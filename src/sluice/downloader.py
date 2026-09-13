"""Downloading one file, resuming from wherever it was interrupted."""

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
    """Download `target` into `destination`, resuming where possible.

    The file grows under a ``.part`` suffix and is renamed only once the
    transfer completes, so whatever watches the folder — a media server, a
    script — never sees a half-written file and mistakes it for a finished one.

    If a ``.part`` is already there, only the missing range is requested. Not
    every server honours range requests: when one answers 200 instead of 206
    the download simply restarts from the beginning rather than failing.
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
            logger.info("Resume refused for %s: starting over", destination.name)

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
