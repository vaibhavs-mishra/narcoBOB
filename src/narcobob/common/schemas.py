"""Pydantic models for every interface in the system.

These mirror the project contract exactly; the TypeScript twin lives in
`frontend/src/contracts.ts`. Change both together.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Severity = Literal["NORMAL", "WATCH", "HIGH", "CRITICAL"]
SEVERITY_ORDER: dict[str, int] = {"NORMAL": 0, "WATCH": 1, "HIGH": 2, "CRITICAL": 3}

EventType = Literal["overdose", "seizure", "arrest"]
EVENT_TYPES: tuple[EventType, ...] = ("overdose", "seizure", "arrest")
Substance = Literal["heroin", "opium", "synthetic", "pharma", "cannabis", "unknown"]
Confidence = Literal["low", "medium", "high"]
AgentId = Literal["steward", "analyst", "skeptic", "writer"]
AGENT_IDS: tuple[AgentId, ...] = ("steward", "analyst", "skeptic", "writer")
VerdictLabel = Literal["CONFIRMED", "DOWNGRADED", "REJECTED", "NEEDS_MORE_DATA"]
RunStatus = Literal["QUEUED", "RUNNING", "DONE", "FAILED_WITH_FALLBACK"]
StepStatus = Literal["running", "done", "failed", "fallback"]
OutputSource = Literal["bob", "fallback"]
FindingKind = Literal["data_quality", "analysis", "verdict"]
Driver = Literal["accel", "div", "spill", "gi"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── 1. Event ─────────────────────────────────────────────────────────────────


class Event(_Model):
    event_id: str = Field(min_length=1, max_length=64)
    type: EventType
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    ts: datetime
    source: str = Field(pattern=r"^[a-z]+:[a-z0-9_\-]+$")
    quantity_g: float | None = None
    substance: Substance | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("meta")
    @classmethod
    def _meta_small(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(str(value)) > 1024:
            raise ValueError("meta must be at most 1 KB")
        return value


# ── 3. REST ──────────────────────────────────────────────────────────────────


class IngestRequest(_Model):
    events: list[Event] = Field(max_length=5000)


class Rejection(_Model):
    event_id: str
    reason: str


class IngestResult(_Model):
    accepted: int
    duplicates: int
    rejected: list[Rejection]
    data_version: int


class Component(_Model):
    z: float
    contrib: float


class Components(_Model):
    accel: Component
    div: Component
    spill: Component
    gi: Component


class CellScore(_Model):
    cell: str
    score: int
    severity: Severity
    confidence: Confidence
    support: int
    components: Components
    final_severity: Severity | None = None
    verdict: VerdictLabel | None = None
    sim_ts: str


class Neighbor(_Model):
    cell: str
    score: int
    severity: Severity


class Alert(_Model):
    alert_id: str
    cell: str
    severity: Severity
    score: int
    reason: str
    run_id: str | None = None
    final_severity: Severity | None = None
    verdict: VerdictLabel | None = None
    sim_ts: str
    wall_created_at: str


class CellDetail(CellScore):
    neighbors: list[Neighbor]
    latest_verdict: Verdict | None = None
    alerts: list[Alert]


class Timeseries(_Model):
    cell: str
    buckets: list[int]
    series: dict[str, list[int]]


class Kpis(_Model):
    events_per_min: float
    active_alerts: int
    cells_monitored: int
    cells_elevated: int
    sim_now: str | None
    data_version: int


class Injection(_Model):
    id: str
    kind: str
    status: Literal["pending", "active", "done"]


class SimStatus(_Model):
    running: bool
    scenario: str
    seed: int
    sim_now: str | None
    speed: float
    injections: list[Injection]


class PublicConfig(_Model):
    area_name: str
    bbox: tuple[float, float, float, float]
    h3_res: int
    bucket_sim_seconds: int
    weights: dict[Driver, float]
    thresholds: dict[Literal["watch", "high", "critical"], int]
    agents_mode: Literal["bob", "fallback"]


class StepSummary(_Model):
    agent_id: AgentId
    status: StepStatus
    source: OutputSource | None = None


class RunSummary(_Model):
    run_id: str
    status: RunStatus
    cells: list[str]
    wall_started_at: str | None
    wall_finished_at: str | None = None
    steps: list[StepSummary]


class Snapshot(_Model):
    config: PublicConfig
    sim: SimStatus
    kpis: Kpis
    cells: list[CellScore]
    alerts: list[Alert]
    runs: list[RunSummary]
    seq: int


class Health(_Model):
    ok: bool
    api: bool = True
    mcp: bool
    bob: Literal["ok", "unavailable", "disabled"]
    mode: Literal["live", "replay"]


class SurgeRequest(_Model):
    """Either a scenario injection id, or an ad-hoc surge."""

    injection_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    radius_cells: int = 1
    multiplier: float = 3.0
    ramp_days: int = 5
    types: list[EventType] = Field(default_factory=lambda: ["overdose"])

    @model_validator(mode="after")
    def _one_form(self) -> SurgeRequest:
        if self.injection_id is None and (self.lat is None or self.lon is None):
            raise ValueError("give injection_id, or lat and lon")
        return self


class SimControl(_Model):
    scenario: str | None = None
    seed: int | None = None


# ── 4. WebSocket ─────────────────────────────────────────────────────────────


class WsEnvelope(_Model):
    type: str
    seq: int
    wall_ts: str
    payload: dict[str, Any]


# ── 5. MCP tool envelope and agent payloads ──────────────────────────────────

ErrorCode = Literal[
    "VALIDATION_ERROR",
    "STEP_NOT_ACTIVE",
    "FORBIDDEN_TOOL",
    "NOT_FOUND",
    "BUDGET_EXCEEDED",
    "TIMEOUT",
    "CONFLICT",
    "INTERNAL",
]


class ToolError(_Model):
    code: ErrorCode
    message: str
    retryable: bool


class ToolMeta(_Model):
    run_id: str
    agent_id: str
    step_id: str
    trace_id: str
    tool: str
    tool_version: str
    duration_ms: int
    truncated: bool = False


class ToolEnvelope(_Model):
    ok: bool
    data: dict[str, Any] | None
    error: ToolError | None
    meta: ToolMeta


class DataQualityFinding(_Model):
    cell: str | None
    issue: Literal["source_gap", "duplicates", "late_events", "single_source", "ok"]
    detail: str = Field(max_length=300)
    affects_recent_window: bool


class AnalysisFinding(_Model):
    cell: str
    cluster_id: str
    drivers: list[Driver]
    narrative: str = Field(max_length=500)
    claimed_severity: Severity


CheckName = Literal[
    "support", "sensitivity", "data_quality", "enforcement_artifact", "single_source"
]


class Verdict(_Model):
    cell: str
    verdict: VerdictLabel
    final_severity: Severity
    checks: dict[CheckName, Literal["pass", "fail", "n/a"]]
    rationale: str = Field(max_length=400)


FINDING_MODELS: dict[str, type[BaseModel]] = {
    "data_quality": DataQualityFinding,
    "analysis": AnalysisFinding,
    "verdict": Verdict,
}
# Which finding kind each agent may submit.
AGENT_FINDING_KIND: dict[str, FindingKind] = {
    "steward": "data_quality",
    "analyst": "analysis",
    "skeptic": "verdict",
}


class FindingIn(_Model):
    kind: FindingKind
    payload: dict[str, Any]

    def parsed(self) -> BaseModel:
        """Validate the payload against the model for its kind."""
        return FINDING_MODELS[self.kind].model_validate(self.payload)


class Finding(_Model):
    finding_id: str
    run_id: str
    step_id: str
    agent_id: AgentId
    kind: FindingKind
    cell: str | None
    payload: dict[str, Any]
    source: OutputSource
    wall_at: str


class Recommendation(_Model):
    track: Literal["enforcement", "treatment"]
    cells: list[str]
    action: str = Field(max_length=200)
    priority: Literal["immediate", "this_week", "monitor"]


class ReportIn(_Model):
    markdown: str = Field(min_length=1)
    recommendations: list[Recommendation]

    @model_validator(mode="after")
    def _both_tracks(self) -> ReportIn:
        tracks = {r.track for r in self.recommendations}
        if tracks != {"enforcement", "treatment"}:
            raise ValueError(
                "report needs at least one enforcement AND one treatment recommendation"
            )
        return self


class Report(_Model):
    report_id: str
    run_id: str
    markdown: str
    recommendations: list[Recommendation]
    provenance_ratio: float | None = None
    source: OutputSource
    wall_at: str


class Step(_Model):
    step_id: str
    run_id: str
    agent_id: AgentId
    status: StepStatus
    source: OutputSource | None = None
    attempt: int
    tool_calls: int
    wall_started_at: str
    wall_finished_at: str | None = None


class Run(_Model):
    run_id: str
    status: RunStatus
    alert_ids: list[str]
    cells: list[str]
    data_version: int
    wall_started_at: str | None
    wall_finished_at: str | None = None
    steps: list[Step]
    findings: list[Finding]
    report: Report | None = None


CellDetail.model_rebuild()
