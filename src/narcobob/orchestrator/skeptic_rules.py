"""The fallback Skeptic: the five mandatory checks as deterministic rules (SPEC §8.2).

Used by the fallback agent, by the backtest, and as the test oracle. The Bob Skeptic
runs the same five checks with judgment; this is the floor it must not fall below.
"""

from __future__ import annotations

from dataclasses import dataclass

RANK = ["NORMAL", "WATCH", "HIGH", "CRITICAL"]
STABILITY_MIN = 0.6
SINGLE_SOURCE_MAX = 0.8
RAID_GROWTH = 1.1  # ln(3): enforcement at least tripled…
OD_FLAT_GROWTH = 0.1  # …while overdoses barely moved


@dataclass(frozen=True)
class CellFacts:
    cell: str
    engine_severity: str
    support: int
    confidence: str
    stability: float
    gap_in_recent_window: bool  # a source that matters for this cell went silent recently
    od_growth: float  # ln((recent+1)/(prior+1)) for overdoses, raw counts
    enforcement_growth: float  # same for seizures + arrests
    top_source_share: float


@dataclass(frozen=True)
class SkepticVerdict:
    cell: str
    verdict: str
    final_severity: str
    checks: dict[str, str]
    rationale: str


def _down(severity: str, steps: int = 1) -> str:
    return RANK[max(0, RANK.index(severity) - steps)]


def judge(f: CellFacts) -> SkepticVerdict:
    checks = {
        "support": "fail" if f.confidence == "low" else "pass",
        "sensitivity": "fail" if f.stability < STABILITY_MIN else "pass",
        "data_quality": "fail" if f.gap_in_recent_window else "pass",
        "enforcement_artifact": (
            "fail"
            if f.enforcement_growth >= RAID_GROWTH and f.od_growth <= OD_FLAT_GROWTH
            else "pass"
        ),
        "single_source": "fail" if f.top_source_share > SINGLE_SOURCE_MAX else "pass",
    }
    failed = [name for name, result in checks.items() if result == "fail"]

    if checks["enforcement_artifact"] == "fail":
        verdict, final = "REJECTED", "NORMAL"
        why = "enforcement spike without overdose growth: a policing artefact, not harm"
    elif checks["data_quality"] == "fail":
        verdict, final = "REJECTED", "WATCH"
        why = "a reporting source went silent in the recent window, so the trend is unreliable"
    elif f.support < 3:
        verdict, final = "NEEDS_MORE_DATA", "WATCH"
        why = f"only {f.support} events in the recent window"
    elif failed:
        final = f.engine_severity
        if checks["support"] == "fail":
            final = min(final, "WATCH", key=RANK.index)
        if checks["sensitivity"] == "fail":
            final = _down(final)
        if checks["single_source"] == "fail":
            final = _down(final)
        verdict = "DOWNGRADED"
        why = "failed: " + ", ".join(failed)
    else:
        verdict, final = "CONFIRMED", f.engine_severity
        why = "all five checks passed"
    return SkepticVerdict(f.cell, verdict, final, checks, why[:400])
