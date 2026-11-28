"""Polite parallel fetching for content discovery (services/pacing.py)."""

from __future__ import annotations

import threading
import time

from app.services.pacing import Pacer, fan_out


def test_results_come_back_in_order_and_the_waits_overlap() -> None:
    def slow(n: int) -> int:
        time.sleep(0.2)
        return n * 10

    began = time.monotonic()
    out = [(item, result, error) for item, result, error in fan_out(range(6), slow, workers=3)]
    elapsed = time.monotonic() - began
    assert out == [(n, n * 10, None) for n in range(6)]
    assert elapsed < 0.2 * 6 * 0.7  # well under one-at-a-time (1.2 s)


def test_errors_are_handed_back_not_raised() -> None:
    def flaky(n: int) -> int:
        if n == 1:
            raise ValueError("nope")
        return n

    out = list(fan_out([0, 1, 2], flaky, workers=2))
    assert out[0] == (0, 0, None) and out[2] == (2, 2, None)
    assert isinstance(out[1][2], ValueError)


def test_stopping_early_skips_work_not_started() -> None:
    calls: list[int] = []
    lock = threading.Lock()

    def record(n: int) -> int:
        with lock:
            calls.append(n)
        time.sleep(0.05)
        return n

    for item, _result, _error in fan_out(range(30), record, workers=2):
        if item == 1:
            break
    assert len(calls) < 10  # the rest was cancelled


def test_the_pacer_spaces_request_starts() -> None:
    slept: list[float] = []
    pacer = Pacer(1.0, sleep=slept.append)
    for _ in range(3):
        pacer.wait()
    assert slept[0] > 0.9 and slept[1] > 1.9  # the second and third start 1 s and 2 s after the first


def test_one_worker_runs_without_threads() -> None:
    names: list[str] = []
    list(fan_out([1, 2], lambda n: names.append(threading.current_thread().name), workers=1))
    assert set(names) == {threading.current_thread().name}
