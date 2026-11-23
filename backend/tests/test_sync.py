from __future__ import annotations

import pytest

from app.sync.hlc import HybridClock, Stamp
from app.sync.ids import new_ulid, ulid_timestamp_ms


def test_ulids_sort_by_creation_time() -> None:
    first, second = new_ulid(1_000), new_ulid(2_000)
    assert len(first) == 26 and first < second
    assert ulid_timestamp_ms(second) == 2_000
    assert new_ulid() != new_ulid()


def test_clock_is_monotonic_when_wall_clock_stalls() -> None:
    clock = HybridClock("PHONE", now_ms=lambda: 1_000)
    stamps = [clock.tick() for _ in range(5)]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == 5


def test_clock_jumps_past_a_device_that_runs_ahead() -> None:
    laptop = HybridClock("LAPTOP", now_ms=lambda: 1_000)
    phone = HybridClock("PHONE", now_ms=lambda: 5_000)
    remote = phone.tick()
    merged = laptop.receive(remote)
    assert merged > remote
    assert laptop.tick() > merged
    assert Stamp.decode(merged).millis == 5_000


def test_last_writer_wins_is_plain_string_max() -> None:
    a = HybridClock("A", now_ms=lambda: 2_000).tick()
    b = HybridClock("B", now_ms=lambda: 1_000).tick()
    assert max(a, b) == a


def test_device_ids_cannot_contain_the_separator() -> None:
    with pytest.raises(ValueError):
        HybridClock("bad-id")
