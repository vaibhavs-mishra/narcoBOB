import { Button, Callout, NonIdealState, Tag } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { CellDetail, Driver, Timeseries } from "../contracts";
import { useStore } from "../store";
import { driverLabel, severityColor, tokens, verdictIntent } from "../theme";

const DRIVERS: Driver[] = ["accel", "div", "spill", "gi"];

function Gauge({ score, color }: { score: number; color: string }) {
  const angle = (score / 100) * 180;
  const rad = (Math.PI * (180 - angle)) / 180;
  const x = 60 + 48 * Math.cos(rad);
  const y = 60 - 48 * Math.sin(rad);
  return (
    <svg viewBox="0 0 120 68" className="gauge" role="img" aria-label={`score ${score} of 100`}>
      <path d="M12 60 A48 48 0 0 1 108 60" stroke={tokens.border} strokeWidth="9" fill="none" />
      <path d={`M12 60 A48 48 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`} stroke={color} strokeWidth="9" fill="none" />
      <text x="60" y="58" textAnchor="middle" className="gauge-num">
        {score}
      </text>
    </svg>
  );
}

function Components({ d }: { d: CellDetail }) {
  const max = Math.max(1, ...DRIVERS.map((k) => Math.abs(d.components[k].contrib)));
  return (
    <div className="components">
      {DRIVERS.map((k) => {
        const c = d.components[k];
        const w = (Math.abs(c.contrib) / max) * 50;
        return (
          <div key={k} className="comp-row">
            <span className="comp-label">{driverLabel[k]}</span>
            <div className="comp-track">
              <span className="comp-zero" />
              <span
                className={`comp-bar ${c.contrib >= 0 ? "pos" : "neg"}`}
                style={c.contrib >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
              />
            </div>
            <span className="mono comp-num">{c.contrib >= 0 ? "+" : ""}{c.contrib.toFixed(2)}</span>
          </div>
        );
      })}
      <div className="muted small">bars: weight × z-score; z in units of the cell's own noise</div>
    </div>
  );
}

function Spark({ ts }: { ts: Timeseries }) {
  const od = ts.series.overdose ?? [];
  const sz = ts.series.seizure ?? [];
  const ar = ts.series.arrest ?? [];
  const data = ts.buckets.map((_, i) => ({ b: i - ts.buckets.length + 1, od: od[i] ?? 0, enf: (sz[i] ?? 0) + (ar[i] ?? 0) }));
  return (
    <div className="spark">
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -28 }}>
          <XAxis dataKey="b" tick={{ fill: tokens.muted, fontSize: 10 }} tickLine={false} axisLine={{ stroke: tokens.border }} />
          <YAxis allowDecimals={false} tick={{ fill: tokens.muted, fontSize: 10 }} tickLine={false} axisLine={false} />
          <ChartTooltip contentStyle={{ background: tokens.panelRaised, border: `1px solid ${tokens.border}` }} labelFormatter={(v) => `day ${v}`} />
          <Line type="monotone" dataKey="od" name="overdoses" stroke={tokens.red} dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line type="monotone" dataKey="enf" name="seizures + arrests" stroke={tokens.cyan} dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <div className="legend small">
        <span style={{ color: tokens.red }}>● overdoses (harm)</span>
        <span style={{ color: tokens.cyan }}>● seizures + arrests (enforcement)</span>
      </div>
    </div>
  );
}

export function CellDrawer() {
  const cell = useStore((s) => s.selectedCell);
  const live = useStore((s) => (s.selectedCell ? s.cells[s.selectedCell] : undefined));
  const select = useStore((s) => s.select);
  const openReport = useStore((s) => s.openReport);
  const [detail, setDetail] = useState<CellDetail | null>(null);
  const [ts, setTs] = useState<Timeseries | null>(null);
  const [error, setError] = useState<string | null>(null);

  // refetch when the cell changes, and whenever its live score or verdict changes
  const version = live ? `${live.score}|${live.verdict ?? ""}|${live.sim_ts}` : "";
  useEffect(() => {
    if (!cell) return;
    let cancelled = false;
    Promise.all([api.cell(cell), api.timeseries(cell, 28)])
      .then(([d, t]) => {
        if (!cancelled) {
          setDetail(d);
          setTs(t);
          setError(null);
        }
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [cell, version]);

  if (!cell) {
    return (
      <aside className="panel drawer">
        <NonIdealState icon="select" title="No cell selected" description="Click a hexagon or an alert." />
      </aside>
    );
  }
  if (error) return <aside className="panel drawer"><Callout intent="danger">{error}</Callout></aside>;
  if (!detail || detail.cell !== cell) return <aside className="panel drawer"><div className="muted pad">Loading…</div></aside>;

  const final = detail.final_severity ?? null;
  const v = detail.latest_verdict;
  const reportRun = detail.alerts.find((a) => a.run_id && a.verdict)?.run_id ?? null;
  return (
    <aside className="panel drawer">
      <div className="drawer-head">
        <div>
          <div className="mono cell-title">{detail.cell}</div>
          <div className="muted small">sim day ending {detail.sim_ts.slice(0, 10)}</div>
        </div>
        <Button minimal icon="cross" onClick={() => select(null)} aria-label="Close" />
      </div>
      <div className="drawer-score">
        <Gauge score={detail.score} color={severityColor[detail.severity]} />
        <div className="sev-block">
          <div className="muted small">engine</div>
          <div className="sev-big" style={{ color: severityColor[detail.severity] }}>{detail.severity}</div>
          <div className="muted small">after Skeptic</div>
          <div className="sev-big" style={{ color: final ? severityColor[final] : tokens.muted }}>{final ?? "—"}</div>
        </div>
      </div>
      <div className="support-row">
        <Tag minimal>support {detail.support} events / 7 d</Tag>
        <Tag minimal intent={detail.confidence === "low" ? "warning" : "none"}>{detail.confidence} confidence</Tag>
      </div>
      <h3 className="section">Why this score</h3>
      <Components d={detail} />
      <h3 className="section">Last 28 sim-days</h3>
      {ts && <Spark ts={ts} />}
      <h3 className="section">Skeptic</h3>
      {v ? (
        <div className="verdict">
          <Tag intent={verdictIntent[v.verdict]} large>{v.verdict.replace("_", " ")} → {v.final_severity}</Tag>
          <p>{v.rationale}</p>
          <div className="checks">
            {Object.entries(v.checks).map(([k, r]) => (
              <span key={k} className={`check check-${r}`}>{k.replace("_", " ")} · {r}</span>
            ))}
          </div>
          {reportRun && <Button small icon="document" text="Open brief" onClick={() => openReport(reportRun)} />}
        </div>
      ) : (
        <div className="muted small">Not reviewed yet. Agents review a cell after it alerts.</div>
      )}
      <h3 className="section">Neighbours</h3>
      <div className="neighbours">
        {detail.neighbors.map((n) => (
          <button key={n.cell} className="nb" onClick={() => select(n.cell)} title={n.cell}>
            <span className="dot" style={{ background: severityColor[n.severity] }} />
            <span className="mono">{n.score}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
