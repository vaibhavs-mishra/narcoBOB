"""The agent-run worker (filled in by M5). For now it only holds the queue."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narcobob.api.state import AppState
    from narcobob.api.ws import Hub


class Worker:
    def __init__(self, state: AppState, hub: Hub) -> None:
        self.state = state
        self.hub = hub
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    def enqueue(self, run_id: str) -> None:
        self.queue.put_nowait(run_id)

    async def run_forever(self) -> None:
        while True:
            await self.queue.get()
