import { Button, ButtonGroup, Menu, MenuDivider, MenuItem, PopoverNext, Tag, Tooltip } from "@blueprintjs/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import { isPanelOpen, PANELS, resetLayout, revealPanel } from "../layout/layouts";
import { useStore } from "../store";
import { HelpTip } from "./HelpTip";
import { SurgeButton } from "./SurgeButton";

function Light({ label, state }: { label: string; state: "ok" | "off" | "bad" }) {
  return (
    <span className={`light light-${state}`}>
      <i />
      {label}
    </span>
  );
}

function Kpi({ label, value, secondary = false }: { label: string; value: string; secondary?: boolean }) {
  return (
    <div className={secondary ? "kpi kpi-secondary" : "kpi"}>
      <span className="kpi-value mono">{value}</span>
      <span className="kpi-label">{label}</span>
    </div>
  );
}

/** Reopen any panel of the current view, or restore its default arrangement. */
function LayoutMenu() {
  const view = useStore((s) => s.view);
  const [, refresh] = useState(0);
  return (
    <PopoverNext
      placement="bottom-end"
      onOpening={() => refresh((n) => n + 1)}
      content={
        <Menu>
          <MenuDivider title="Panels" />
          {PANELS.filter((p) => p.view === view).map((p) => (
            <MenuItem key={p.id} text={p.title} icon={isPanelOpen(p.id) ? "tick" : "blank"} onClick={() => revealPanel(p.id)} />
          ))}
          <MenuDivider />
          <MenuItem icon="reset" text="Reset layout" onClick={() => resetLayout(view)} />
        </Menu>
      }
    >
      <Button minimal className="layout-btn" icon="page-layout" text="Layout" />
    </PopoverNext>
  );
}

function simClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 16);
}

export function TopBar() {
  const config = useStore((s) => s.config);
  const kpis = useStore((s) => s.kpis);
  const sim = useStore((s) => s.sim);
  const health = useStore((s) => s.health);
  const connected = useStore((s) => s.connected);
  const mode = useStore((s) => s.mode);
  const setHealth = useStore((s) => s.setHealth);
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const helpMode = useStore((s) => s.helpMode);
  const setHelpMode = useStore((s) => s.setHelpMode);

  useEffect(() => {
    const poll = () => api.health().then(setHealth).catch(() => setHealth(null));
    poll();
    const id = window.setInterval(poll, 5000);
    return () => window.clearInterval(id);
  }, [setHealth]);

  const bob = health?.bob === "ok" ? "ok" : health?.bob === "disabled" ? "off" : "bad";
  return (
    <header className="topbar">
      <div className="brand">
        <span className="wordmark">
          NARCO<b>BOB</b>
        </span>
        <span className="area">{config?.area_name ?? "…"}</span>
        <HelpTip id="simBadge">
          <Tooltip content="Events are synthetic, calibrated to public aggregates. The pipeline is real; the feed is not.">
            <Tag intent="warning" minimal className="sim-badge">
              SIMULATED FEED
            </Tag>
          </Tooltip>
        </HelpTip>
      </div>
      <HelpTip id="viewSwitch">
        <ButtonGroup className="view-switch">
          <Button small active={view === "command"} icon="map" text="Command" onClick={() => setView("command")} />
          <Button small active={view === "observability"} icon="console" text="Observability" onClick={() => setView("observability")} />
        </ButtonGroup>
      </HelpTip>
      <HelpTip id="kpis">
      <div className="kpis">
        <Kpi secondary label="events / min" value={kpis ? Math.round(kpis.events_per_min).toLocaleString() : "—"} />
        <Kpi label="active alerts" value={kpis ? String(kpis.active_alerts) : "—"} />
        <Kpi secondary label="cells elevated" value={kpis ? `${kpis.cells_elevated} / ${kpis.cells_monitored}` : "—"} />
        <Kpi label="sim clock (UTC)" value={simClock(kpis?.sim_now ?? sim?.sim_now)} />
      </div>
      </HelpTip>
      <div className="status">
        <HelpTip id="status">
        <span className="lights">
        <Light label="API" state={connected ? "ok" : "bad"} />
        <Light label="MCP" state={health?.mcp ? "ok" : health ? "bad" : "off"} />
        <Tooltip content={health?.bob === "disabled" ? "Fallback agents (Bob disabled)" : "IBM Bob Shell agents"}>
          <Light label={health?.bob === "disabled" ? "BOB off" : "BOB"} state={bob} />
        </Tooltip>
        </span>
        </HelpTip>
        <HelpTip id="mode">
          <Tag intent={mode === "replay" ? "primary" : "success"} className="mode-tag">
            {mode === "replay" ? "REPLAY" : "LIVE"}
          </Tag>
        </HelpTip>
        {mode === "live" && <HelpTip id="surge"><SurgeButton /></HelpTip>}
        {mode === "live" && (
          <PopoverNext
            placement="bottom-end"
            content={
              <Menu>
                <MenuItem icon={sim?.running ? "pause" : "play"} text={sim?.running ? "Pause feed" : "Resume feed"}
                  onClick={() => void (sim?.running ? api.simPause() : api.simStart())} />
                <MenuItem icon="reset" text="Reset scenario (clears all data)" intent="danger"
                  onClick={() => void api.simReset().then(() => window.location.reload())} />
              </Menu>
            }
          >
            <Button minimal icon="more" aria-label="Simulation controls" />
          </PopoverNext>
        )}
        <span className="topbar-divider" />
        <HelpTip id="layout"><LayoutMenu /></HelpTip>
        <Tooltip content={helpMode ? "Hide help (Esc)" : "Explain this screen (?)"} placement="bottom-end">
          <Button className="help-btn" minimal={!helpMode} intent={helpMode ? "primary" : "none"} icon="help"
            aria-label="Help" aria-pressed={helpMode} onClick={() => setHelpMode(!helpMode)} />
        </Tooltip>
      </div>
    </header>
  );
}
