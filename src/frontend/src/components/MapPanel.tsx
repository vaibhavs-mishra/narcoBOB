import { Button } from "@blueprintjs/core";
import { useState } from "react";
import { MapView } from "./MapView";

/** The map with its (collapsible) legend. */
export function MapPanel() {
  const [legend, setLegend] = useState(true);
  return (
    <div className="map">
      <MapView />
      <div className="map-legend">
        <Button minimal small className="legend-toggle" icon={legend ? "chevron-down" : "chevron-up"}
          text="Legend" onClick={() => setLegend(!legend)} />
        {legend && (
          <>
            <div><span className="lg-ramp" /> score 30 → 100 (height and colour)</div>
            <div><span className="lg-confirmed" /> confirmed by the Skeptic</div>
            <div>
              <span className="lg-dot" style={{ background: "var(--red)" }} /> overdose{" "}
              <span className="lg-dot" style={{ background: "var(--cyan)" }} /> seizure{" "}
              <span className="lg-dot" style={{ background: "var(--violet)" }} /> arrest
            </div>
          </>
        )}
      </div>
    </div>
  );
}
