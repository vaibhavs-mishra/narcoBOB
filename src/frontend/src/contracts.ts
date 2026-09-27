// TypeScript mirror of the backend interface (Python twin: narcobob/common/schemas.py).
// Change both together.

export type Severity = "NORMAL" | "WATCH" | "HIGH" | "CRITICAL";
export type EventType = "overdose" | "seizure" | "arrest";
export type Confidence = "low" | "medium" | "high";
export type AgentId = "steward" | "analyst" | "skeptic" | "writer";
export type VerdictLabel = "CONFIRMED" | "DOWNGRADED" | "REJECTED" | "NEEDS_MORE_DATA";
export type RunStatus = "QUEUED" | "RUNNING" | "DONE" | "FAILED_WITH_FALLBACK";
export type StepStatus = "running" | "done" | "failed" | "fallback";
export type OutputSource = "bob" | "fallback";
export type Driver = "accel" | "div" | "spill" | "gi";
export type FindingKind = "data_quality" | "analysis" | "verdict";

export const AGENT_IDS: readonly AgentId[] = ["steward", "analyst", "skeptic", "writer"];

// ── REST ─────────────────────────────────────────────────────────────────────

export interface Component {
  z: number;
  contrib: number;
}

export interface CellScore {
  cell: string;
  score: number;
  severity: Severity;
  confidence: Confidence;
  support: number;
  components: Record<Driver, Component>;
  final_severity?: Severity | null;
  verdict?: VerdictLabel | null;
  sim_ts: string;
}

export interface Neighbor {
  cell: string;
  score: number;
  severity: Severity;
}

export interface Alert {
  alert_id: string;
  cell: string;
  severity: Severity;
  score: number;
  reason: string;
  run_id?: string | null;
  final_severity?: Severity | null;
  verdict?: VerdictLabel | null;
  sim_ts: string;
  wall_created_at: string;
}

export interface Verdict {
  cell: string;
  verdict: VerdictLabel;
  final_severity: Severity;
  checks: Partial<
    Record<
      "support" | "sensitivity" | "data_quality" | "enforcement_artifact" | "single_source",
      "pass" | "fail" | "n/a"
    >
  >;
  rationale: string;
}

export interface CellDetail extends CellScore {
  neighbors: Neighbor[];
  latest_verdict?: Verdict | null;
  alerts: Alert[];
}

export interface Timeseries {
  cell: string;
  buckets: number[];
  series: Partial<Record<EventType, number[]>>;
}

export interface Kpis {
  events_per_min: number;
  active_alerts: number;
  cells_monitored: number;
  cells_elevated: number;
  sim_now: string | null;
  data_version: number;
}

export interface Injection {
  id: string;
  kind: string;
  status: "pending" | "active" | "done";
}

export interface SimStatus {
  running: boolean;
  scenario: string;
  seed: number;
  sim_now: string | null;
  speed: number;
  injections: Injection[];
}

export interface PublicConfig {
  area_name: string;
  bbox: [number, number, number, number]; // lat_min, lon_min, lat_max, lon_max
  h3_res: number;
  bucket_sim_seconds: number;
  weights: Record<Driver, number>;
  thresholds: { watch: number; high: number; critical: number };
  agents_mode: "bob" | "fallback";
}

export interface StepSummary {
  agent_id: AgentId;
  status: StepStatus;
  source?: OutputSource | null;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  cells: string[];
  wall_started_at: string | null;
  wall_finished_at?: string | null;
  steps: StepSummary[];
}

export interface Snapshot {
  config: PublicConfig;
  sim: SimStatus;
  kpis: Kpis;
  cells: CellScore[];
  alerts: Alert[];
  runs: RunSummary[];
  seq: number;
}

export interface Health {
  ok: boolean;
  api: boolean;
  mcp: boolean;
  bob: "ok" | "unavailable" | "disabled";
  mode: "live" | "replay";
}

export interface Recommendation {
  track: "enforcement" | "treatment";
  cells: string[];
  action: string;
  priority: "immediate" | "this_week" | "monitor";
}

export interface Report {
  report_id: string;
  run_id: string;
  markdown: string;
  recommendations: Recommendation[];
  provenance_ratio?: number | null;
  source: OutputSource;
  wall_at: string;
}

export interface Finding {
  finding_id: string;
  run_id: string;
  step_id: string;
  agent_id: AgentId;
  kind: FindingKind;
  cell: string | null;
  payload: Record<string, unknown>;
  source: OutputSource;
  wall_at: string;
}

export interface Step {
  step_id: string;
  run_id: string;
  agent_id: AgentId;
  status: StepStatus;
  source?: OutputSource | null;
  attempt: number;
  tool_calls: number;
  wall_started_at: string;
  wall_finished_at?: string | null;
}

export interface Run {
  run_id: string;
  status: RunStatus;
  alert_ids: string[];
  cells: string[];
  data_version: number;
  wall_started_at: string | null;
  wall_finished_at?: string | null;
  steps: Step[];
  findings: Finding[];
  report?: Report | null;
}

// ── WebSocket ────────────────────────────────────────────────────────────────

export interface TickerEvent {
  type: EventType;
  cell: string;
  lat: number;
  lon: number;
  ts: string;
}

export interface AgentStepMsg {
  run_id: string;
  step_id: string;
  agent_id: AgentId;
  status: StepStatus;
  source?: OutputSource | null;
  attempt: number;
}

export interface ToolCallMsg {
  run_id: string;
  step_id: string;
  agent_id: AgentId;
  tool: string;
  ok: boolean;
  error_code?: string | null;
  duration_ms: number;
  wall_at: string;
}

export interface FindingPostedMsg {
  run_id: string;
  agent_id: AgentId;
  kind: FindingKind;
  cell?: string | null;
  summary: string;
}

/** Every WebSocket message, discriminated by `type`. */
export type WsMessage = { seq: number; wall_ts: string } & (
  | { type: "hello"; payload: { server_session: string; mode: "live" | "replay"; seq: number } }
  | { type: "event.batch"; payload: { events: TickerEvent[]; count: number } }
  | { type: "scores.update"; payload: { cells: CellScore[]; kpis: Kpis } }
  | { type: "alert.raised" | "alert.updated"; payload: Alert }
  | { type: "run.queued" | "run.started" | "run.finished"; payload: RunSummary }
  | { type: "agent.step"; payload: AgentStepMsg }
  | { type: "agent.tool_call"; payload: ToolCallMsg }
  | { type: "finding.posted"; payload: FindingPostedMsg }
  | { type: "report.ready"; payload: { run_id: string; report_id: string; provenance_ratio?: number | null } }
  | { type: "sim.status"; payload: SimStatus }
  | { type: "heartbeat"; payload: Record<string, never> }
);
