// REST client. Every number the UI shows comes from here or from the WebSocket.
import type { CellDetail, Health, Report, Run, SimStatus, Snapshot, Timeseries } from "./contracts";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const WS_URL: string = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

async function post<T>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `${path}: HTTP ${r.status}`);
  }
  return (await r.json()) as T;
}

export const api = {
  state: () => get<Snapshot>("/api/state"),
  health: () => get<Health>("/api/health"),
  cell: (cell: string) => get<CellDetail>(`/api/cells/${cell}`),
  timeseries: (cell: string, buckets = 28) =>
    get<Timeseries>(`/api/cells/${cell}/timeseries?buckets=${buckets}`),
  run: (runId: string) => get<Run>(`/api/runs/${runId}`),
  report: (runId: string) => get<Report>(`/api/reports/${runId}`),
  surge: (injectionId: string) => post<SimStatus>("/api/sim/surge", { injection_id: injectionId }),
  simStart: () => post<SimStatus>("/api/sim/start"),
  simPause: () => post<SimStatus>("/api/sim/pause"),
  simReset: () => post<SimStatus>("/api/sim/reset"),
};
