// A dockable workspace: resizable, draggable panels whose groups can float or pop out.
import { Button, PortalProvider, Tooltip } from "@blueprintjs/core";
import {
  DockviewReact,
  themeDark,
  type IDockviewHeaderActionsProps,
  type IDockviewPanelProps,
} from "dockview-react";
import { useEffect, useMemo, useRef, useState, type FunctionComponent } from "react";
import { HelpTip } from "../components/HelpTip";
import type { HelpId } from "../help";
import type { View } from "../store";
import { initDock, panelDef, POPOUT_URL, type PanelId } from "./layouts";

const THEME = { ...themeDark, gap: 6 };

/** Wraps a panel so Blueprint overlays render in whichever window the panel lives in. */
function PanelFrame({ id, props, Body }: { id: PanelId; props: IDockviewPanelProps; Body: FunctionComponent }) {
  const ref = useRef<HTMLDivElement>(null);
  const [container, setContainer] = useState<HTMLElement | undefined>(undefined);
  useEffect(() => {
    const sync = () => setContainer(ref.current?.ownerDocument.body);
    sync();
    // the panel's DOM moves to another document when its group pops out
    const d = props.api.onDidLocationChange(() => window.setTimeout(sync, 50));
    return () => d.dispose();
  }, [props.api]);
  return (
    <PortalProvider portalContainer={container}>
      <div ref={ref} className={`dock-panel dock-panel-${id}`}>
        <HelpTip id={id as HelpId} corner />
        <Body />
      </div>
    </PortalProvider>
  );
}

function GroupActions({ containerApi, group, api, panels }: IDockviewHeaderActionsProps) {
  const [, rerender] = useState(0);
  useEffect(() => {
    const subs = [
      api.onDidLocationChange(() => rerender((n) => n + 1)),
      containerApi.onDidMaximizedGroupChange(() => rerender((n) => n + 1)),
    ];
    return () => subs.forEach((s) => s.dispose());
  }, [api, containerApi]);

  const where = api.location.type;
  const canPopout = panels.every((p) => panelDef(p.id)?.canPopout ?? true);
  const maximized = api.isMaximized();
  return (
    <div className="group-actions">
      {where === "grid" && (
        <Tooltip content="Float over the page" placement="bottom" compact>
          <Button minimal small icon="applications" aria-label="Float" onClick={() => containerApi.addFloatingGroup(group)} />
        </Tooltip>
      )}
      {where === "floating" && (
        <Tooltip content="Dock back into the layout" placement="bottom" compact>
          <Button minimal small icon="pin" aria-label="Dock" onClick={() => api.moveTo({ position: "right" })} />
        </Tooltip>
      )}
      {where !== "popout" && canPopout && (
        <Tooltip content="Open in a new window" placement="bottom" compact>
          <Button minimal small icon="share" aria-label="Pop out"
            onClick={() => void containerApi.addPopoutGroup(group, { popoutUrl: POPOUT_URL })} />
        </Tooltip>
      )}
      {where === "grid" && (
        <Tooltip content={maximized ? "Restore" : "Maximise"} placement="bottom" compact>
          <Button minimal small icon={maximized ? "minimize" : "maximize"} aria-label={maximized ? "Restore" : "Maximise"}
            onClick={() => (maximized ? api.exitMaximized() : api.maximize())} />
        </Tooltip>
      )}
    </div>
  );
}

export function Workspace({ view, panels, hidden }: { view: View; panels: Partial<Record<PanelId, FunctionComponent>>; hidden: boolean }) {
  const components = useMemo(() => {
    const out: Record<string, FunctionComponent<IDockviewPanelProps>> = {};
    for (const [id, Body] of Object.entries(panels)) {
      out[id] = (props: IDockviewPanelProps) => <PanelFrame id={id as PanelId} props={props} Body={Body} />;
    }
    return out;
  }, [panels]);
  // mount on first show, so the default layout is built at the real size
  const [shown, setShown] = useState(!hidden);
  if (!hidden && !shown) setShown(true);
  if (!shown) return null;
  return (
    <div className="workspace" style={hidden ? { display: "none" } : undefined}>
      <DockviewReact
        theme={THEME}
        components={components}
        rightHeaderActionsComponent={GroupActions}
        popoutUrl={POPOUT_URL}
        onReady={(e) => initDock(view, e.api)}
      />
    </div>
  );
}
