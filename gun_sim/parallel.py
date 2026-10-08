"""Worker processes, so a shot's separate solves run at the same time.

Python threads share one interpreter lock, so the flash, the sound and the recoil
would take turns on a single core. Each kind of job runs in a lane of its own
instead: one worker process per lane, kept alive so the caches inside it (the
sound's blast, the plume) stay warm between calls.

The fluid shot the others build on is solved once and handed to each job as its
seed, which fills that worker's fluid.simulate_cached() before the job runs.

Set GUN_SIM_WORKERS=0 to run everything inline on the calling thread instead.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

INLINE = os.environ.get("GUN_SIM_WORKERS", "").strip() == "0"

_lanes: dict[str, ProcessPoolExecutor] = {}
_lock = threading.Lock()


def _init() -> None:
    # Import the whole simulator up front, so the first job doesn't pay for it.
    from .ui import api  # noqa: F401


def _job(seed, fn, args, kwargs):
    if seed is not None:
        from . import fluid
        fluid.remember(*seed)
    return fn(*args, **kwargs)


def _lane(name: str, fresh: bool = False) -> ProcessPoolExecutor:
    with _lock:
        if fresh or name not in _lanes:
            old = _lanes.pop(name, None)
            if old is not None:
                old.shutdown(wait=False, cancel_futures=True)
            _lanes[name] = ProcessPoolExecutor(max_workers=1, initializer=_init)
        return _lanes[name]


def submit(lane: str, fn, *args, seed: tuple | None = None, **kwargs) -> Future:
    """Run fn(*args, **kwargs) in the lane's worker. fn must be a module-level function.

    seed: (gun, blowdown_time, ambient_pressure, shot) to remember as that fluid run first.
    """
    if INLINE:
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as e:
            future.set_exception(e)
        return future
    try:
        return _lane(lane).submit(_job, seed, fn, args, kwargs)
    except BrokenProcessPool:  # its worker died (out of memory, killed); start another
        return _lane(lane, fresh=True).submit(_job, seed, fn, args, kwargs)


def run(lane: str, fn, *args, seed: tuple | None = None, **kwargs):
    """submit() and wait for the result."""
    return submit(lane, fn, *args, seed=seed, **kwargs).result()


def warm(*lanes: str) -> None:
    """Start the lanes' workers now, so the first shot doesn't wait for them to boot."""
    if not INLINE:
        for name in lanes:
            submit(name, int)


def shutdown() -> None:
    with _lock:
        for ex in _lanes.values():
            ex.shutdown(wait=False, cancel_futures=True)
        _lanes.clear()
