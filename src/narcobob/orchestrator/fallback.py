"""Deterministic fallback agents: rule-based twins of the four Bob agents (SPEC §8.3).

They are the safety net when Bob is unavailable, the `make dev-fallback` path, and the
test oracle. They act *only* through the harness tools (same checks, same tracing,
same schemas), so a fallback output is indistinguishable in shape from a Bob output;
the UI labels its source honestly.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from types import ModuleType
from typing import Any

import h3
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from narcobob.harness.envelope import CallContext, execute
from narcobob.harness.tools import (
    get_cell_scores,
    get_cell_timeseries,
    get_data_quality,
    get_findings,
    get_neighbors,
    get_run_context,
    get_support,
    run_sensitivity,
    submit_findings,
    submit_report,
)
from narcobob.orchestrator.skeptic_rules import CellFacts, judge

DRIVER_LABEL = {
    "accel": "accelerating overdose admissions",
    "div": "harm outpacing enforcement (divergence)",
    "spill": "spillover from neighbouring cells",
    "gi": "a statistically significant hotspot (Gi*)",
}
RANK = ["NORMAL", "WATCH", "HIGH", "CRITICAL"]
_TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,  # markdown output, never rendered as HTML by us
)


class ToolError(RuntimeError):
    pass


def _tool(
    conn: sqlite3.Connection, ctx: CallContext, tool: ModuleType, **args: Any
) -> dict[str, Any]:
    envelope = execute(conn, ctx, tool.NAME, tool.VERSION, tool.run, args)
    if not envelope["ok"]:
        raise ToolError(f"{tool.NAME}: {envelope['error']}")
    data: dict[str, Any] = envelope["data"]
    return data


def location(cell: str) -> str:
    lat, lon = h3.cell_to_latlng(cell)
    return f"{lat:.3f}°N {lon:.3f}°E"


# ── Steward ──────────────────────────────────────────────────────────────────


def steward(conn: sqlite3.Connection, ctx: CallContext) -> None:
    cells = _tool(conn, ctx, get_run_context)["cells"]
    dq = _tool(conn, ctx, get_data_quality, cells=cells, window_buckets=14)
    shares = {s["cell"]: s for s in dq["single_source"]}
    findings = []
    for cell in cells:
        gaps = [g for g in dq["source_gaps"] if cell in g["cells_affected"]]
        share = shares.get(cell)
        if gaps:
            g = gaps[0]
            payload = {
                "cell": cell,
                "issue": "source_gap",
                "affects_recent_window": g["in_recent_window"],
                "detail": f"{g['source']} reported nothing for buckets {g['from_bucket']}–"
                f"{g['to_bucket']}; this cell depends on it.",
            }
        elif share is not None and share["share"] > 0.8:
            payload = {
                "cell": cell,
                "issue": "single_source",
                "affects_recent_window": True,
                "detail": f"{share['share']:.0%} of recent events come from {share['source']}.",
            }
        else:
            top = f"top source share {share['share']:.0%}" if share else "no recent events"
            payload = {
                "cell": cell,
                "issue": "ok",
                "affects_recent_window": False,
                "detail": f"No feed gap affects this cell; {top}; "
                f"{dq['duplicates']} duplicates and {dq['late_events']} late "
                "events seen at ingest overall.",
            }
        findings.append({"kind": "data_quality", "payload": payload})
    _tool(conn, ctx, submit_findings, findings=findings, idempotency_key=f"{ctx.step_id}-dq")


# ── Analyst ──────────────────────────────────────────────────────────────────


def clusters(cells: list[str]) -> dict[str, str]:
    """Group adjacent cells: cluster ids C1, C2, … in order of first appearance."""
    parent = {c: c for c in cells}

    def find(c: str) -> str:
        while parent[c] != c:
            c = parent[c]
        return c

    for a in cells:
        for b in cells:
            if a < b and h3.grid_distance(a, b) <= 1:
                parent[find(b)] = find(a)
    names: dict[str, str] = {}
    return {c: names.setdefault(find(c), f"C{len(names) + 1}") for c in cells}


def alerted_severity(alerts: list[dict[str, Any]]) -> dict[str, str]:
    """Per cell: the highest severity among this run's alerts (what the agents review)."""
    out: dict[str, str] = {}
    for a in alerts:
        if RANK.index(a["severity"]) > RANK.index(out.get(a["cell"], "NORMAL")):
            out[a["cell"]] = a["severity"]
    return out


def analyst(conn: sqlite3.Connection, ctx: CallContext) -> None:
    context = _tool(conn, ctx, get_run_context)
    cells = context["cells"]
    claimed = alerted_severity(context["alerts"])
    scores = {s["cell"]: s for s in _tool(conn, ctx, get_cell_scores, cells=cells)["cells"]}
    cluster_of = clusters(cells)
    findings = []
    for cell in cells:
        s = scores.get(cell)
        if s is None:
            continue
        comps = s["components"]
        drivers = sorted(comps, key=lambda d: comps[d]["contrib"], reverse=True)
        positive = [d for d in drivers if comps[d]["contrib"] > 0] or drivers[:1]
        hot = [
            n
            for n in _tool(conn, ctx, get_neighbors, cell=cell, k=1)["neighbors"]
            if n["severity"] in ("HIGH", "CRITICAL")
        ]
        evidence = "; ".join(
            f"{DRIVER_LABEL[d]} (z {comps[d]['z']:+.2f}, contributes {comps[d]['contrib']:+.2f})"
            for d in positive[:3]
        )
        narrative = (
            f"Alerted at {claimed.get(cell, s['severity'])}; now score {s['score']}"
            f" ({s['severity']}), support {s['support']} events"
            f" ({s['confidence']} confidence). Driven by {evidence}."
            + (f" {len(hot)} adjacent cell(s) are also HIGH or above." if hot else "")
        )
        findings.append(
            {
                "kind": "analysis",
                "payload": {
                    "cell": cell,
                    "cluster_id": cluster_of[cell],
                    "drivers": positive,
                    "narrative": narrative[:500],
                    "claimed_severity": claimed.get(cell, s["severity"]),
                },
            }
        )
    _tool(conn, ctx, submit_findings, findings=findings, idempotency_key=f"{ctx.step_id}-an")


# ── Skeptic ──────────────────────────────────────────────────────────────────


def _growth(series: list[int]) -> float:
    recent, prior = sum(series[-7:]), sum(series[-14:-7])
    return math.log((recent + 1) / (prior + 1))


def skeptic(conn: sqlite3.Connection, ctx: CallContext) -> None:
    analyses = _tool(conn, ctx, get_findings, kind="analysis")["findings"]
    claims = {f["payload"]["cell"]: f["payload"] for f in analyses}
    cells = list(claims) or _tool(conn, ctx, get_run_context)["cells"]
    support = {s["cell"]: s for s in _tool(conn, ctx, get_support, cells=cells)["cells"]}
    stability = {s["cell"]: s for s in _tool(conn, ctx, run_sensitivity, cells=cells)["cells"]}
    dq = _tool(conn, ctx, get_data_quality, cells=cells, window_buckets=14)
    findings = []
    for cell in cells:
        ts = _tool(conn, ctx, get_cell_timeseries, cell=cell, buckets=14)["series"]
        enforcement = [a + b for a, b in zip(ts["seizure"], ts["arrest"], strict=True)]
        sup = support[cell]
        facts = CellFacts(
            cell=cell,
            engine_severity=claims.get(cell, {}).get("claimed_severity", "HIGH"),
            support=int(sup["support"]),
            confidence=sup["confidence"],
            stability=float(stability[cell]["stability"]),
            gap_in_recent_window=any(
                g["in_recent_window"] and cell in g["cells_affected"] for g in dq["source_gaps"]
            ),
            od_growth=_growth(ts["overdose"]),
            enforcement_growth=_growth(enforcement),
            top_source_share=float(sup["top_source_share"]),
        )
        v = judge(facts)
        rationale = (
            f"{v.rationale}. Support {facts.support}, weight stability {facts.stability:.2f},"
            f" overdose growth {facts.od_growth:+.2f}"
            f" vs enforcement {facts.enforcement_growth:+.2f}"
            " (log ratio, last 7 vs prior 7 days)."
        )
        findings.append(
            {
                "kind": "verdict",
                "payload": {
                    "cell": cell,
                    "verdict": v.verdict,
                    "final_severity": v.final_severity,
                    "checks": v.checks,
                    "rationale": rationale[:400],
                },
            }
        )
    _tool(conn, ctx, submit_findings, findings=findings, idempotency_key=f"{ctx.step_id}-vd")


# ── Writer ───────────────────────────────────────────────────────────────────


def recommendations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At least one enforcement and one treatment action, prioritised by final severity."""
    critical = [r["cell"] for r in rows if r["final_severity"] == "CRITICAL"]
    high = [r["cell"] for r in rows if r["final_severity"] == "HIGH"]
    watch = [r["cell"] for r in rows if r["final_severity"] in ("WATCH", "NORMAL")]
    urgent = critical + high
    recs: list[dict[str, Any]] = []
    if urgent:
        priority = "immediate" if critical else "this_week"
        recs += [
            {
                "track": "enforcement",
                "cells": urgent,
                "priority": priority,
                "action": "Intelligence-led interdiction on supply routes into the confirmed cells;"
                " prioritise distribution points over users.",
            },
            {
                "track": "treatment",
                "cells": urgent,
                "priority": priority,
                "action": "Scale de-addiction outreach and naloxone at nearby hospitals and PHCs;"
                " use the NDPS s.64A pathway to divert users into treatment.",
            },
            {
                "track": "treatment",
                "cells": urgent,
                "priority": "this_week",
                "action": "Run awareness sessions in schools and villages in these cells with"
                " district health and education officers.",
            },
        ]
    if watch or not urgent:
        cells = watch or [r["cell"] for r in rows]
        recs += [
            {
                "track": "enforcement",
                "cells": cells,
                "priority": "monitor",
                "action": "No deployment change; keep these cells on the watch list and re-check"
                " after the next reporting cycle.",
            },
            {
                "track": "treatment",
                "cells": cells,
                "priority": "monitor",
                "action": "Ask local health facilities to confirm overdose reporting is complete"
                " before acting on these cells.",
            },
        ]
    return recs


def writer(conn: sqlite3.Connection, ctx: CallContext) -> None:
    context = _tool(conn, ctx, get_run_context)
    cells = context["cells"]
    scores = {s["cell"]: s for s in _tool(conn, ctx, get_cell_scores, cells=cells)["cells"]}
    found = _tool(conn, ctx, get_findings)["findings"]
    by = {
        k: {f["payload"].get("cell"): f["payload"] for f in found if f["kind"] == k}
        for k in ("data_quality", "analysis", "verdict")
    }

    rows = []
    for cell in cells:
        s, v, a = scores.get(cell, {}), by["verdict"].get(cell, {}), by["analysis"].get(cell, {})
        rows.append(
            {
                "cell": cell,
                "label": f"`{cell}`",
                "location": location(cell),
                "score": s.get("score", "n/a"),
                "severity": s.get("severity", "n/a"),
                "support": s.get("support", "n/a"),
                "confidence": s.get("confidence", "n/a"),
                "final_severity": v.get("final_severity", s.get("severity", "n/a")),
                "verdict": v.get("verdict", "NOT_REVIEWED"),
                "rationale": v.get("rationale", ""),
                "checks": v.get("checks", {}),
                "narrative": a.get("narrative", "No analysis."),
            }
        )
    rows.sort(
        key=lambda r: (
            RANK.index(r["final_severity"]) if r["final_severity"] in RANK else -1,
            r["score"] if isinstance(r["score"], int) else 0,
        ),
        reverse=True,
    )
    recs = recommendations(rows)
    caveats = [f"`{c}`: {p['detail']}" for c, p in by["data_quality"].items() if p["issue"] != "ok"]
    weights = context["config"]["weights"]
    markdown = _TEMPLATES.get_template("report_template.md.j2").render(
        area_name=context["config"]["area_name"],
        run_id=ctx.run_id,
        sim_now=context["sim_now"],
        source=ctx.source,
        cells=rows,
        confirmed=[
            r
            for r in rows
            if r["verdict"] == "CONFIRMED" and r["final_severity"] in ("HIGH", "CRITICAL")
        ],
        challenged=[r for r in rows if r["verdict"] in ("DOWNGRADED", "REJECTED")],
        enforcement=[r for r in recs if r["track"] == "enforcement"],
        treatment=[r for r in recs if r["track"] == "treatment"],
        caveats=caveats,
        weights=", ".join(f"{k} {v:.2f}" for k, v in weights.items()),
    )
    _tool(
        conn,
        ctx,
        submit_report,
        report={"markdown": markdown, "recommendations": recs},
        idempotency_key=f"{ctx.step_id}-report",
    )


AGENTS = {"steward": steward, "analyst": analyst, "skeptic": skeptic, "writer": writer}
