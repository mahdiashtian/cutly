"""``python main.py`` starts and stops the Celery processes."""
from __future__ import annotations

import sys

from tests.conftest import make_settings
from worker.processes import ProcessGroup, ProcessSpec, celery_processes


def test_one_worker_per_queue_plus_beat(tmp_path):
    specs = {spec.name: spec.args for spec in celery_processes(make_settings(tmp_path))}
    assert set(specs) == {"worker-default", "worker-broadcasts", "beat"}
    assert specs["worker-default"][specs["worker-default"].index("-Q") + 1] == "default"
    broadcasts = specs["worker-broadcasts"]
    assert broadcasts[broadcasts.index("-Q") + 1] == "broadcasts" and "--pool=solo" in broadcasts
    assert all(args[:4] == [sys.executable, "-m", "celery", "-A"] for args in specs.values())


async def test_group_starts_and_stops_its_processes():
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    group = ProcessGroup([ProcessSpec("a", sleeper), ProcessSpec("b", sleeper)])
    await group.start()
    processes = list(group._running.values())
    assert all(process.returncode is None for process in processes)
    await group.stop()
    assert all(process.returncode is not None for process in processes)


async def test_empty_group_is_a_no_op():
    group = ProcessGroup([])
    await group.start()
    await group.stop()
