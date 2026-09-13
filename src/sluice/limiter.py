"""Limitatore di portata ridimensionabile mentre il lavoro e' gia' in corso."""

from __future__ import annotations

import threading
from types import TracebackType


class Limiter:
    """Semaforo il cui tetto si puo' alzare o abbassare a caldo.

    `threading.Semaphore` nasce con un valore fisso: per poter cambiare i
    trasferimenti simultanei da interfaccia, senza riavviare nulla, il conto va
    tenuto a mano. Abbassando il limite i trasferimenti in corso proseguono
    fino alla fine: si rientra nel nuovo tetto man mano che finiscono, invece
    di interromperli a meta'.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            msg = "il limite deve essere almeno 1"
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
            msg = "il limite deve essere almeno 1"
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
