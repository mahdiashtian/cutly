"""Keep restoration exclusive with respect to handlers and database sessions."""

import asyncio
from contextlib import asynccontextmanager


class OperationGate:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.readers = {}
        self.writers_waiting = 0
        self.restoring = False
        self.generation = 0
        self.download_lock = asyncio.Lock()
        self.downloads = {}

    @asynccontextmanager
    async def operation(self):
        task = asyncio.current_task()
        async with self.condition:
            await self.condition.wait_for(
                lambda: (
                    task in self.readers
                    or (not self.restoring and not self.writers_waiting)
                )
            )
            self.readers[task] = self.readers.get(task, 0) + 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers[task] -= 1
                if not self.readers[task]:
                    del self.readers[task]
                self.condition.notify_all()

    @asynccontextmanager
    async def restoration(self):
        if asyncio.current_task() in self.readers:
            raise RuntimeError("Cannot restore inside a database operation")
        async with self.condition:
            self.writers_waiting += 1
            try:
                await self.condition.wait_for(
                    lambda: not self.readers and not self.restoring
                )
                self.restoring = True
            finally:
                self.writers_waiting -= 1
                self.condition.notify_all()
        try:
            yield
        finally:
            async with self.condition:
                self.generation += 1
                self.restoring = False
                self.condition.notify_all()


_gates = {}


def get_gate():
    loop = asyncio.get_running_loop()
    # A bot has one event loop; tests create separate loops.
    if loop not in _gates:
        _gates.clear()
        _gates[loop] = OperationGate()
    return _gates[loop]
