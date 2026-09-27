import { Callout, NonIdealState, Tag } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import type { Report } from "../contracts";
import { useStore } from "../store";

export function ReportViewer() {
  const reportRunId = useStore((s) => s.reportRunId);
  const latest = useStore((s) => s.runOrder.find((id) => s.runs[id]?.reportReady) ?? null);
  const runId = reportRunId ?? latest;
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    api.report(runId).then((r) => { setReport(r); setError(null); }).catch((e: unknown) => setError(String(e)));
  }, [runId]);

  if (!runId) return <NonIdealState icon="document" title="No brief yet" description="The Intel Writer publishes a brief after each agent run." />;
  if (error) return <Callout intent="warning">{error}</Callout>;
  if (!report) return <div className="muted pad">Loading…</div>;
  return (
    <div className="report">
      <div className="report-meta">
        <Tag minimal className={`src src-${report.source}`}>written by {report.source === "bob" ? "IBM Bob agents" : "fallback agents"}</Tag>
        <Tag minimal>{report.recommendations.length} recommendations</Tag>
        <span className="muted small mono">run {report.run_id}</span>
      </div>
      <div className="markdown"><ReactMarkdown>{report.markdown}</ReactMarkdown></div>
    </div>
  );
}
