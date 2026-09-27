import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { ScatterplotLayer } from "@deck.gl/layers";
import DeckGL from "@deck.gl/react";
import type { MapViewState, PickingInfo } from "@deck.gl/core";
import { useEffect, useMemo, useState } from "react";
import { Map } from "react-map-gl/maplibre";
import { cellToLatLng } from "h3-js";
import type { CellScore, Driver } from "../contracts";
import { useStore, type Ping } from "../store";
import { driverLabel, scoreColor } from "../theme";

const BASEMAP = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const PING_COLORS: Record<string, [number, number, number]> = {
  overdose: [239, 68, 68],
  seizure: [34, 211, 238],
  arrest: [167, 139, 250],
};

function topDriver(c: CellScore): Driver {
  return (Object.keys(c.components) as Driver[]).reduce((a, b) =>
    c.components[a].contrib >= c.components[b].contrib ? a : b,
  );
}

export function MapView() {
  const config = useStore((s) => s.config);
  const cells = useStore((s) => s.cells);
  const pings = useStore((s) => s.pings);
  const selected = useStore((s) => s.selectedCell);
  const alerts = useStore((s) => s.alerts);
  const select = useStore((s) => s.select);
  const [view, setView] = useState<MapViewState | null>(null);
  const [now, setNow] = useState(() => performance.now());

  // centre the view on the configured area once the config arrives
  useEffect(() => {
    if (!config || view) return;
    const [latMin, lonMin, latMax, lonMax] = config.bbox;
    setView({ latitude: (latMin + latMax) / 2 - 0.08, longitude: (lonMin + lonMax) / 2, zoom: 9.3, pitch: 45, bearing: -8 });
  }, [config, view]);

  // fly to the selected cell
  useEffect(() => {
    if (!selected) return;
    const [lat, lon] = cellToLatLng(selected);
    setView((v) => (v ? { ...v, latitude: lat - 0.03, longitude: lon, zoom: Math.max(v.zoom, 10.2), transitionDuration: 800 } : v));
  }, [selected]);

  // fade event pings
  useEffect(() => {
    const id = window.setInterval(() => setNow(performance.now()), 100);
    return () => window.clearInterval(id);
  }, []);

  const data = useMemo(() => Object.values(cells).filter((c) => c.score >= 30 || c.severity !== "NORMAL"), [cells]);
  const livePings = useMemo(() => pings.filter((p) => now - p.at < 2500), [pings, now]);
  // Hotspots the Skeptic confirmed at HIGH or above stay outlined after the map moves on.
  const confirmed = useMemo(
    () => [
      ...new Set(
        alerts
          .filter((a) => a.verdict === "CONFIRMED" && (a.final_severity === "HIGH" || a.final_severity === "CRITICAL"))
          .map((a) => a.cell),
      ),
    ],
    [alerts],
  );

  const layers = [
    new H3HexagonLayer<CellScore>({
      id: "scores",
      data,
      getHexagon: (d) => d.cell,
      extruded: true,
      elevationScale: 1,
      getElevation: (d) => Math.max(0, d.score - 25) * 55,
      getFillColor: (d) => scoreColor(d.score, d.score >= 65 ? 235 : 150),
      getLineColor: [11, 14, 19, 255],
      lineWidthMinPixels: 1,
      material: { ambient: 0.55, diffuse: 0.6, shininess: 24 },
      pickable: true,
      autoHighlight: true,
      highlightColor: [34, 211, 238, 120],
      transitions: { getElevation: 600, getFillColor: 600 },
      onClick: (info: PickingInfo<CellScore>) => info.object && select(info.object.cell),
    }),
    new H3HexagonLayer<string>({
      id: "confirmed",
      data: confirmed,
      getHexagon: (d) => d,
      extruded: false,
      filled: true,
      stroked: true,
      getFillColor: [239, 68, 68, 40],
      getLineColor: [239, 68, 68, 255],
      lineWidthMinPixels: 2,
    }),
    new H3HexagonLayer<string>({
      id: "selected",
      data: selected ? [selected] : [],
      getHexagon: (d) => d,
      extruded: false,
      filled: false,
      stroked: true,
      getLineColor: [34, 211, 238, 255],
      lineWidthMinPixels: 3,
    }),
    new ScatterplotLayer<Ping>({
      id: "pings",
      data: livePings,
      getPosition: (p) => [p.lon, p.lat],
      getRadius: (p) => 250 + ((now - p.at) / 2500) * 900,
      getFillColor: (p) => [...(PING_COLORS[p.type] ?? [200, 200, 200]), Math.max(0, 200 * (1 - (now - p.at) / 2500))] as [number, number, number, number],
      radiusUnits: "meters",
      updateTriggers: { getRadius: now, getFillColor: now },
    }),
  ];

  if (!view) return <div className="map-empty">Waiting for the area configuration…</div>;

  return (
    <DeckGL
      viewState={view}
      onViewStateChange={({ viewState }) => setView(viewState as MapViewState)}
      controller
      layers={layers}
      getTooltip={({ object }: PickingInfo<CellScore>) =>
        object
          ? {
              html: `<div class="tt"><b>${object.severity}</b> · score ${object.score}<br/>top driver: ${driverLabel[topDriver(object)]}<br/>support ${object.support} (${object.confidence})${object.verdict ? `<br/>Skeptic: ${object.verdict} → ${object.final_severity}` : ""}</div>`,
              style: { background: "transparent", padding: "0" },
            }
          : null
      }
    >
      <Map mapStyle={BASEMAP} attributionControl={{ compact: true }} />
    </DeckGL>
  );
}
