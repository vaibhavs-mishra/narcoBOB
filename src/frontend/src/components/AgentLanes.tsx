import { Button, HTMLSelect, NonIdealState, Tag, Tooltip } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import { AGENT_IDS, type AgentId } from "../contracts";
import { revealPanel } from "../layout/layouts";
import { useStore, type LaneState } from "../store";
import { agentLabel } from "../theme";

const STATUS_INTENT = { idle: "none", running: "primary", done: "success", fallback: "warning", failed: "danger" } as const;

function Lane({ agent, lane, t0, span }: { agent: AgentId; lane: LaneState; t0: number; span: number }) {
  const last = lane.findings[lane.findings.length - 1];
  return (
    <div className={`lane lane-${lane.status}`}>
      <div className="lane-head">
        <span className="lane-name">{agentLabel[agent]}</span>
        <Tag minimal intent={STATUS_INTENT[lane.status]}>
          {lane.status === "fallback" ? "done" : lane.status}
          {lane.attempt > 1 ? ` · try ${lane.attempt}` : ""}
        </Tag>
        {lane.source && (
          <Tag minimal className={`src src-${lane.source}`}>{lane.source === "bob" ? "IBM Bob" : "fallback"}</Tag>
        )}
      </div>
      <div className="lane-track">
        {lane.calls.map((c, i) => {
          const x = ((Date.parse(c.wall_at) - t0) / span) * 100;
          return (
            <Tooltip key={i} content={`${c.tool}${c.ok ? "" : ` · ${c.error_code}`} · ${c.duration_ms} ms`} placement="top">
              <span className={`blip${c.ok ? "" : " blip-err"}`} style={{ left: `${Math.min(99, Math.max(0, x))}%` }} />
            </Tooltip>
          );
        })}
        {lane.status === "running" && <span className="lane-pulse" />}
      </div>
      <div className="lane-note muted small" title={last?.summary}>
        {last ? last.summary : `${lane.calls.length} tool calls`}
      </div>
    </div>
  );
}

export function AgentLanes() {
  const runs = useStore((s) => s.runs);
  const order = useStore((s) => s.runOrder);
  const focus = useStore((s) => s.focusRunId);
  const focusRun = useStore((s) => s.focusRun);
  const openReport = useStore((s) => s.openReport);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, []);

  const run = focus ? runs[focus] : undefined;
  if (!run) {
    return <NonIdealState icon="people" title="The Narclings are idle" description="Four IBM Bob agents review every alert: Steward, Analyst, Skeptic, Writer." />;
  }
  const s = run.summary;
  const t0 = s.wall_started_at ? Date.parse(s.wall_started_at) : now;
  const end = s.wall_finished_at ? Date.parse(s.wall_finished_at) : now;
  const span = Math.max(30_000, end - t0);
  return (
    <div className="lanes">
      <div className="lanes-head">
        <span className="lanes-title">Narclings</span>
        <HTMLSelect minimal value={s.run_id} onChange={(e) => focusRun(e.currentTarget.value)}
          options={order.map((id) => ({ value: id, label: `run …${id.slice(-6)} · ${runs[id]?.summary.status ?? ""}` }))} />
        <span className="muted small">{s.cells.length} cell(s) · {end - t0 < 1000 ? "<1" : Math.round((end - t0) / 1000)} s</span>
        <Tag minimal intent={s.status === "DONE" ? "success" : s.status === "RUNNING" ? "primary" : s.status === "QUEUED" ? "none" : "warning"}>{s.status}</Tag>
        {run.reportReady && <Button small icon="document" text="Open brief" onClick={() => { openReport(s.run_id); revealPanel("brief"); }} />}
      </div>
      {AGENT_IDS.map((a) => <Lane key={a} agent={a} lane={run.lanes[a]} t0={t0} span={span} />)}
    </div>
  );
}
