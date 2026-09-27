"""The per-step prompt handed to a headless Bob agent.

Deliberately short: each agent's behaviour lives in its custom mode and rules files
(`agents/.bob/`). The prompt only carries the ids and the cells for this run.
"""

from __future__ import annotations


def build_prompt(agent_id: str, run_id: str, step_id: str, cells: list[str]) -> str:
    return (
        f"RUN_ID={run_id} AGENT_ID={agent_id} STEP_ID={step_id}\n"
        f"Alerted cells: {', '.join(cells)}.\n"
        "Use exactly these ids on every narcobob tool call. Follow your mode rules and finish "
        "with your single submit call."
    )
