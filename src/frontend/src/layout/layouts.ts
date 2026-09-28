// Dockable workspaces: the panel registry, default layouts, persistence and "reveal".
import type { DockviewApi, SerializedDockview } from "dockview-react";
import { useStore, type View } from "../store";

export type PanelId =
  | "map" | "alerts" | "cell" | "agents" | "brief" | "ticker"
  | "runs" | "log" | "console" | "lanes"; // prettier-ignore

export interface PanelDef {
  id: PanelId;
  title: string;
  view: View;
  canPopout: boolean; // the map stays in the main window: WebGL in a second window is fragile
}

export const PANELS: PanelDef[] = [
  { id: "map", title: "Map", view: "command", canPopout: false },
  { id: "alerts", title: "Alerts", view: "command", canPopout: true },
  { id: "cell", title: "Cell detail", view: "command", canPopout: true },
  { id: "agents", title: "Agents", view: "command", canPopout: true },
  { id: "brief", title: "Brief", view: "command", canPopout: true },
  { id: "ticker", title: "Event ticker", view: "command", canPopout: true },
  { id: "runs", title: "Runs", view: "observability", canPopout: true },
  { id: "log", title: "Agent log", view: "observability", canPopout: true },
  { id: "console", title: "Bob console", view: "observability", canPopout: true },
  { id: "lanes", title: "Narclings", view: "observability", canPopout: true },
];

export const panelDef = (id: string): PanelDef | undefined => PANELS.find((p) => p.id === id);
export const POPOUT_URL = "/popout.html";

const docks: Partial<Record<View, DockviewApi>> = {};
const storageKey = (view: View) => `narcobob.layout.v1.${view}`;

function add(api: DockviewApi, id: PanelId, extra: Record<string, unknown> = {}): void {
  api.addPanel({ id, component: id, title: panelDef(id)?.title ?? id, ...extra });
}

function defaultLayout(view: View, api: DockviewApi): void {
  api.clear();
  if (view === "observability") {
    add(api, "log");
    add(api, "runs", { position: { referencePanel: "log", direction: "left" }, initialWidth: 300 });
    add(api, "console", { position: { referencePanel: "log", direction: "right" }, initialWidth: 520 });
    add(api, "lanes", { position: { referencePanel: "console", direction: "below" }, initialHeight: 260 });
    api.getPanel("log")?.api.setActive();
    return;
  }
  const narrow = window.innerWidth < 900;
  add(api, "map");
  if (narrow) {
    // small screens: the map on top, everything else as tabs underneath
    add(api, "alerts", { position: { direction: "below" }, initialHeight: Math.round(window.innerHeight * 0.45) });
    for (const id of ["cell", "agents", "brief", "ticker"] as const) {
      add(api, id, { position: { referencePanel: "alerts", direction: "within" }, inactive: true });
    }
    return;
  }
  // the bottom strip spans the full width; alerts and cell detail flank the map above it
  add(api, "agents", { position: { direction: "below" }, initialHeight: Math.round(Math.min(340, Math.max(220, window.innerHeight * 0.28))) });
  add(api, "brief", { position: { referencePanel: "agents", direction: "within" }, inactive: true });
  add(api, "ticker", { position: { referencePanel: "agents", direction: "within" }, inactive: true });
  add(api, "alerts", { position: { referencePanel: "map", direction: "left" }, initialWidth: 320 });
  add(api, "cell", { position: { referencePanel: "map", direction: "right" }, initialWidth: 400 });
}

function save(view: View, api: DockviewApi): void {
  try {
    const json: SerializedDockview = api.toJSON();
    delete json.popoutGroups; // pop-up windows are not reopened on reload
    localStorage.setItem(storageKey(view), JSON.stringify(json));
  } catch {
    /* storage unavailable: the layout simply is not remembered */
  }
}

function restore(view: View, api: DockviewApi): boolean {
  try {
    const raw = localStorage.getItem(storageKey(view));
    if (!raw) return false;
    api.fromJSON(JSON.parse(raw) as SerializedDockview);
    return api.panels.length > 0;
  } catch {
    return false;
  }
}

/** Called once per workspace from DockviewReact's onReady. */
export function initDock(view: View, api: DockviewApi): void {
  docks[view] = api;
  if (!restore(view, api)) defaultLayout(view, api);
  let timer = 0;
  api.onDidLayoutChange(() => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => save(view, api), 400);
  });
}

export function resetLayout(view: View): void {
  const api = docks[view];
  if (!api) return;
  defaultLayout(view, api);
  save(view, api);
}

export function isPanelOpen(id: PanelId): boolean {
  const def = panelDef(id);
  return def ? docks[def.view]?.getPanel(id) !== undefined : false;
}

/** Show a panel: switch to its view, reopen it if it was closed, and bring its tab to the front. */
export function revealPanel(id: PanelId): void {
  const def = panelDef(id);
  const api = def && docks[def.view];
  if (!def || !api) return;
  if (useStore.getState().view !== def.view) useStore.getState().setView(def.view);
  const panel = api.getPanel(id);
  if (panel) panel.api.setActive();
  else add(api, id);
}

// Selecting a cell (map, alert, neighbour) brings the cell detail to the front.
useStore.subscribe((s, prev) => {
  if (s.selectedCell && s.selectedCell !== prev.selectedCell && s.view === "command") revealPanel("cell");
});
