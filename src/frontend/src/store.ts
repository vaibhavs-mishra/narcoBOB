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

export interface RunView {
  summary: RunSummary;
  lanes: Record<AgentId, LaneState>;
  reportReady: boolean;
}

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
  bottomTab: "agents" | "report" | "ticker";
  reportRunId: string | null;

  applySnapshot: (s: Snapshot) => void;
  applyMessage: (m: WsMessage) => void;
  setConnected: (c: boolean, mode?: "live" | "replay") => void;
  setHealth: (h: Health | null) => void;
  select: (cell: string | null) => void;
  setBottomTab: (t: State["bottomTab"]) => void;
  openReport: (runId: string) => void;
  focusRun: (runId: string) => void;
}

let pingId = 0;
const PING_TTL_MS = 2500;

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
    [summary.run_id]: { summary, lanes, reportReady: existing?.reportReady ?? false },
  };
  const runOrder = state.runOrder.includes(summary.run_id)
    ? state.runOrder
    : [summary.run_id, ...state.runOrder].slice(0, 20);
  return { runs, runOrder };
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
  bottomTab: "agents",
  reportRunId: null,

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
          return { ...next, ...withRun(state, m.payload), focusRunId: focus };
        }
        case "agent.step": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const lane = run.lanes[m.payload.agent_id];
          const lanes = {
            ...run.lanes,
            [m.payload.agent_id]: { ...lane, status: m.payload.status, source: m.payload.source ?? lane.source, attempt: m.payload.attempt },
          };
          return { ...next, runs: { ...state.runs, [m.payload.run_id]: { ...run, lanes } } };
        }
        case "agent.tool_call": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const lane = run.lanes[m.payload.agent_id];
          if (!lane) return next;
          const lanes = { ...run.lanes, [m.payload.agent_id]: { ...lane, calls: [...lane.calls, m.payload] } };
          return { ...next, runs: { ...state.runs, [m.payload.run_id]: { ...run, lanes } } };
        }
        case "finding.posted": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          const lane = run.lanes[m.payload.agent_id];
          const lanes = { ...run.lanes, [m.payload.agent_id]: { ...lane, findings: [...lane.findings, m.payload] } };
          return { ...next, runs: { ...state.runs, [m.payload.run_id]: { ...run, lanes } } };
        }
        case "report.ready": {
          const run = state.runs[m.payload.run_id];
          if (!run) return next;
          return { ...next, runs: { ...state.runs, [m.payload.run_id]: { ...run, reportReady: true } } };
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
  setBottomTab: (bottomTab) => set({ bottomTab }),
  openReport: (reportRunId) => set({ reportRunId, bottomTab: "report" }),
  focusRun: (focusRunId) => set({ focusRunId, bottomTab: "agents" }),
}));

