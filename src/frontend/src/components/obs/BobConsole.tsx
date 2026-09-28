import { Button, NonIdealState, Tab, Tabs, Tag } from "@blueprintjs/core";
import { useState } from "react";
import { AGENT_IDS, type AgentId } from "../../contracts";
import { useStore } from "../../store";
import { agentLabel } from "../../theme";
import { useRunLog } from "./useRunLog";

const TERMINAL = new Set(["done", "fallback", "failed"]);
// Bob Shell colours its output; show it as plain text
// oxlint-disable-next-line no-control-regex
const ANSI = /\u001b\[[0-9;?]*[A-Za-z]/g;

function StepConsole({ runId, agent }: { runId: string; agent: AgentId }) {
  const lane = useStore((s) => s.runs[runId]?.lanes[agent]);
  const stored = useRunLog(runId);
  if (!lane || lane.status === "idle") return <div className="muted pad">This agent has not started yet.</div>;
  // only show output once the step has finished here, so replay never reveals it early
  if (!TERMINAL.has(lane.status)) return <div className="muted pad">Running… console output appears when the step finishes.</div>;
  const step = stored?.log.steps.find((s) => s.agent_id === agent);
  if (!step) return <div className="muted pad">Loading…</div>;
  const text = (step.log ?? "").replace(ANSI, "");
  return (
    <div className="console">
      <div className="console-head">
        <Tag minimal className={`src src-${step.source ?? "fallback"}`}>{step.source === "bob" ? "IBM Bob Shell" : "fallback agent"}</Tag>
        <span className="muted small mono">{step.status} · attempt {step.attempt} · {step.tool_calls} tool calls</span>
        {text && <Button minimal small icon="duplicate" text="Copy" onClick={() => void navigator.clipboard.writeText(text)} />}
      </div>
      {step.source !== "bob" && (
        <div className="muted small console-note">Deterministic fallback agent: no Bob Shell console output.</div>
      )}
      {text ? <pre className="console-out">{text}</pre> : step.source === "bob" && <div className="muted pad">The process printed nothing.</div>}
    </div>
  );
}

export function BobConsole() {
  const runId = useStore((s) => s.focusRunId);
  const [tab, setTab] = useState<AgentId>("steward");
  if (!runId) return <NonIdealState icon="code" title="No run selected" description="Pick a run in the Runs panel." />;
  return (
    <div className="bob-console">
      <Tabs id="console" selectedTabId={tab} onChange={(t) => setTab(t as AgentId)} renderActiveTabPanelOnly>
        {AGENT_IDS.map((a) => (
          <Tab key={a} id={a} title={agentLabel[a]} panel={<StepConsole runId={runId} agent={a} />} />
        ))}
      </Tabs>
    </div>
  );
}
