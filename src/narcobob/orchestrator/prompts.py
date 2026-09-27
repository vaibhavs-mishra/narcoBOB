"""The per-step prompt handed to a headless Bob agent (SPEC §8.1).

Deliberately short: each agent's behaviour lives in its custom mode and rules files
(`agents/.bob/`). The prompt only carries the ids and the cells for this run.
"""

from __future__ import annotations

FINISH_TOOL = {
    "steward": "submit_findings",
    "analyst": "submit_findings",
    "skeptic": "submit_findings",
    "writer": "submit_report",
}


def build_prompt(agent_id: str, run_id: str, step_id: str, cells: list[str]) -> str:
    return (
        f"RUN_ID={run_id} AGENT_ID={agent_id} STEP_ID={step_id}\n"
        f"Alerted cells: {', '.join(cells)}.\n"
        "Follow your mode rules. Use only the `narcobob` MCP tools. Pass run_id, agent_id and "
        f"step_id on every call. Finish by calling {FINISH_TOOL[agent_id]} exactly once."
    )
