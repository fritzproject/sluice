"""Scaricamento di un singolo file, con ripresa da dove si era interrotto."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import requests

    from sluice.models import Target

logger = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024
PARTIAL_SUFFIX = ".part"
HTTP_PARTIAL_CONTENT = 206


@dataclass
class Progress:
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    resumed_from: int = 0


ProgressCallback = Callable[[Progress], None]


def download(
    target: Target,
    destination: Path,
    session: requests.Session,
    *,
    timeout: int = 30,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Scarica `target` in `destination`, riprendendo se possibile.

    Il file cresce con il suffisso ``.part`` e viene rinominato solo a
    trasferimento concluso: chi guarda la cartella (un server multimediale,
    uno script) non vede mai un file incompleto come se fosse buono.

    Se un ``.part`` esiste gia' si chiede al server la parte mancante. Non
    tutti i server accettano le richieste parziali: se risponde 200 invece di
    206 si riparte da zero, senza fallire.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    partial = destination.with_name(destination.name + PARTIAL_SUFFIX)
    resume_from = partial.stat().st_size if partial.exists() else 0

    headers = dict(target.headers)
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"

    with session.get(target.url, stream=True, timeout=timeout, headers=headers) as response:
        response.raise_for_status()
        resuming = resume_from > 0 and response.status_code == HTTP_PARTIAL_CONTENT
        if resume_from and not resuming:
            logger.info("Ripresa non accettata per %s: riparto da capo", destination.name)

        progress = Progress(
            downloaded=resume_from if resuming else 0,
            total=int(response.headers.get("content-length", 0)) + (resume_from if resuming else 0),
            resumed_from=resume_from if resuming else 0,
        )
        if on_progress:
            on_progress(progress)

        last_time = time.monotonic()
        last_bytes = progress.downloaded
        with partial.open("ab" if resuming else "wb") as handle:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                handle.write(chunk)
                progress.downloaded += len(chunk)

                now = time.monotonic()
                elapsed = now - last_time
                if elapsed >= 1:
                    progress.speed = (progress.downloaded - last_bytes) / elapsed
                    last_time, last_bytes = now, progress.downloaded
                    if on_progress:
                        on_progress(progress)

    progress.speed = 0.0
    partial.replace(destination)
    if on_progress:
        on_progress(progress)
    return destination
