import { useEffect } from "react";
import { AlertFeed } from "./components/AlertFeed";
import { BottomPanel } from "./components/BottomPanel";
import { CellDrawer } from "./components/CellDrawer";
import { MapView } from "./components/MapView";
import { TopBar } from "./components/TopBar";
import { connect } from "./ws";

export default function App() {
  useEffect(() => connect(), []);
  return (
    <div className="shell">
      <TopBar />
      <AlertFeed />
      <main className="map">
        <MapView />
      </main>
      <CellDrawer />
      <BottomPanel />
    </div>
  );
}
