"""`submit_findings`: the only way steward, analyst and skeptic write results.

Each agent may submit only its own finding kind. Re-sending the same
`idempotency_key` with the same payload returns the original ids (safe retries);
with a different payload it is a CONFLICT.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from narcobob.common.ids import new_id, wall_now
from narcobob.common.schemas import AGENT_FINDING_KIND, FindingIn
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "submit_findings"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("idempotency_key") or "")
    if not key:
        raise ToolFailure("VALIDATION_ERROR", "idempotency_key is required")
    findings = [FindingIn.model_validate(f) for f in args.get("findings") or []]
    if not findings:
        raise ToolFailure("VALIDATION_ERROR", "findings must contain at least one finding")

    allowed_kind = AGENT_FINDING_KIND[ctx.agent_id]
    rows = []
    for index, finding in enumerate(findings):
        if finding.kind != allowed_kind:
            raise ToolFailure(
                "VALIDATION_ERROR", f"{ctx.agent_id} may only submit kind={allowed_kind!r}"
            )
        payload = finding.parsed().model_dump(mode="json")
        rows.append((f"{key}:{index}", finding.kind, payload))

    existing = {
        r["idempotency_key"]: r
        for r in conn.execute(
            "SELECT finding_id, idempotency_key, payload FROM findings WHERE run_id = ?"
            " AND idempotency_key LIKE ?",
            (ctx.run_id, f"{key}:%"),
        )
    }
    if existing:
        same = len(existing) == len(rows) and all(
            k in existing and json.loads(existing[k]["payload"]) == p for k, _, p in rows
        )
        if not same:
            raise ToolFailure("CONFLICT", "idempotency_key reused with a different payload")
        return {"finding_ids": [existing[k]["finding_id"] for k, _, _ in rows]}

    ids = []
    for row_key, kind, payload in rows:
        finding_id = new_id()
        ids.append(finding_id)
        conn.execute(
            "INSERT INTO findings(finding_id, run_id, step_id, agent_id, kind, cell, payload,"
            " source, idempotency_key, wall_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                finding_id,
                ctx.run_id,
                ctx.step_id,
                ctx.agent_id,
                kind,
                payload.get("cell"),
                json.dumps(payload),
                ctx.source,
                row_key,
                wall_now(),
            ),
        )
    conn.commit()
    return {"finding_ids": ids}
