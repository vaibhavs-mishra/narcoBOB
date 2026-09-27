"""Alert transitions, data-quality checks, fallback Skeptic rules and generator determinism."""

from __future__ import annotations

import numpy as np
import pytest

from narcobob.common.config import SRC_DIR
from narcobob.engine.alerting import alert_reason, bypasses_cooldown
from narcobob.engine.cells import CellGrid
from narcobob.engine.quality import source_gaps, top_source_share
from narcobob.orchestrator.skeptic_rules import CellFacts, judge
from narcobob.simulator.generator import Generator
from narcobob.simulator.scenario import load_scenario


@pytest.mark.parametrize(
    ("prev", "cur", "reason"),
    [
        ("WATCH", "HIGH", "entered HIGH"),
        ("NORMAL", "CRITICAL", "entered CRITICAL"),
        ("HIGH", "CRITICAL", "escalated to CRITICAL"),
        ("HIGH", "HIGH", None),
        ("CRITICAL", "HIGH", None),
        ("NORMAL", "WATCH", None),
    ],
)
def test_alert_transitions(prev: str, cur: str, reason: str | None) -> None:
    assert alert_reason(prev, cur) == reason


def test_escalation_bypasses_cooldown() -> None:
    assert bypasses_cooldown("escalated to CRITICAL")
    assert not bypasses_cooldown("entered HIGH")


def test_source_gap_detected_only_for_regular_sources() -> None:
    per_source = np.array([[3, 3, 3, 0, 0, 0, 3, 3], [0, 0, 1, 0, 0, 0, 0, 0]], dtype=float)
    gaps = source_gaps(per_source)
    assert [(g.source, g.from_bucket, g.to_bucket) for g in gaps] == [(0, 3, 5)]


def test_top_source_share() -> None:
    top, share = top_source_share(np.array([[8.0, 2.0], [0.0, 0.0]]))
    assert top[0] == 0 and share[0] == pytest.approx(0.8) and share[1] == 0.0


def facts(**kw: object) -> CellFacts:
    base: dict[str, object] = dict(
        cell="c", engine_severity="CRITICAL", support=40, confidence="high", stability=0.9,
        gap_in_recent_window=False, od_growth=1.0, enforcement_growth=0.0, top_source_share=0.5,
    )  # fmt: skip
    base.update(kw)
    return CellFacts(**base)  # type: ignore[arg-type]


def test_skeptic_confirms_clean_signal() -> None:
    v = judge(facts())
    assert v.verdict == "CONFIRMED" and v.final_severity == "CRITICAL"
    assert set(v.checks.values()) == {"pass"}


def test_skeptic_downgrades_low_support() -> None:
    v = judge(facts(support=5, confidence="low"))
    assert v.verdict == "DOWNGRADED" and v.final_severity == "WATCH"


def test_skeptic_rejects_raid_artefact() -> None:
    v = judge(facts(od_growth=0.0, enforcement_growth=2.0))
    assert v.verdict == "REJECTED" and v.checks["enforcement_artifact"] == "fail"


def test_skeptic_rejects_on_feed_gap_and_flags_thin_data() -> None:
    assert judge(facts(gap_in_recent_window=True)).verdict == "REJECTED"
    assert judge(facts(support=2, confidence="low")).verdict == "NEEDS_MORE_DATA"


def test_skeptic_downgrades_unstable_and_single_source() -> None:
    v = judge(facts(stability=0.3, top_source_share=0.95))
    assert v.verdict == "DOWNGRADED" and v.final_severity == "WATCH"  # two steps down


def test_generator_is_deterministic_and_decoy_is_exact() -> None:
    sc = load_scenario(SRC_DIR / "scenarios" / "demo_border_surge.yaml")
    sc.auto_injections = True
    grid = CellGrid.from_bbox(sc.area.bbox, sc.area.h3_res)
    gen = Generator(sc, grid, 42)
    assert gen.events_for_day(10) == Generator(sc, grid, 42).events_for_day(10)
    d1 = next(a for a in gen.injections if a.spec.id == "D1")
    extra = sum(int(gen.extra_counts(d)[d1.cells, 0].sum()) for d in range(60, 70))
    assert extra == 5
