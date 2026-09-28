import { NonIdealState, Tag } from "@blueprintjs/core";
import { AGENT_IDS, type ToolCallMsg } from "../../contracts";
import { useStore } from "../../store";
import { agentLabel } from "../../theme";
import { useRunLog } from "./useRunLog";

const STATUS_INTENT = { QUEUED: "none", RUNNING: "primary", DONE: "success", FAILED_WITH_FALLBACK: "warning" } as const;

function seconds(from: string | null, to: string | null | undefined): string {
  if (!from) return "—";
  const ms = (to ? Date.parse(to) : Date.now()) - Date.parse(from);
  return ms < 1000 ? "<1 s" : `${Math.round(ms / 1000)} s`;
}

function RunRow({ runId }: { runId: string }) {
  const run = useStore((s) => s.runs[runId]);
  const focused = useStore((s) => s.focusRunId === runId);
  const focusRun = useStore((s) => s.focusRun);
  const live: ToolCallMsg[] = run ? AGENT_IDS.flatMap((a) => run.lanes[a].calls) : [];
  // after a reload the live lanes are empty: fall back to the stored tool calls
  const stored = useRunLog(live.length === 0 ? runId : null);
  if (!run) return null;
  const calls = live.length ? live : (stored?.log.tool_calls ?? []);
  const errors = calls.filter((c) => !c.ok).length;
  const s = run.summary;
  return (
    <button className={`run-row${focused ? " selected" : ""}`} onClick={() => focusRun(runId)}>
      <div className="run-top">
        <span className="mono">run …{runId.slice(-6)}</span>
        <Tag minimal intent={STATUS_INTENT[s.status]}>{s.status.replaceAll("_", " ")}</Tag>
      </div>
      <div className="run-meta muted small mono">
        {s.cells.length} cell{s.cells.length === 1 ? "" : "s"} · {calls.length} calls
        {errors > 0 && <span className="err"> · {errors} rejected</span>} · {seconds(s.wall_started_at, s.wall_finished_at)}
      </div>
      <div className="run-sources">
        {AGENT_IDS.map((a) => {
          const src = run.lanes[a].source;
          return (
            <span key={a} className={`src-chip src-${src ?? "none"}`} title={`${agentLabel[a]}: ${src ?? run.lanes[a].status}`}>
              {agentLabel[a].split(" ").pop()}
            </span>
          );
        })}
      </div>
    </button>
  );
}

export function RunList() {
  const order = useStore((s) => s.runOrder);
  if (!order.length) {
    return <NonIdealState icon="history" title="No agent runs yet" description="A run starts when a cell raises an alert." />;
  }
  return (
    <div className="scroll run-list">
      {order.map((id) => <RunRow key={id} runId={id} />)}
    </div>
  );
}
