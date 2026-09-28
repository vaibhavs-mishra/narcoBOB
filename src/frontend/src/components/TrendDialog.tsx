import { Button, ButtonGroup, Callout, Classes, Dialog } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Timeseries } from "../contracts";
import { tokens } from "../theme";

const RANGES = [14, 28, 60] as const; // the API serves at most 60 buckets
type Range = (typeof RANGES)[number];

/** The cell's events per sim-day, large, one line per event type. */
export function TrendDialog({ cell, isOpen, onClose }: { cell: string; isOpen: boolean; onClose: () => void }) {
  const [range, setRange] = useState<Range>(28);
  const [ts, setTs] = useState<Timeseries | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    api
      .timeseries(cell, range)
      .then((t) => !cancelled && (setTs(t), setError(null)))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [cell, range, isOpen]);

  const n = ts?.buckets.length ?? 0;
  const data = ts
    ? ts.buckets.map((_, i) => ({
        day: i - n + 1,
        overdose: ts.series.overdose?.[i] ?? 0,
        seizure: ts.series.seizure?.[i] ?? 0,
        arrest: ts.series.arrest?.[i] ?? 0,
      }))
    : [];
  const total = (k: "overdose" | "seizure" | "arrest") => data.reduce((s, d) => s + d[k], 0);

  return (
    <Dialog isOpen={isOpen} onClose={onClose} title={<span className="mono">{cell} · events per sim-day</span>} icon="timeline-line-chart" className="trend-dialog">
      <div className={Classes.DIALOG_BODY}>
        <div className="trend-bar">
          <ButtonGroup>
            {RANGES.map((r) => (
              <Button key={r} small active={range === r} text={`${r} days`} onClick={() => setRange(r)} />
            ))}
          </ButtonGroup>
          {ts && (
            <span className="muted small mono">
              totals · overdoses {total("overdose")} · seizures {total("seizure")} · arrests {total("arrest")}
            </span>
          )}
        </div>
        {error && <Callout intent="danger">{error}</Callout>}
        <div className="trend-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 16, bottom: 4, left: -8 }}>
              <CartesianGrid stroke={tokens.border} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" tick={{ fill: tokens.muted, fontSize: 11 }} tickLine={false} axisLine={{ stroke: tokens.border }} />
              <YAxis allowDecimals={false} tick={{ fill: tokens.muted, fontSize: 11 }} tickLine={false} axisLine={false} />
              <ChartTooltip contentStyle={{ background: tokens.panelRaised, border: `1px solid ${tokens.border}` }} labelFormatter={(v) => `day ${v}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="linear" dataKey="overdose" name="overdoses (harm)" stroke={tokens.red} dot={false} strokeWidth={2} isAnimationActive={false} />
              <Line type="linear" dataKey="seizure" name="seizures" stroke={tokens.cyan} dot={false} strokeWidth={1.5} isAnimationActive={false} />
              <Line type="linear" dataKey="arrest" name="NDPS arrests" stroke={tokens.violet} dot={false} strokeWidth={1.5} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="muted small">Counts per simulated day from the event store; the x-axis is sim-days before now (0 = today). Rising harm with flat enforcement drives the divergence score.</div>
      </div>
    </Dialog>
  );
}
