"""Core behaviour: throughput, naming, resuming, final status."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from sluice.downloader import download
from sluice.engine import Engine
from sluice.limiter import Limiter
from sluice.models import Target
from sluice.naming import Layout, sanitize


# ------------------------------------------------------------------- limiter
def test_limiter_blocks_past_the_ceiling() -> None:
    limiter = Limiter(1)
    limiter.acquire()
    entered = threading.Event()

    threading.Thread(target=lambda: (limiter.acquire(), entered.set()), daemon=True).start()
    assert not entered.wait(0.2), "the second one must not pass with a ceiling of 1"

    limiter.release()
    assert entered.wait(1), "once a slot is freed the second one must pass"


def test_limiter_widens_at_runtime() -> None:
    """Raising the ceiling must immediately release whoever was waiting."""
    limiter = Limiter(1)
    limiter.acquire()
    entered = threading.Event()

    threading.Thread(target=lambda: (limiter.acquire(), entered.set()), daemon=True).start()
    time.sleep(0.1)
    assert not entered.is_set()

    limiter.set_limit(2)
    assert entered.wait(1), "raising the ceiling should unblock the waiter"


def test_limiter_rejects_invalid_ceilings() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        Limiter(0)


# -------------------------------------------------------------------- naming
@pytest.mark.parametrize(("raw", "expected"), [
    ("Title: with a colon", "Title with a colon"),
    ("a/b\\c", "abc"),
    ("   double    spaces   ", "double spaces"),
    ("...", "unnamed"),
])
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize(raw) == expected


def test_layout_numbers_and_groups(tmp_path: Path) -> None:
    path = Layout().build(tmp_path, source="The Collection", title="First piece",
                          index=3, suggested="whatever.mp3")
    assert path == tmp_path / "The Collection" / "03 - First piece.mp3"


def test_layout_single_file_gets_no_subfolder(tmp_path: Path) -> None:
    """One file must not be buried in a folder named after itself."""
    path = Layout.for_single_file().build(
        tmp_path, source="README.md", title="README.md", index=1, suggested="README.md")
    assert path == tmp_path / "README.md"


def test_layout_media_library_scheme(tmp_path: Path) -> None:
    layout = Layout(folder="{source}", filename="{source} S01E{index:02d}{ext}")
    path = layout.build(tmp_path, source="Series", title="ignored",
                        index=7, suggested="x.mkv")
    assert path.name == "Series S01E07.mkv"


# ------------------------------------------------------------------ resuming
class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        self.body = body
        self.status_code = status
        self.headers = headers or {"content-length": str(len(body))}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = f"HTTP {self.status_code}"
            raise RuntimeError(msg)

    def iter_content(self, chunk_size: int = 0):  # noqa: ANN201, ARG002
        yield self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeSession:
    """A session that answers range requests the way a CDN would."""

    def __init__(self, content: bytes, *, accepts_range: bool = True) -> None:
        self.content = content
        self.accepts_range = accepts_range
        self.requests: list[dict] = []

    def get(self, url: str, **kwargs) -> FakeResponse:  # noqa: ANN003, ARG002
        headers = kwargs.get("headers") or {}
        self.requests.append(headers)
        wanted = headers.get("Range")
        if wanted and self.accepts_range:
            start = int(wanted.split("=")[1].split("-")[0])
            rest = self.content[start:]
            return FakeResponse(rest, status=206, headers={"content-length": str(len(rest))})
        return FakeResponse(self.content)


def test_download_complete(tmp_path: Path) -> None:
    session = FakeSession(b"0123456789")
    destination = tmp_path / "file.bin"
    download(Target(url="http://x/file.bin", filename="file.bin"), destination, session)
    assert destination.read_bytes() == b"0123456789"
    assert not (tmp_path / "file.bin.part").exists(), "the .part must be gone when finished"


def test_download_resumes_where_it_stopped(tmp_path: Path) -> None:
    """What was already fetched must not be thrown away."""
    destination = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(b"01234")   # interrupted half-way

    session = FakeSession(b"0123456789")
    download(Target(url="http://x/file.bin", filename="file.bin"), destination, session)

    assert destination.read_bytes() == b"0123456789"
    assert session.requests[0].get("Range") == "bytes=5-"


def test_download_restarts_when_server_ignores_range(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(b"01234")

    session = FakeSession(b"0123456789", accepts_range=False)
    download(Target(url="http://x/file.bin", filename="file.bin"), destination, session)

    assert destination.read_bytes() == b"0123456789", "no duplicated bytes at the head"


def test_download_skips_files_already_there(tmp_path: Path) -> None:
    destination = tmp_path / "file.bin"
    destination.write_bytes(b"already here")
    session = FakeSession(b"new content")

    download(Target(url="http://x/file.bin", filename="file.bin"), destination, session)

    assert destination.read_bytes() == b"already here"
    assert session.requests == [], "it should not even have asked"


# -------------------------------------------------------------- final status
@pytest.mark.parametrize(("states", "expected"), [
    (["done", "done"], "done"),
    (["done", "failed"], "partial"),
    (["failed", "failed"], "failed"),
    # The one that matters: calling a job finished while parts of it are still
    # pending is the surest way to lose track of them for good.
    (["done", "queued"], "interrupted"),
    (["done", "transferring"], "interrupted"),
])
def test_final_status(states: list[str], expected: str) -> None:
    job = {"items": {str(n): {"status": s} for n, s in enumerate(states)}}
    Engine._finalize(job)  # noqa: SLF001
    assert job["status"] == expected


# ----------------------------------------------------------- configuration
def test_cli_flags_do_not_shadow_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitted flags must leave the environment in charge.

    When the flags defaulted to "./downloads" and "./state" they were passed
    unconditionally, silently overriding SLUICE_DOWNLOAD_ROOT and
    SLUICE_STATE_DIR — which is how a container ends up writing its queue into
    a working directory it has no permission on.
    """
    import argparse

    from sluice.cli import _config

    monkeypatch.setenv("SLUICE_DOWNLOAD_ROOT", "/downloads")
    monkeypatch.setenv("SLUICE_STATE_DIR", "/state")

    from_env = _config(argparse.Namespace(output=None, state=None))
    assert from_env.download_root == Path("/downloads")
    assert from_env.state_dir == Path("/state")

    explicit = _config(argparse.Namespace(output="/tmp/elsewhere", state=None))
    assert explicit.download_root == Path("/tmp/elsewhere"), "an explicit flag still wins"
    assert explicit.state_dir == Path("/state")


def test_incomplete_leaves_running_jobs_alone() -> None:
    job = {"status": "running", "items": {"a": {"status": "failed"}}}
    assert Engine.incomplete(job) == [], "a running job must not be touched"

    job["status"] = "interrupted"
    assert Engine.incomplete(job) == ["a"]
