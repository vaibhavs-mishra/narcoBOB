"""The orchestrator: a deterministic state machine per agent run (SPEC §8.1).

QUEUED → steward → analyst → skeptic → writer → DONE (or FAILED_WITH_FALLBACK).

For each step it inserts a `running` agent_steps row, which is what authorises that
agent's tool calls in the harness. In bob mode it runs the agent headless, checks that
the agent actually submitted its output, retries once, and otherwise runs the
deterministic fallback agent for that step. Outputs are never parsed from stdout.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from narcobob.common.ids import new_id, wall_now
from narcobob.harness.envelope import CallContext
from narcobob.orchestrator import fallback
from narcobob.orchestrator.bob_runner import run_agent
from narcobob.orchestrator.prompts import build_prompt

if TYPE_CHECKING:
    from narcobob.api.state import AppState
    from narcobob.api.ws import Hub

log = logging.getLogger(__name__)

AGENT_ORDER = ("steward", "analyst", "skeptic", "writer")
MAX_WAITING = 3
POLL_S = 0.5


class Worker:
    def __init__(self, state: AppState, hub: Hub) -> None:
        self.state = state
        self.hub = hub
        self.waiting: list[str] = []
        self._wake = asyncio.Event()
        self._last_call_rowid = 0
        self._last_finding_rowid = 0

    @property
    def conn(self) -> Any:
        return self.state.conn

    # ── queue ────────────────────────────────────────────────────────────────

    def enqueue(self, run_id: str) -> None:
        """Queue a run. Beyond MAX_WAITING, the oldest waiting run merges into this one."""
        if len(self.waiting) >= MAX_WAITING:
            self._merge(self.waiting.pop(0), into=run_id)
        self.waiting.append(run_id)
        self._wake.set()

    def _merge(self, old: str, into: str) -> None:
        rows = {
            r["run_id"]: r
            for r in self.conn.execute(
                "SELECT run_id, alert_ids, cells FROM agent_runs WHERE run_id IN (?, ?)",
                (old, into),
            )
        }
        alerts = json.loads(rows[into]["alert_ids"]) + json.loads(rows[old]["alert_ids"])
        cells = sorted(set(json.loads(rows[into]["cells"])) | set(json.loads(rows[old]["cells"])))
        self.conn.execute(
            "UPDATE agent_runs SET alert_ids = ?, cells = ? WHERE run_id = ?",
            (json.dumps(alerts), json.dumps(cells), into),
        )
        self.conn.execute("UPDATE alerts SET run_id = ? WHERE run_id = ?", (into, old))
        self.conn.execute("DELETE FROM agent_runs WHERE run_id = ?", (old,))
        self.conn.commit()

    async def run_forever(self) -> None:
        self._last_call_rowid = self._max_rowid("tool_calls")
        self._last_finding_rowid = self._max_rowid("findings")
        while True:
            if not self.waiting:
                self._wake.clear()
                await self._wake.wait()
                continue
            run_id = self.waiting.pop(0)
            try:
                await self.execute_run(run_id)
            except Exception:
                log.exception("run crashed", extra={"run_id": run_id})
                await self._finish_run(run_id, "FAILED_WITH_FALLBACK")

    # ── one run ──────────────────────────────────────────────────────────────

    async def execute_run(self, run_id: str) -> str:
        row = self.conn.execute(
            "SELECT cells FROM agent_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return "MISSING"
        cells: list[str] = json.loads(row["cells"])
        self.conn.execute(
            "UPDATE agent_runs SET status = 'RUNNING', wall_started_at = ? WHERE run_id = ?",
            (wall_now(), run_id),
        )
        self.conn.commit()
        await self._broadcast_run("run.started", run_id)

        used_fallback = False
        for agent_id in AGENT_ORDER:
            source = await self._run_step(run_id, agent_id, cells)
            used_fallback |= source == "fallback" and self.state.settings.agents_mode == "bob"
            if agent_id == "skeptic":
                await self._apply_verdicts(run_id)
        report = self.conn.execute(
            "SELECT report_id, provenance_ratio FROM reports WHERE run_id = ?", (run_id,)
        ).fetchone()
        if report is not None:
            await self.hub.broadcast("report.ready", {"run_id": run_id, **dict(report)})
        status = "FAILED_WITH_FALLBACK" if used_fallback else "DONE"
        await self._finish_run(run_id, status)
        return status

    async def _run_step(self, run_id: str, agent_id: str, cells: list[str]) -> str:
        step_id = new_id()
        self.conn.execute(
            "INSERT INTO agent_steps(step_id, run_id, agent_id, status, source, attempt,"
            " wall_started_at) VALUES (?,?,?,?,?,?,?)",
            (step_id, run_id, agent_id, "running", None, 1, wall_now()),
        )
        self.conn.commit()
        await self._step_event(run_id, step_id, agent_id, "running", None, 1)

        logs: list[str] = []
        if self.state.settings.agents_mode == "bob":
            for attempt in (1, 2):
                self.conn.execute(
                    "UPDATE agent_steps SET attempt = ? WHERE step_id = ?", (attempt, step_id)
                )
                self.conn.commit()
                if attempt == 2:
                    await self._step_event(run_id, step_id, agent_id, "running", None, 2)
                prompt = build_prompt(agent_id, run_id, step_id, cells)
                task = asyncio.create_task(run_agent(self.state.settings, agent_id, prompt))
                while not task.done():
                    await asyncio.sleep(POLL_S)
                    await self.stream_activity()
                result = task.result()
                logs.append(
                    f"--- attempt {attempt} exit={result.exit_code} "
                    f"timed_out={result.timed_out} {result.duration_s:.1f}s\n{result.log}"
                )
                await self.stream_activity()
                if self._has_output(step_id, agent_id):
                    return await self._end_step(
                        run_id, step_id, agent_id, "done", "bob", logs, attempt
                    )

        ctx = CallContext(run_id=run_id, agent_id=agent_id, step_id=step_id, source="fallback")
        try:
            fallback.AGENTS[agent_id](self.conn, ctx)
        except fallback.ToolError as exc:
            logs.append(f"fallback failed: {exc}")
            log.error("fallback agent failed", extra={"agent": agent_id, "error": str(exc)})
        await self.stream_activity()
        attempt = 2 if self.state.settings.agents_mode == "bob" else 1
        status = "fallback" if self._has_output(step_id, agent_id) else "failed"
        return await self._end_step(run_id, step_id, agent_id, status, "fallback", logs, attempt)

    def _has_output(self, step_id: str, agent_id: str) -> bool:
        if agent_id == "writer":
            sql = (
                "SELECT 1 FROM reports r JOIN agent_steps s ON s.run_id = r.run_id"
                " WHERE s.step_id = ?"
            )
        else:
            sql = "SELECT 1 FROM findings WHERE step_id = ?"
        return self.conn.execute(sql, (step_id,)).fetchone() is not None

    async def _end_step(
        self,
        run_id: str,
        step_id: str,
        agent_id: str,
        status: str,
        source: str,
        logs: list[str],
        attempt: int,
    ) -> str:
        self.conn.execute(
            "UPDATE agent_steps SET status = ?, source = ?, log = ?, wall_finished_at = ?"
            " WHERE step_id = ?",
            (status, source, "\n".join(logs)[-20_000:] or None, wall_now(), step_id),
        )
        self.conn.commit()
        await self._step_event(run_id, step_id, agent_id, status, source, attempt)
        return source

    async def _apply_verdicts(self, run_id: str) -> None:
        """Final severity = the Skeptic's verdict (SPEC §8.2)."""
        verdicts = {
            r["cell"]: json.loads(r["payload"])
            for r in self.conn.execute(
                "SELECT cell, payload FROM findings WHERE run_id = ? AND kind = 'verdict'",
                (run_id,),
            )
        }
        for alert in self.conn.execute(
            "SELECT * FROM alerts WHERE run_id = ?", (run_id,)
        ).fetchall():
            v = verdicts.get(alert["cell"])
            if v is None:
                continue
            self.conn.execute(
                "UPDATE alerts SET final_severity = ?, verdict = ? WHERE alert_id = ?",
                (v["final_severity"], v["verdict"], alert["alert_id"]),
            )
            self.conn.commit()
            updated = dict(alert) | {"final_severity": v["final_severity"], "verdict": v["verdict"]}
            await self.hub.broadcast("alert.updated", updated)

    async def _finish_run(self, run_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE agent_runs SET status = ?, wall_finished_at = ? WHERE run_id = ?",
            (status, wall_now(), run_id),
        )
        self.conn.commit()
        await self._broadcast_run("run.finished", run_id)

    # ── live activity for the UI ─────────────────────────────────────────────

    def _max_rowid(self, table: str) -> int:
        return int(self.conn.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {table}").fetchone()[0])

    async def stream_activity(self) -> None:
        """Broadcast tool calls and findings written since the last poll (by any process)."""
        # A reset empties the tables and SQLite restarts rowids at 1: rewind the cursors.
        if self._max_rowid("tool_calls") < self._last_call_rowid:
            self._last_call_rowid = 0
        if self._max_rowid("findings") < self._last_finding_rowid:
            self._last_finding_rowid = 0
        calls = self.conn.execute(
            "SELECT rowid, run_id, step_id, agent_id, tool, ok, error_code, duration_ms, wall_at"
            " FROM tool_calls WHERE rowid > ? ORDER BY rowid",
            (self._last_call_rowid,),
        ).fetchall()
        for c in calls:
            self._last_call_rowid = c["rowid"]
            payload = {
                k: c[k]
                for k in (
                    "run_id",
                    "step_id",
                    "agent_id",
                    "tool",
                    "error_code",
                    "duration_ms",
                    "wall_at",
                )
            } | {"ok": bool(c["ok"])}
            await self.hub.broadcast("agent.tool_call", payload)
        findings = self.conn.execute(
            "SELECT rowid, run_id, agent_id, kind, cell, payload FROM findings WHERE rowid > ?"
            " ORDER BY rowid",
            (self._last_finding_rowid,),
        ).fetchall()
        for f in findings:
            self._last_finding_rowid = f["rowid"]
            await self.hub.broadcast(
                "finding.posted",
                {
                    "run_id": f["run_id"],
                    "agent_id": f["agent_id"],
                    "kind": f["kind"],
                    "cell": f["cell"],
                    "summary": summarize(f["kind"], json.loads(f["payload"])),
                },
            )

    async def _step_event(
        self,
        run_id: str,
        step_id: str,
        agent_id: str,
        status: str,
        source: str | None,
        attempt: int,
    ) -> None:
        await self.hub.broadcast(
            "agent.step",
            {
                "run_id": run_id,
                "step_id": step_id,
                "agent_id": agent_id,
                "status": status,
                "source": source,
                "attempt": attempt,
            },
        )

    async def _broadcast_run(self, type_: str, run_id: str) -> None:
        from narcobob.api.queries import run_summary

        summary = run_summary(self.state, run_id)
        if summary is not None:
            await self.hub.broadcast(type_, summary)


def summarize(kind: str, payload: dict[str, Any]) -> str:
    if kind == "verdict":
        verdict = f"{payload.get('verdict')} → {payload.get('final_severity')}"
        text = f"{verdict}: {payload.get('rationale', '')}"
    elif kind == "analysis":
        text = (
            f"{payload.get('claimed_severity')} · drivers {', '.join(payload.get('drivers', []))}"
        )
    else:
        text = f"{payload.get('issue')}: {payload.get('detail', '')}"
    return text[:200]
