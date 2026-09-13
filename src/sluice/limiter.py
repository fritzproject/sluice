"""A concurrency limit that can be resized while work is already running."""

from __future__ import annotations

import threading
from types import TracebackType


class Limiter:
    """A semaphore whose ceiling can be raised or lowered at runtime.

    `threading.Semaphore` is created with a fixed value, so changing how many
    transfers run at once — from the UI, without restarting anything — means
    keeping the count by hand. Lowering the limit never interrupts transfers
    that already started: they run to completion, and the new ceiling takes
    effect as slots are released.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            msg = "limit must be at least 1"
            raise ValueError(msg)
        self._cond = threading.Condition()
        self._limit = limit
        self._active = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    def set_limit(self, limit: int) -> None:
        if limit < 1:
            msg = "limit must be at least 1"
            raise ValueError(msg)
        with self._cond:
            self._limit = limit
            self._cond.notify_all()

    def acquire(self) -> None:
        with self._cond:
            while self._active >= self._limit:
                self._cond.wait()
            self._active += 1

    def release(self) -> None:
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify()

    def __enter__(self) -> Limiter:
        self.acquire()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, tb: TracebackType | None) -> None:
        self.release()
