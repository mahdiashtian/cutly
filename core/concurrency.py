"""Per-key async locks with bounded lifetime and cancellation-safe cleanup."""

import asyncio
from contextlib import asynccontextmanager


class KeyedLocks:
    def __init__(self):
        self.entries = {}

    @asynccontextmanager
    async def hold(self, keys):
        entries, acquired = [], []
        for key in sorted(set(keys)):
            entry = self.entries.setdefault(key, [asyncio.Lock(), 0])
            entry[1] += 1
            entries.append((key, entry))
        try:
            for _, entry in entries:
                await entry[0].acquire()
                acquired.append(entry)
            yield
        finally:
            for entry in reversed(acquired):
                entry[0].release()
            for key, entry in entries:
                entry[1] -= 1
                if not entry[1]:
                    del self.entries[key]


async def bounded_map(function, values, *, concurrency=5):
    """Use a fixed number of tasks, keeping result order and cancellation clean."""
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    results = [None] * len(values)
    iterator = iter(enumerate(values))

    async def worker():
        for index, value in iterator:
            results[index] = await function(value)

    tasks = [
        asyncio.create_task(worker()) for _ in range(min(concurrency, len(values)))
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return results


async def run_blocking(function, *args, on_cancel=None):
    """Finish a thread's file access before cancellation closes/deletes its file."""
    worker = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        if on_cancel is not None:
            on_cancel()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise
