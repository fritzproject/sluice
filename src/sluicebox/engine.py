"""The core: queue, throughput, retries, resuming and source re-checks."""

from __future__ import annotations

import itertools
import logging
import queue
import random
import threading
import time
import uuid
from typing import Any

import requests

from sluicebox import extractors
from sluicebox.config import Config, Settings
from sluicebox.downloader import download
from sluicebox.extractors.base import Context
from sluicebox.limiter import Limiter
from sluicebox.naming import Layout
from sluicebox.store import Store

logger = logging.getLogger(__name__)

#: Threads standing by to pick up a source. How many actually work at once is
#: decided by the limiter, which can be adjusted at runtime.
SOURCE_WORKERS = 16
#: The timeout covers inspecting a source only, never a transfer: a large file
#: is slow by nature, and that is not a stall.
INSPECT_TIMEOUT = 120

TERMINAL_ITEM_STATES = {"done"}
ACTIVE_JOB_STATES = {"queued", "preparing", "running"}


class Engine:
    """Coordinates extractors, the queue and the transfers.

    It does three things that sound obvious and are almost always missing:
    resumes an interrupted transfer instead of throwing it away, refuses to
    call a job finished while parts of it are still pending, and survives a
    restart without losing the queue.
    """

    def __init__(self, config: Config | None = None, settings: Settings | None = None) -> None:
        self.config = config or Config()
        self.settings = settings or Settings()
        self.store = Store(self.config.state_dir / "state.json")

        self.jobs: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.watches: dict[str, dict[str, Any]] = {}

        self._queue: queue.Queue[str] = queue.Queue()
        self._transfer_slots = Limiter(self.settings.concurrent_transfers)
        self._source_slots = Limiter(self.settings.parallel_sources)
        self._proxies = itertools.cycle(self.config.proxies) if self.config.proxies else None
        self._proxy_lock = threading.Lock()
        self._started = False

    # ---------------------------------------------------------------- startup
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        extractors.load_plugins()
        self._restore()
        for _ in range(SOURCE_WORKERS):
            threading.Thread(target=self._source_worker, daemon=True).start()
        threading.Thread(target=self._recheck_worker, daemon=True).start()

    def _restore(self) -> None:
        data = self.store.load()
        self.jobs = data.get("jobs", {})
        self.order = data.get("order", [])
        self.watches = data.get("watches", {})
        if saved := data.get("settings"):
            try:
                self.settings.update(saved)
            except ValueError:
                logger.warning("Saved settings are invalid, using the initial values")
        self.apply_settings()

        # Any job with unfinished items is resumed, not just the ones that were
        # marked as running: a restart can leave a job flagged as finished with
        # items still pending, and without this check it would sit there
        # forever with nobody looking at it again.
        resumed = 0
        for job_id in self.order:
            job = self.jobs.get(job_id)
            if not job:
                continue
            pending = [key for key, state in job.get("items", {}).items()
                       if state.get("status") not in TERMINAL_ITEM_STATES]
            for key in pending:
                job["items"][key].update({"status": "queued", "speed": 0})
            if pending or job.get("status") in ACTIVE_JOB_STATES:
                job["requested"] = pending or job.get("requested", [])
                job["status"] = "queued"
                self._queue.put(job_id)
                resumed += 1
        if resumed:
            logger.info("Resumed %d jobs from saved state", resumed)

    def apply_settings(self) -> None:
        self._transfer_slots.set_limit(self.settings.concurrent_transfers)
        self._source_slots.set_limit(self.settings.parallel_sources)

    def save(self) -> None:
        self.store.save({"jobs": self.jobs, "order": self.order,
                         "watches": self.watches, "settings": self.settings.as_dict()})

    # ---------------------------------------------------------------- network
    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": self.config.user_agent})
        if self._proxies:
            with self._proxy_lock:
                proxy = next(self._proxies)
            session.proxies.update({"http": proxy, "https": proxy})
        return session

    # -------------------------------------------------------------------- API
    def inspect(self, url: str) -> dict[str, Any]:
        """Look at what is behind a URL without downloading anything."""
        extractor_cls = extractors.find(url)
        if not extractor_cls:
            msg = "no extractor can handle this URL"
            raise ValueError(msg)
        ctx = Context(session=self._session(), timeout=self.config.timeout)
        extractor = extractor_cls()
        source = extractor.inspect(url, ctx)
        items = extractor.items(url, ctx)
        return {
            "extractor": extractor_cls.name,
            "title": source.title,
            "kind": source.kind,
            "ongoing": source.ongoing,
            "items": [{"key": i.key, "title": i.title, "index": i.index} for i in items],
        }

    def submit(self, url: str, item_keys: list[str] | None = None, *,
               title: str | None = None, layout: dict | None = None,
               watch: bool = False) -> str:
        extractor_cls = extractors.find(url)
        if not extractor_cls:
            msg = "no extractor can handle this URL"
            raise ValueError(msg)

        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = {
            "id": job_id,
            "url": url,
            "extractor": extractor_cls.name,
            # The title is already known at submit time: storing it right away
            # avoids showing anonymous jobs until they are picked up, which is
            # exactly when someone wants to know what they are.
            "title": title,
            "status": "queued",
            "items": {},
            "requested": item_keys or [],
            "layout": layout or {},
            "created": time.time(),
        }
        self.order.append(job_id)
        if watch:
            self.watch(url, layout=layout, known=len(item_keys or []))
        self._queue.put(job_id)
        self.save()
        return job_id

    def retry(self, job_id: str) -> int:
        job = self.jobs.get(job_id)
        if not job:
            msg = "unknown job"
            raise KeyError(msg)
        pending = self.incomplete(job)
        if not pending:
            return 0
        job["requested"] = pending
        job["status"] = "queued"
        self._queue.put(job_id)
        self.save()
        return len(pending)

    def retry_all(self) -> dict[str, int]:
        """Re-queue everything still missing, across every idle job."""
        jobs = items = 0
        for job_id in list(self.order):
            count = self.retry(job_id) if self.jobs.get(job_id) else 0
            if count:
                jobs += 1
                items += count
        return {"jobs": jobs, "items": items}

    @staticmethod
    def incomplete(job: dict) -> list[str]:
        """Items worth recovering: failed, or left half-done."""
        if job.get("status") in ACTIVE_JOB_STATES:
            return []   # already being worked on: leave it alone
        return [key for key, state in job.get("items", {}).items()
                if state.get("status") not in TERMINAL_ITEM_STATES]

    # ---------------------------------------------------------------- sources
    def watch(self, url: str, *, layout: dict | None = None, known: int = 0) -> str:
        for watch_id, existing in self.watches.items():
            if existing["url"] == url:
                existing.update({"enabled": True, "layout": layout or existing.get("layout")})
                self.save()
                return watch_id
        watch_id = uuid.uuid4().hex[:8]
        self.watches[watch_id] = {
            "id": watch_id, "url": url, "title": None, "layout": layout or {},
            # From here on: whatever is already there is not downloaded again.
            "known": known, "enabled": True, "added": time.time(),
            "last_check": None, "last_new": None,
        }
        self.save()
        return watch_id

    def unwatch(self, watch_id: str) -> bool:
        removed = self.watches.pop(watch_id, None) is not None
        if removed:
            self.save()
        return removed

    def check_watches(self) -> list[dict]:
        found = []
        for watch in list(self.watches.values()):
            if not watch.get("enabled", True):
                continue
            try:
                info = self.inspect(watch["url"])
                watch["title"] = info["title"]
                watch["last_check"] = time.time()
                items = info["items"]
                known = int(watch.get("known") or 0)

                if len(items) > known:
                    new_items = items[known:]
                    job_id = self.submit(watch["url"], [i["key"] for i in new_items],
                                         title=info["title"], layout=watch.get("layout"))
                    watch["known"] = len(items)
                    watch["last_new"] = {"when": time.time(),
                                         "count": len(new_items), "job": job_id}
                    found.append({"watch": watch["id"], "title": info["title"],
                                  "new": len(new_items)})
                elif not info["ongoing"]:
                    # Collection closed and nothing new: stop polling the source
                    # for the rest of time, which is what would happen otherwise.
                    watch["enabled"] = False
                    watch["closed"] = "collection complete"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Re-check failed for %s: %s", watch["url"], exc)
                watch["last_error"] = str(exc)[:120]
            self.save()
        return found

    def _recheck_worker(self) -> None:
        while True:
            time.sleep(self.settings.recheck_interval_seconds)
            try:
                self.check_watches()
            except Exception:  # noqa: BLE001
                logger.exception("Error while re-checking sources")

    # -------------------------------------------------------------- execution
    def _source_worker(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id in self.jobs:
                    with self._source_slots:
                        self._run(job_id)
            except BaseException:  # noqa: BLE001
                # Not even a SystemExit raised by some library may kill this
                # worker: if it dies, the queue stops silently.
                logger.exception("Unhandled error on job %s", job_id)
            finally:
                self._queue.task_done()

    def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job["status"] = "preparing"
        self.save()

        extractor_cls = extractors.find(job["url"])
        if not extractor_cls:
            job.update({"status": "failed", "error": "extractor no longer available"})
            self.save()
            return
        extractor = extractor_cls()

        try:
            result: dict = {}
            done = threading.Event()

            def prepare() -> None:
                try:
                    ctx = Context(session=self._session(), timeout=self.config.timeout)
                    result["source"] = extractor.inspect(job["url"], ctx)
                    result["items"] = extractor.items(job["url"], ctx)
                except Exception as exc:  # noqa: BLE001
                    result["error"] = exc
                finally:
                    done.set()

            threading.Thread(target=prepare, daemon=True).start()
            if not done.wait(INSPECT_TIMEOUT):
                job.update({"status": "failed",
                            "error": f"source did not answer within {INSPECT_TIMEOUT}s"})
                self.save()
                return
            if "error" in result:
                raise result["error"]

            source, all_items = result["source"], result["items"]
            job["title"] = source.title
            wanted = set(job.get("requested") or [])
            selected = [i for i in all_items if not wanted or i.key in wanted]

            for item in selected:
                job["items"].setdefault(item.key, {
                    "title": item.title, "index": item.index,
                    "status": "queued", "bytes": 0, "total": 0, "speed": 0, "error": None})
            job["status"] = "running"
            self.save()

            pending: queue.Queue = queue.Queue()
            for item in selected:
                if job["items"][item.key]["status"] not in TERMINAL_ITEM_STATES:
                    pending.put(item)

            # As many threads as permitted transfers, not one per item: with a
            # collection of hundreds of files the rest would sit blocked anyway,
            # while still taking memory away from the other sources in flight.
            worker_count = max(1, min(pending.qsize(), self.settings.concurrent_transfers))
            threads = [
                threading.Thread(target=self._item_worker,
                                 args=(job_id, extractor, source, pending), daemon=True)
                for _ in range(worker_count)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self._finalize(job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job %s failed", job_id)
            job.update({"status": "failed", "error": str(exc)[:160]})
        finally:
            self.save()

    def _item_worker(self, job_id: str, extractor: Any, source: Any,
                     pending: queue.Queue) -> None:
        job = self.jobs[job_id]
        # Without an explicit scheme, pick one from the source: a single file
        # must not be buried in a folder carrying its own name.
        layout = (Layout(**job["layout"]) if job.get("layout")
                  else Layout.for_single_file() if source.kind == "file"
                  else Layout())
        while True:
            try:
                item = pending.get_nowait()
            except queue.Empty:
                return
            try:
                self._transfer(job, extractor, source, item, layout)
            except Exception:  # noqa: BLE001
                logger.exception("Unhandled error on item %s", item.key)
            finally:
                pending.task_done()

    def _transfer(self, job: dict, extractor: Any, source: Any,
                  item: Any, layout: Layout) -> None:
        state = job["items"][item.key]
        with self._transfer_slots:
            pause = random.uniform(self.settings.pacing_min_seconds,  # noqa: S311
                                   self.settings.pacing_max_seconds)
            if pause:
                time.sleep(pause)

            for attempt in range(1, self.settings.max_retries + 1):
                session = self._session()
                ctx = Context(session=session, timeout=self.config.timeout)
                try:
                    state["status"] = "transferring" if attempt == 1 else f"retry {attempt}"
                    # Resolving and downloading share one session: if the source
                    # signs the link against whoever asked for it, splitting the
                    # two would get the transfer refused.
                    target = extractor.resolve(item, ctx)
                    destination = layout.build(
                        self.config.download_root, source=source.title,
                        title=item.title, index=item.index, suggested=target.filename)

                    def report(progress: Any, state: dict = state) -> None:
                        state.update({"bytes": progress.downloaded,
                                      "total": progress.total, "speed": progress.speed})

                    download(target, destination, session,
                             timeout=self.config.timeout, on_progress=report)
                    state.update({"status": "done", "speed": 0, "error": None,
                                  "path": str(destination)})
                    if target.metadata:
                        # Licence and attribution travel with the item: most
                        # free licences require crediting the author.
                        state["metadata"] = target.metadata
                    self.save()
                    return
                except Exception as exc:  # noqa: BLE001
                    state["error"] = self._short_error(exc)
                    logger.warning("%s: attempt %d/%d failed (%s)",
                                   item.title, attempt, self.settings.max_retries, exc)
                    if attempt == self.settings.max_retries:
                        state.update({"status": "failed", "speed": 0})
                        self.save()
                        return
                    time.sleep(min(60, 5 * 2 ** (attempt - 1)))

    @staticmethod
    def _short_error(exc: Exception) -> str:
        """Compact message for the interface; the rest stays in the log."""
        response = getattr(exc, "response", None)
        if response is not None:
            return f"HTTP {response.status_code}"
        if isinstance(exc, requests.Timeout):
            return "network timeout"
        if isinstance(exc, requests.ConnectionError):
            return "connection dropped"
        return str(exc)[:80]

    @staticmethod
    def _finalize(job: dict) -> None:
        states = [i["status"] for i in job["items"].values()]
        done = states.count("done")
        failed = states.count("failed")
        pending = len(states) - done - failed
        # A job with items still pending is not "done": saying otherwise is the
        # surest way to lose track of them for good.
        if pending:
            job["status"] = "interrupted"
        elif failed and done:
            job["status"] = "partial"
        elif failed:
            job["status"] = "failed"
        else:
            job["status"] = "done"

    # ---------------------------------------------------------------- summary
    def snapshot(self) -> dict[str, Any]:
        jobs = [self.jobs[j] for j in self.order if j in self.jobs]
        speed = sum(i.get("speed") or 0 for job in jobs
                    for i in job.get("items", {}).values()
                    if i.get("status") == "transferring")
        active = sum(1 for job in jobs for i in job.get("items", {}).values()
                     if i.get("status") == "transferring")
        failed = sum(1 for job in jobs for i in job.get("items", {}).values()
                     if i.get("status") == "failed")
        return {
            "jobs": jobs,
            "watches": list(self.watches.values()),
            "summary": {
                "speed": speed,
                "active": active,
                "failed": failed,
                "recoverable": sum(len(self.incomplete(job)) for job in jobs),
                "queued": sum(1 for job in jobs if job["status"] == "queued"),
                "sources_running": self._source_slots.active,
                "settings": self.settings.as_dict(),
                "proxies": len(self.config.proxies),
            },
        }
