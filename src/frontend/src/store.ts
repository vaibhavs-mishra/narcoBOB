// Zustand store shaped by the Snapshot, kept current by WebSocket deltas.
import { create } from "zustand";
import type {
  AgentId,
  Alert,
  CellScore,
  FindingPostedMsg,
  Health,
  Kpis,
  PublicConfig,
  RunSummary,
  SimStatus,
  Snapshot,
  StepStatus,
  TickerEvent,
  ToolCallMsg,
  WsMessage,
} from "./contracts";

export interface Ping extends TickerEvent {
  id: number;
  at: number; // performance.now() when received
}

export interface LaneState {
  status: StepStatus | "idle";
  source: "bob" | "fallback" | null;
  attempt: number;
  calls: ToolCallMsg[];
  findings: FindingPostedMsg[];
}

/** One line of the observability view's agent log. */
export interface LogEntry {
  at: string; // wall-clock ISO time
  agent_id: AgentId | null;
  kind: "run" | "step" | "tool" | "finding";
  text: string;
  ok: boolean;
}

export interface RunView {
  summary: RunSummary;
  lanes: Record<AgentId, LaneState>;
  reportReady: boolean;
  log: LogEntry[]; // live entries from the WebSocket, oldest first
}

export type View = "command" | "observability";

const emptyLane = (): LaneState => ({ status: "idle", source: null, attempt: 0, calls: [], findings: [] });
const emptyLanes = (): Record<AgentId, LaneState> => ({
  steward: emptyLane(),
  analyst: emptyLane(),
  skeptic: emptyLane(),
  writer: emptyLane(),
});

interface State {
  connected: boolean;
  mode: "live" | "replay";
  seq: number;
  config: PublicConfig | null;
  sim: SimStatus | null;
  kpis: Kpis | null;
  health: Health | null;
  cells: Record<string, CellScore>;
  alerts: Alert[];
  flashAlertIds: Record<string, number>;
  runs: Record<string, RunView>;
  runOrder: string[]; // newest first
  focusRunId: string | null;
  ticker: TickerEvent[];
  pings: Ping[];
  selectedCell: string | null;
  reportRunId: string | null;
  view: View;
  helpMode: boolean;

  applySnapshot: (s: Snapshot) => void;
  applyMessage: (m: WsMessage) => void;
  setConnected: (c: boolean, mode?: "live" | "replay") => void;
  setHealth: (h: Health | null) => void;
  select: (cell: string | null) => void;
  setView: (v: View) => void;
  setHelpMode: (on: boolean) => void;
  openReport: (runId: string) => void;
  focusRun: (runId: string) => void;
}

let pingId = 0;
const PING_TTL_MS = 2500;
const LOG_CAP = 1000;

function appendLog(state: State, runId: string, entry: LogEntry): Pick<State, "runs"> | null {
  const run = state.runs[runId];
  if (!run) return null;
  return { runs: { ...state.runs, [runId]: { ...run, log: [...run.log, entry].slice(-LOG_CAP) } } };
}

function upsertAlert(alerts: Alert[], a: Alert): Alert[] {
  const rest = alerts.filter((x) => x.alert_id !== a.alert_id);
  return [a, ...rest].sort((x, y) => (x.wall_created_at < y.wall_created_at ? 1 : -1)).slice(0, 100);
}

function withRun(state: State, summary: RunSummary): Pick<State, "runs" | "runOrder"> {
  const existing = state.runs[summary.run_id];
  const lanes = existing?.lanes ?? emptyLanes();
  for (const s of summary.steps) {
    lanes[s.agent_id] = { ...lanes[s.agent_id], status: s.status, source: s.source ?? null };
  }
  const runs = {
    ...state.runs,
    [summary.run_id]: { summary, lanes, reportReady: existing?.reportReady ?? false, log: existing?.log ?? [] },
  };
  const runOrder = state.runOrder.includes(summary.run_id)
    ? state.runOrder
    : [summary.run_id, ...state.runOrder].slice(0, 20);
  return { runs, runOrder };
}

/** A tool call as a log line; shared by the live path and the REST backfill. */
export function toolEntry(c: ToolCallMsg): LogEntry {
  return {
    at: c.wall_at, agent_id: c.agent_id, kind: "tool", ok: c.ok,
    text: `${c.tool} ${c.ok ? "✓" : `✗ ${c.error_code ?? "error"}`} · ${c.duration_ms} ms`,
  };
}

export const useStore = create<State>((set) => ({
  connected: false,
  mode: "live",
  seq: 0,
  config: null,
  sim: null,
  kpis: null,
  health: null,
  cells: {},
  alerts: [],
  flashAlertIds: {},
  runs: {},
  runOrder: [],
  focusRunId: null,
  ticker: [],
  pings: [],
  selectedCell: null,
  reportRunId: null,
  view: "command",
  helpMode: false,

  applySnapshot: (s) =>
    set((state) => {
      const cells: Record<string, CellScore> = {};
      for (const c of s.cells) cells[c.cell] = c;
      let next: Partial<State> = { config: s.config, sim: s.sim, kpis: s.kpis, cells, alerts: s.alerts, seq: s.seq };
      let runsState: Pick<State, "runs" | "runOrder"> = { runs: {}, runOrder: [] };
      for (const r of [...s.runs].reverse()) runsState = withRun({ ...state, ...runsState }, r);
      next = { ...next, ...runsState, focusRunId: state.focusRunId ?? s.runs[0]?.run_id ?? null };
      return next;
    }),

  applyMessage: (m) =>
    set((state) => {
      const next: Partial<State> = { seq: m.seq };
      switch (m.type) {
        case "hello":
          return { seq: m.payload.seq, mode: m.payload.mode };
        case "scores.update": {
          const cells = { ...state.cells };
          for (const c of m.payload.cells) cells[c.cell] = c;
          return { ...next, cells, kpis: m.payload.kpis };
        }
        case "event.batch": {
          const now = performance.now();
          const fresh = m.payload.events.map((e) => ({ ...e, id: pingId++, at: now }));
          const pings = [...state.pings.filter((p) => now - p.at < PING_TTL_MS), ...fresh].slice(-600);
          const ticker = [...m.payload.events.slice(-30).reverse(), ...state.ticker].slice(0, 120);
          return { ...next, pings, ticker };
        }
        case "alert.raised":
          return {
            ...next,
            alerts: upsertAlert(state.alerts, m.payload),
            flashAlertIds: { ...state.flashAlertIds, [m.payload.alert_id]: Date.now() },
          };
        case "alert.updated": {
          const cells = { ...state.cells };
          const c = cells[m.payload.cell];
          if (c) cells[m.payload.cell] = { ...c, final_severity: m.payload.final_severity, verdict: m.payload.verdict };
          return { ...next, alerts: upsertAlert(state.alerts, m.payload), cells };
        }
        case "run.queued":
        case "run.started":
        case "run.finished": {
          const focus = m.type === "run.started" ? m.payload.run_id : state.focusRunId ?? m.payload.run_id;
          const withSummary = { ...state, ...withRun(state, m.payload) };
          const cells = m.payload.cells.length;
          const logged = appendLog(withSummary, m.payload.run_id, {
            at: m.wall_ts, agent_id: null, kind: "run", ok: m.payload.status !== "FAILED_WITH_FALLBACK",
            text: `run ${m.type.slice(4)} · ${m.payload.status} · ${cells} cell${cells === 1 ? "" : "s"}`,
          });
          return { ...next, runOrder: withSummary.runOrder, ...(logged ?? { runs: withSummary.runs }), focusRunId: focus };
        }
        case "agent.step": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const lane = run.lanes[m.payload.agent_id];
          const lanes = {
            ...run.lanes,
            [m.payload.agent_id]: { ...lane, status: m.payload.status, source: m.payload.source ?? lane.source, attempt: m.payload.attempt },
          };
          const p = m.payload;
          const entry: LogEntry = {
            at: m.wall_ts, agent_id: p.agent_id, kind: "step", ok: p.status !== "failed",
            text: `step ${p.status}${p.source ? ` · ${p.source === "bob" ? "IBM Bob" : "fallback"}` : ""}${p.attempt > 1 ? ` · attempt ${p.attempt}` : ""}`,
          };
          return { ...next, runs: { ...state.runs, [p.run_id]: { ...run, lanes, log: [...run.log, entry].slice(-LOG_CAP) } } };
        }
        case "agent.tool_call": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const lane = run.lanes[m.payload.agent_id];
          if (!lane) return next;
          const lanes = { ...run.lanes, [m.payload.agent_id]: { ...lane, calls: [...lane.calls, m.payload] } };
          const log = [...run.log, toolEntry(m.payload)].slice(-LOG_CAP);
          return { ...next, runs: { ...state.runs, [m.payload.run_id]: { ...run, lanes, log } } };
        }
        case "finding.posted": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const lane = run.lanes[m.payload.agent_id];
          const lanes = { ...run.lanes, [m.payload.agent_id]: { ...lane, findings: [...lane.findings, m.payload] } };
          const p = m.payload;
          const entry: LogEntry = {
            at: m.wall_ts, agent_id: p.agent_id, kind: "finding", ok: true,
            text: `${p.kind}${p.cell ? ` · ${p.cell}` : ""} · ${p.summary}`,
          };
          return { ...next, runs: { ...state.runs, [p.run_id]: { ...run, lanes, log: [...run.log, entry].slice(-LOG_CAP) } } };
        }
        case "report.ready": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const entry: LogEntry = { at: m.wall_ts, agent_id: "writer", kind: "run", ok: true, text: "brief published" };
          return { ...next, runs: { ...state.runs, [m.payload.run_id]: { ...run, reportReady: true, log: [...run.log, entry] } } };
        }
        case "sim.status":
          return { ...next, sim: m.payload };
        case "heartbeat":
          return next;
      }
    }),

  setConnected: (connected, mode) => set(mode ? { connected, mode } : { connected }),
  setHealth: (health) => set({ health }),
  select: (selectedCell) => set({ selectedCell }),
  setView: (view) => set({ view }),
  setHelpMode: (helpMode) => set({ helpMode }),
  openReport: (reportRunId) => set({ reportRunId }),
  focusRun: (focusRunId) => set({ focusRunId }),
}));

