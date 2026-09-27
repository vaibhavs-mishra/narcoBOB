import { NonIdealState, Tag } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import type { Alert } from "../contracts";
import { useStore } from "../store";
import { severityColor, verdictIntent } from "../theme";

function age(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

function AlertRow({ a, now }: { a: Alert; now: number }) {
  const select = useStore((s) => s.select);
  const selected = useStore((s) => s.selectedCell === a.cell);
  const flashedAt = useStore((s) => s.flashAlertIds[a.alert_id]);
  const flash = flashedAt !== undefined && now - flashedAt < 2500;
  const final = a.final_severity ?? null;
  const runStatus = useStore((s) => (a.run_id ? s.runs[a.run_id]?.summary.status : undefined));
  const reviewed = runStatus === "DONE" || runStatus === "FAILED_WITH_FALLBACK";
  return (
    <button className={`alert-row${selected ? " selected" : ""}${flash ? " flash" : ""}`} onClick={() => select(a.cell)}>
      <span className="sev-bar" style={{ background: severityColor[final ?? a.severity] }} />
      <div className="alert-main">
        <div className="alert-top">
          <span className="sev" style={{ color: severityColor[a.severity] }}>
            {a.severity}
          </span>
          {final && final !== a.severity && (
            <span className="sev-final">
              → <span style={{ color: severityColor[final] }}>{final}</span>
            </span>
          )}
          <span className="mono muted score">{a.score}</span>
          <span className="mono muted age">{age(a.wall_created_at, now)}</span>
        </div>
        <div className="alert-sub">
          <span className="mono cell-id">{a.cell}</span>
          {a.verdict ? (
            <Tag minimal intent={verdictIntent[a.verdict]} className="verdict-tag">
              {a.verdict.replace("_", " ")}
            </Tag>
          ) : a.run_id && reviewed ? (
            <Tag minimal className="verdict-tag" title="The run reviewed only its most severe cells">not reviewed</Tag>
          ) : a.run_id ? (
            <Tag minimal className="verdict-tag pending">agents reviewing</Tag>
          ) : (
            <Tag minimal className="verdict-tag pending">queued</Tag>
          )}
        </div>
        <div className="alert-reason muted">{a.reason} · sim {a.sim_ts.slice(0, 10)}</div>
      </div>
    </button>
  );
}

export function AlertFeed() {
  const alerts = useStore((s) => s.alerts);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <section className="panel alert-feed">
      <h2 className="panel-title">
        Alerts <span className="muted mono">{alerts.length}</span>
      </h2>
      <div className="scroll">
        {alerts.length === 0 ? (
          <NonIdealState icon="shield" title="No alerts" description="Cells alert when they enter HIGH or CRITICAL." />
        ) : (
          alerts.map((a) => <AlertRow key={a.alert_id} a={a} now={now} />)
        )}
      </div>
    </section>
  );
}
