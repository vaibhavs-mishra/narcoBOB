"""Engine-level severity and confidence (SPEC §6.6–6.7). This is *pre-Skeptic*."""

from __future__ import annotations

GI_CRITICAL = 1.96  # 95% two-sided significance for the Gi* z-score


def confidence_of(support: int) -> str:
    """Confidence from raw event count in the recent window."""
    if support < 8:
        return "low"
    if support < 20:
        return "medium"
    return "high"


def severity_of(score: int, gi: float, confidence: str, thresholds: tuple[int, int, int]) -> str:
    """CRITICAL also needs a significant hotspot and more than a handful of events."""
    watch, high, critical = thresholds
    if score >= critical and gi >= GI_CRITICAL and confidence != "low":
        return "CRITICAL"
    if score >= high:
        return "HIGH"
    if score >= watch:
        return "WATCH"
    return "NORMAL"
