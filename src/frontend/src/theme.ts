// Design tokens for the dark command-centre theme (see index.css for the CSS mirror).
import type { Severity } from "./contracts";

export const tokens = {
  bg: "#0B0E13",
  panel: "#11151C",
  panelRaised: "#161B24",
  border: "#1F2630",
  text: "#D8DEE9",
  muted: "#7B8794",
  cyan: "#22D3EE",
  amber: "#F59E0B",
  red: "#EF4444",
  green: "#10B981",
  violet: "#A78BFA",
} as const;

export const severityColor: Record<Severity, string> = {
  NORMAL: "#3B4A5A",
  WATCH: "#EAB308",
  HIGH: "#F97316",
  CRITICAL: tokens.red,
};

export const verdictIntent = {
  CONFIRMED: "danger",
  DOWNGRADED: "warning",
  REJECTED: "success",
  NEEDS_MORE_DATA: "none",
} as const;

export const driverLabel = {
  accel: "Acceleration",
  div: "Harm vs enforcement",
  spill: "Spillover",
  gi: "Hotspot (Gi*)",
} as const;

export const agentLabel = {
  steward: "Data Steward",
  analyst: "Spatial Analyst",
  skeptic: "Skeptic",
  writer: "Intel Writer",
} as const;

// Score 0–100 → RGBA on a slate → amber → red ramp (used by the map).
export function scoreColor(score: number, alpha = 220): [number, number, number, number] {
  const stops: [number, [number, number, number]][] = [
    [0, [30, 41, 59]],
    [50, [51, 65, 85]],
    [65, [234, 179, 8]],
    [82, [249, 115, 22]],
    [90, [239, 68, 68]],
    [100, [255, 40, 80]],
  ];
  for (let i = 1; i < stops.length; i++) {
    const [s1, c1] = stops[i];
    const [s0, c0] = stops[i - 1];
    if (score <= s1) {
      const t = (score - s0) / (s1 - s0);
      return [0, 1, 2].map((k) => Math.round(c0[k] + t * (c1[k] - c0[k]))).concat(alpha) as [
        number,
        number,
        number,
        number,
      ];
    }
  }
  return [255, 40, 80, alpha];
}
