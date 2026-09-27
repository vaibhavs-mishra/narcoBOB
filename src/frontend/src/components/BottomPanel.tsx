import { Tab, Tabs } from "@blueprintjs/core";
import { useStore } from "../store";
import { AgentLanes } from "./AgentLanes";
import { EventTicker } from "./EventTicker";
import { ReportViewer } from "./ReportViewer";

export function BottomPanel() {
  const tab = useStore((s) => s.bottomTab);
  const setTab = useStore((s) => s.setBottomTab);
  return (
    <section className="panel bottom">
      <Tabs id="bottom" selectedTabId={tab} onChange={(t) => setTab(t as typeof tab)} renderActiveTabPanelOnly>
        <Tab id="agents" title="Agents" panel={<AgentLanes />} />
        <Tab id="report" title="Brief" panel={<ReportViewer />} />
        <Tab id="ticker" title="Event ticker" panel={<EventTicker />} />
      </Tabs>
    </section>
  );
}
