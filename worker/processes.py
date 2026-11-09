"""Starting and stopping the Celery processes from ``python main.py``.

They stay separate OS processes (not threads in the bot): a long broadcast or
a restore can never slow the bot down, and a crash in one cannot take the bot
with it.

Two workers, one per queue. The broadcasts worker runs one task at a time
(broadcasts are sequential anyway), so a broadcast that lasts hours never
delays the 30-second message deletions handled by the default worker.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from dataclasses import dataclass

from core.config import Settings
from worker.queue import BROADCAST_QUEUE, DEFAULT_QUEUE

log = logging.getLogger(__name__)
STOP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    args: list[str]


def celery_processes(settings: Settings) -> list[ProcessSpec]:
    celery = [sys.executable, "-m", "celery", "-A", "worker.app"]
    level = f"--loglevel={settings.log_level}"
    # Celery's prefork pool needs fork(), which Windows lacks; there the default
    # worker falls back to the solo pool (one task at a time, same queue).
    pool = ["--pool=solo"] if sys.platform == "win32" else [f"--concurrency={settings.worker_concurrency}"]
    return [
        ProcessSpec("worker-default", [*celery, "worker", "-Q", DEFAULT_QUEUE, "-n", "default@%h", *pool, level]),
        ProcessSpec("worker-broadcasts",
                    [*celery, "worker", "-Q", BROADCAST_QUEUE, "-n", "broadcasts@%h", "--pool=solo", level]),
        ProcessSpec("beat", [*celery, "beat", "--schedule", "celerybeat-schedule", level]),
    ]


class ProcessGroup:
    """Child processes that live exactly as long as the bot."""

    def __init__(self, specs: list[ProcessSpec]) -> None:
        self._specs = specs
        self._running: dict[str, asyncio.subprocess.Process] = {}
        self._watchers: list[asyncio.Task] = []
        self._stopping = False

    async def start(self) -> None:
        for spec in self._specs:
            # Output is inherited, so every process logs to the same terminal.
            process = await asyncio.create_subprocess_exec(*spec.args)
            self._running[spec.name] = process
            self._watchers.append(asyncio.create_task(self._watch(spec.name, process)))
            log.info("started %s (pid %s)", spec.name, process.pid)

    async def _watch(self, name: str, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        if not self._stopping:
            log.error("%s exited unexpectedly with code %s", name, code)

    async def stop(self) -> None:
        self._stopping = True
        for process in self._running.values():
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
        for name, process in self._running.items():
            try:
                await asyncio.wait_for(process.wait(), STOP_TIMEOUT_SECONDS)
            except TimeoutError:
                log.warning("%s did not stop in time; killing it", name)
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        for watcher in self._watchers:
            watcher.cancel()
