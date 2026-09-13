"""State persistence: the queue survives restarts and upgrades."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Store:
    """A JSON snapshot of the state, written atomically.

    Writes go to a temporary file which is then moved over the real one: if
    the process dies mid-write, the previous state stays intact instead of
    becoming a truncated, unreadable file.
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
            # Unreadable state: better to start clean than to refuse to start.
            logger.exception("State at %s is unreadable, ignoring it", self.path)
            return {}

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                logger.exception("Could not save state to %s", self.path)
