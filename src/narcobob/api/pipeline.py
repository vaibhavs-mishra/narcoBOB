"""The live fast path as plain functions, shared by the server loop and the golden e2e test.

score → broadcast changed cells → raise alerts → (after coalescing) queue an agent run.
"""

from __future__ import annotations

from narcobob.api import queries
from narcobob.api.alerts import AlertEngine, create_run
from narcobob.api.scoring import cell_score_dicts, persist_scores, score_now
from narcobob.api.state import AppState
from narcobob.api.ws import Hub
from narcobob.common.db import data_version

VISIBLE_SCORE = 30  # the map draws cells from this score up


async def score_once(state: AppState, hub: Hub, engine: AlertEngine) -> None:
    scored = score_now(state)
    if scored is None:
        return
    result, bucket = scored
    fresh = cell_score_dicts(state, result, bucket)
    changed = [
        s
        for cell, s in fresh.items()
        if (old := state.scores.get(cell)) is None
        or abs(int(str(old["score"])) - int(str(s["score"]))) >= 1
        or old["severity"] != s["severity"]
    ]
    # Persist every change, but only broadcast cells the map can show (or just left it):
    # this keeps WebSocket traffic and recordings small.
    visible = [
        s
        for s in changed
        if int(str(s["score"])) >= VISIBLE_SCORE
        or int(str((state.scores.get(str(s["cell"])) or {"score": 0})["score"])) >= VISIBLE_SCORE
    ]
    state.scores = fresh
    if changed:
        persist_scores(state, changed)
    if visible:
        verdicts = queries.latest_verdicts(state)
        payload = [queries.with_verdict(s, verdicts) for s in visible]
        await hub.broadcast("scores.update", {"cells": payload, "kpis": queries.kpis(state)})
    for alert in engine.check(state, fresh):
        await hub.broadcast("alert.raised", alert)


async def dispatch(state: AppState, hub: Hub, engine: AlertEngine) -> str | None:
    """Create a queued run from coalesced alerts; returns its id (or None if not yet due)."""
    batch = engine.take_batch(state)
    if not batch:
        return None
    run = create_run(state, batch, data_version(state.conn))
    await hub.broadcast("run.queued", run)
    return str(run["run_id"])
