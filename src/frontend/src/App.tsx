import { useEffect } from "react";
import { useStore } from "./store";
import { AlertFeed } from "./components/AlertFeed";
import { BottomPanel } from "./components/BottomPanel";
import { CellDrawer } from "./components/CellDrawer";
import { MapView } from "./components/MapView";
import { TopBar } from "./components/TopBar";
import { connect } from "./ws";

export default function App() {
  useEffect(() => connect(), []);
  const hasSelection = useStore((s) => s.selectedCell !== null);
  return (
    <div className={hasSelection ? "shell has-selection" : "shell"}>
      <TopBar />
      <AlertFeed />
      <main className="map">
        <MapView />
        <div className="map-legend">
          <div><span className="lg-ramp" /> score 30 → 100 (height and colour)</div>
          <div><span className="lg-confirmed" /> confirmed by the Skeptic</div>
          <div>
            <span className="lg-dot" style={{ background: "var(--red)" }} /> overdose{" "}
            <span className="lg-dot" style={{ background: "var(--cyan)" }} /> seizure{" "}
            <span className="lg-dot" style={{ background: "var(--violet)" }} /> arrest
          </div>
        </div>
      </main>
      <CellDrawer />
      <BottomPanel />
    </div>
  );
}
