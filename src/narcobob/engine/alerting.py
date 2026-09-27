"""When does a severity change deserve an alert? (SPEC §7)

An alert fires when a cell *enters* HIGH or CRITICAL, or escalates between them.
Cooldowns and coalescing are wall-clock concerns and live in the API, not here.
"""

from __future__ import annotations

RANK = {"NORMAL": 0, "WATCH": 1, "HIGH": 2, "CRITICAL": 3}
ALERTING = ("HIGH", "CRITICAL")


def bypasses_cooldown(reason: str) -> bool:
    """Escalations are never muted: the cooldown only stops repeat HIGH alerts."""
    return reason.startswith("escalated")


def alert_reason(previous: str, current: str) -> str | None:
    """The alert reason for a transition, or None if it is not alert-worthy."""
    if current not in ALERTING or RANK[current] <= RANK[previous]:
        return None
    if previous in ALERTING:
        return f"escalated to {current}"
    return f"entered {current}"
