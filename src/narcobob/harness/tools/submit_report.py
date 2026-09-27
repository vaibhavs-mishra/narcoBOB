"""`submit_report`: the Writer's brief. Only way a report enters the system.

Rejected with VALIDATION_ERROR unless it carries at least one enforcement AND one
treatment/prevention recommendation (checked by the `ReportIn` model). Idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from narcobob.common.ids import new_id, wall_now
from narcobob.common.schemas import ReportIn
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "submit_report"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("idempotency_key") or "")
    if not key:
        raise ToolFailure("VALIDATION_ERROR", "idempotency_key is required")
    report = ReportIn.model_validate(args.get("report") or {})
    recs = json.dumps([r.model_dump(mode="json") for r in report.recommendations])

    existing = conn.execute(
        "SELECT report_id, markdown, recommendations, idempotency_key FROM reports"
        " WHERE run_id = ?",
        (ctx.run_id,),
    ).fetchone()
    if existing is not None:
        same = existing["markdown"] == report.markdown and existing["recommendations"] == recs
        if existing["idempotency_key"] == key and same:
            return {"report_id": existing["report_id"], "provenance_ratio": None}
        raise ToolFailure("CONFLICT", "this run already has a different report")

    report_id = new_id()
    conn.execute(
        "INSERT INTO reports(report_id, run_id, markdown, recommendations, provenance_ratio,"
        " source, idempotency_key, wall_at) VALUES (?,?,?,?,?,?,?,?)",
        (report_id, ctx.run_id, report.markdown, recs, None, ctx.source, key, wall_now()),
    )
    conn.commit()
    return {"report_id": report_id, "provenance_ratio": None}
