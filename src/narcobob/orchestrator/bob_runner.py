"""Runs one agent step as a headless IBM Bob Shell process.

Bob 2.0 syntax: `bob run --mode <slug> -w <workspace> --trust --accept-license "<prompt>"`.
The process is started from an argument list (never a shell string). Its output is kept
only as a log: results reach the system exclusively through the MCP harness, so
nothing here parses stdout for data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from narcobob.common.config import SRC_DIR, Settings

log = logging.getLogger(__name__)

AGENTS_DIR = SRC_DIR / "agents"
MAX_TURNS = 40  # matches the harness budget of 40 tool calls per step
MAX_LOG_CHARS = 20_000


@dataclass(frozen=True)
class BobResult:
    exit_code: int | None  # None when killed on timeout
    timed_out: bool
    duration_s: float
    log: str


def bob_command(settings: Settings, agent_id: str, prompt: str) -> list[str]:
    return [
        settings.bob_bin,
        "run",
        "--mode", f"narcobob-{agent_id}",
        "-w", str(AGENTS_DIR),
        "--trust",
        "--accept-license",
        "--disable-subagents",
        "--max-turns", str(MAX_TURNS),
        "--log-level", "warn",
        prompt,
    ]  # fmt: skip


def _child_env(settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    if settings.bob_api_key is not None:
        env["BOB_API_KEY"] = settings.bob_api_key.get_secret_value()
    return env


async def run_agent(settings: Settings, agent_id: str, prompt: str) -> BobResult:
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *bob_command(settings, agent_id, prompt),
        cwd=AGENTS_DIR,
        env=_child_env(settings),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    timed_out = False
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=settings.bob_agent_timeout_s)
    except TimeoutError:
        timed_out = True
        proc.kill()
        out, _ = await proc.communicate()
    duration = time.monotonic() - started
    text = out.decode(errors="replace")[-MAX_LOG_CHARS:]
    log.info(
        "bob step finished",
        extra={"agent": agent_id, "exit": proc.returncode, "timed_out": timed_out,
               "duration_s": round(duration, 1)},
    )  # fmt: skip
    return BobResult(
        exit_code=None if timed_out else proc.returncode,
        timed_out=timed_out,
        duration_s=duration,
        log=text,
    )
