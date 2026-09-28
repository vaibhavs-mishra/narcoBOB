import { useEffect } from "react";
import { AgentLanes } from "./components/AgentLanes";
import { AlertFeed } from "./components/AlertFeed";
import { CellDrawer } from "./components/CellDrawer";
import { EventTicker } from "./components/EventTicker";
import { MapPanel } from "./components/MapPanel";
import { AgentLog } from "./components/obs/AgentLog";
import { BobConsole } from "./components/obs/BobConsole";
import { RunList } from "./components/obs/RunList";
import { ReportViewer } from "./components/ReportViewer";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./layout/Workspace";
import { useStore } from "./store";
import { connect } from "./ws";

const COMMAND = { map: MapPanel, alerts: AlertFeed, cell: CellDrawer, agents: AgentLanes, brief: ReportViewer, ticker: EventTicker };
const OBSERVABILITY = { runs: RunList, log: AgentLog, console: BobConsole, lanes: AgentLanes };

export default function App() {
  useEffect(() => connect(), []);
  const view = useStore((s) => s.view);
  const helpMode = useStore((s) => s.helpMode);
  const setHelpMode = useStore((s) => s.setHelpMode);

  // "?" toggles help mode, Esc leaves it
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (e.key === "?" && !typing) setHelpMode(!useStore.getState().helpMode);
      else if (e.key === "Escape") setHelpMode(false);
    };
    // capture phase: focused Blueprint controls would otherwise swallow Esc
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [setHelpMode]);

  return (
    <div className={helpMode ? "shell help-on" : "shell"}>
      <TopBar />
      {helpMode && (
        <div className="help-banner">
          Help mode: hover a <span className="help-marker">?</span> marker to learn what it shows. Press Esc to exit.
        </div>
      )}
      {/* both views stay mounted so the map and layouts survive switching */}
      <Workspace view="command" panels={COMMAND} hidden={view !== "command"} />
      <Workspace view="observability" panels={OBSERVABILITY} hidden={view !== "observability"} />
    </div>
  );
}
