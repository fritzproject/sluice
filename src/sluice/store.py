"""Persistenza dello stato: la coda sopravvive a riavvii e aggiornamenti."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Store:
    """Istantanea dello stato su file JSON, scritta in modo atomico.

    Si scrive su un file temporaneo e lo si sposta sopra quello buono: se il
    processo muore a meta' scrittura, lo stato precedente resta integro invece
    di diventare un file troncato e illeggibile.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Stato illeggibile: meglio ripartire puliti che non partire.
            logger.exception("Stato non leggibile in %s, lo ignoro", self.path)
            return {}

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                logger.exception("Impossibile salvare lo stato in %s", self.path)
