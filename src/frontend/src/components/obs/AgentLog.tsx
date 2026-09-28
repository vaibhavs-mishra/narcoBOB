import { Button, ButtonGroup, NonIdealState, Switch } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { AGENT_IDS, type AgentId, type Finding, type RunLog, type ToolCallMsg } from "../../contracts";
import { toolEntry, useStore, type LogEntry } from "../../store";
import { agentLabel } from "../../theme";
import { useRunLog } from "./useRunLog";

type Kind = LogEntry["kind"];
const KINDS: Kind[] = ["run", "step", "tool", "finding"];

function findingText(f: Finding): string {
  const p = f.payload;
  const detail =
    typeof p.verdict === "string" ? `${p.verdict} → ${String(p.final_severity ?? "")}`
    : typeof p.summary === "string" ? p.summary
    : Object.keys(p).slice(0, 4).join(", "); // prettier-ignore
  return `${f.kind}${f.cell ? ` · ${f.cell}` : ""} · ${detail}`;
}

/** Rebuild the timeline from the stored run (used when this page did not see the run live). */
function fromStored(log: RunLog, findings: Finding[]): LogEntry[] {
  const out: LogEntry[] = [];
  for (const s of log.steps) {
    out.push({ at: s.wall_started_at, agent_id: s.agent_id, kind: "step", ok: true, text: "step running" });
    if (s.wall_finished_at) {
      const src = s.source === "bob" ? " · IBM Bob" : s.source === "fallback" ? " · fallback" : "";
      out.push({ at: s.wall_finished_at, agent_id: s.agent_id, kind: "step", ok: s.status !== "failed",
        text: `step ${s.status}${src}${s.attempt > 1 ? ` · attempt ${s.attempt}` : ""}` }); // prettier-ignore
    }
  }
  for (const c of log.tool_calls) out.push(toolEntry(c));
  for (const f of findings) out.push({ at: f.wall_at, agent_id: f.agent_id, kind: "finding", ok: true, text: findingText(f) });
  return out.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
}

function Summary({ calls }: { calls: ToolCallMsg[] }) {
  return (
    <div className="log-summary">
      {AGENT_IDS.map((a) => {
        const mine = calls.filter((c) => c.agent_id === a);
        const errors = mine.filter((c) => !c.ok).length;
        return (
          <div key={a} className={`log-stat agent-${a}`}>
            <span className="log-stat-name">{agentLabel[a]}</span>
            <span className="mono">{mine.length} calls</span>
            <span className={`mono${errors ? " err" : " muted"}`}>{errors} rejected</span>
            <span className="mono muted">p50 {mine.length ? `${median(mine.map((c) => c.duration_ms))} ms` : "—"}</span>
          </div>
        );
      })}
    </div>
  );
}

export function AgentLog() {
  const runId = useStore((s) => s.focusRunId);
  const run = useStore((s) => (s.focusRunId ? s.runs[s.focusRunId] : undefined));
  // the live log is complete only if this page saw the run start
  const liveComplete = !!run?.log.some((e) => e.kind === "run" && e.text.startsWith("run started"));
  const stored = useRunLog(liveComplete ? null : runId);
  const [agents, setAgents] = useState<Set<AgentId>>(new Set(AGENT_IDS));
  const [kinds, setKinds] = useState<Set<Kind>>(new Set(KINDS));
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [follow, setFollow] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);

  const entries = useMemo(
    () => (liveComplete ? (run?.log ?? []) : stored ? fromStored(stored.log, stored.findings) : []),
    [liveComplete, run?.log, stored],
  );
  const calls = useMemo(
    () => (liveComplete && run ? AGENT_IDS.flatMap((a) => run.lanes[a].calls) : (stored?.log.tool_calls ?? [])),
    [liveComplete, run, stored],
  );
  const shown = entries.filter(
    (e) => kinds.has(e.kind) && (e.agent_id === null || agents.has(e.agent_id)) && (!errorsOnly || !e.ok),
  );
  useEffect(() => {
    if (follow) bottom.current?.scrollIntoView({ block: "end" });
  }, [follow, shown.length]);

  if (!run || !runId) {
    return <NonIdealState icon="console" title="No run selected" description="Pick a run in the Runs panel." />;
  }
  const t0 = run.summary.wall_started_at ? Date.parse(run.summary.wall_started_at) : Date.parse(entries[0]?.at ?? "");
  const toggle = <T,>(set: Set<T>, v: T, apply: (s: Set<T>) => void) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    apply(next);
  };

  return (
    <div className="agent-log">
      <Summary calls={calls} />
      <div className="log-toolbar">
        <ButtonGroup>
          {AGENT_IDS.map((a) => (
            <Button key={a} small active={agents.has(a)} className={`agent-btn agent-${a}`} text={agentLabel[a].split(" ").pop()}
              onClick={() => toggle(agents, a, setAgents)} />
          ))}
        </ButtonGroup>
        <ButtonGroup>
          {KINDS.map((k) => (
            <Button key={k} small active={kinds.has(k)} text={k === "tool" ? "tool calls" : `${k}s`} onClick={() => toggle(kinds, k, setKinds)} />
          ))}
        </ButtonGroup>
        <Switch checked={errorsOnly} label="Errors only" onChange={() => setErrorsOnly(!errorsOnly)} />
        <Switch checked={follow} label="Follow" onChange={() => setFollow(!follow)} />
        <span className="muted small mono log-count">{shown.length} / {entries.length}</span>
      </div>
      <div className="log-rows mono">
        {shown.map((e, i) => {
          const dt = Math.max(0, (Date.parse(e.at) - t0) / 1000);
          return (
            <div key={i} className={`log-row kind-${e.kind}${e.ok ? "" : " log-err"}`}>
              <span className="muted">+{dt.toFixed(1)}s</span>
              <span className={e.agent_id ? `agent-${e.agent_id}` : "muted"}>{e.agent_id ? agentLabel[e.agent_id] : "run"}</span>
              <span className="muted">{e.kind}</span>
              <span className="log-text">{e.text}</span>
            </div>
          );
        })}
        {!entries.length && (
          <div className="muted pad">{run.summary.status === "QUEUED" ? "Queued: the agents have not started this run yet." : "Loading the run's log…"}</div>
        )}
        <div ref={bottom} />
      </div>
    </div>
  );
}
