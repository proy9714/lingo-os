"""Polite parallel fetching for content discovery.

Discovery used to make one request at a time with a fixed sleep after each, so a run spent most of its time waiting.
Here a few requests run at once, and a shared `Pacer` keeps their starts a minimum gap apart, so a site sees about
the same gentle stream of requests while the waiting overlaps. Results come back in the order the work was given,
so runs stay deterministic (and the "stop after N failures in a row" rules still mean what they say).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy import Connection, Engine

T = TypeVar("T")
R = TypeVar("R")


# Discovery's halves (videos, articles) write to SQLite from different threads, and storing an article analyses it
# inside its transaction (seconds). They take turns here instead of timing out on SQLite's lock.
DB_WRITE = threading.RLock()


@contextmanager
def writing(engine: Engine) -> Iterator[Connection]:
    """A write transaction for discovery work, one at a time across its threads."""
    with DB_WRITE, engine.begin() as conn:
        yield conn


class Pacer:
    """Request starts at least `gap` seconds apart, across every thread that shares it."""

    def __init__(self, gap: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self.gap, self.sleep = gap, sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.gap
        if start > now:
            self.sleep(start - now)


class Stopped(Exception):
    """The work was given up before it started (an earlier result said to stop)."""


def fan_out(
    items: Iterable[T],
    fetch: Callable[[T], R],
    *,
    workers: int,
    pacer: Pacer | None = None,
    name: str = "fetch",
) -> Iterator[tuple[T, R | None, BaseException | None]]:
    """Run `fetch(item)` on up to `workers` threads; yield (item, result, error) in the items' order as each is ready.

    Stop iterating (break) to give up on what hasn't started yet: queued work is cancelled, and work that is waiting
    for its turn is skipped."""
    items = list(items)
    if not items:
        return
    stop = threading.Event()

    def run(item: T) -> R:
        if stop.is_set():
            raise Stopped()
        if pacer:
            pacer.wait()
        if stop.is_set():
            raise Stopped()
        return fetch(item)

    if workers <= 1:  # the same behaviour without threads (and what tests with fake fetchers see)
        for item in items:
            try:
                yield item, run(item), None
            except Exception as exc:  # noqa: BLE001 - handed to the caller
                yield item, None, exc
        return

    pool = ThreadPoolExecutor(max_workers=min(workers, len(items)), thread_name_prefix=name)
    futures: list[Future[R]] = [pool.submit(run, item) for item in items]
    try:
        for item, future in zip(items, futures):
            try:
                yield item, future.result(), None
            except Exception as exc:  # noqa: BLE001 - handed to the caller
                yield item, None, exc
    finally:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
