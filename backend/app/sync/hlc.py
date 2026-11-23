"""Hybrid logical clock.

Timestamps look like `0001795445422123-0003-<device id>`: wall-clock milliseconds,
a counter that breaks ties, and the device id. Plain string comparison orders
them, so "last writer wins" is simply `max()` over the stored strings, even when
the phone's clock is a little off.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Stamp:
    millis: int
    counter: int
    device: str

    def encode(self) -> str:
        return f"{self.millis:016d}-{self.counter:04d}-{self.device}"

    @classmethod
    def decode(cls, value: str) -> "Stamp":
        millis, counter, device = value.split("-", 2)
        return cls(int(millis), int(counter), device)


class HybridClock:
    def __init__(self, device: str, now_ms: Callable[[], int] | None = None) -> None:
        if "-" in device:
            raise ValueError("device id must not contain '-'")
        self.device = device
        self._now = now_ms or (lambda: int(time.time() * 1000))
        self._millis = 0
        self._counter = 0
        self._lock = threading.Lock()

    def tick(self) -> str:
        """Stamp for a local event."""
        with self._lock:
            physical = self._now()
            if physical > self._millis:
                self._millis, self._counter = physical, 0
            else:
                self._counter += 1
            return Stamp(self._millis, self._counter, self.device).encode()

    def receive(self, remote: str) -> str:
        """Merge a stamp received from another device; returns the stamp for the merge event."""
        other = Stamp.decode(remote)
        with self._lock:
            physical = self._now()
            newest = max(self._millis, other.millis, physical)
            if newest == self._millis == other.millis:
                counter = max(self._counter, other.counter) + 1
            elif newest == self._millis:
                counter = self._counter + 1
            elif newest == other.millis:
                counter = other.counter + 1
            else:
                counter = 0
            self._millis, self._counter = newest, counter
            return Stamp(newest, counter, self.device).encode()
