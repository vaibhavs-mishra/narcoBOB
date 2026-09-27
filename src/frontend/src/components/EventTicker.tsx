import { NonIdealState } from "@blueprintjs/core";
import { useStore } from "../store";

const COLOR = { overdose: "var(--red)", seizure: "var(--cyan)", arrest: "var(--violet)" } as const;

export function EventTicker() {
  const ticker = useStore((s) => s.ticker);
  if (!ticker.length) return <NonIdealState icon="pulse" title="No live events yet" description="Events stream in once the simulated feed is live." />;
  return (
    <div className="ticker">
      {ticker.map((e, i) => (
        <div key={`${e.ts}-${i}`} className="tick mono">
          <span className="muted">{e.ts.replace("T", " ").slice(0, 16)}</span>
          <span style={{ color: COLOR[e.type] }}>{e.type}</span>
          <span>{e.cell}</span>
          <span className="muted">{e.lat.toFixed(3)}, {e.lon.toFixed(3)}</span>
        </div>
      ))}
    </div>
  );
}
