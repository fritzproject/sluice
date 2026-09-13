"""Il nucleo: coda, portata, tentativi, ripresa e ricontrollo delle sorgenti."""

from __future__ import annotations

import itertools
import logging
import queue
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from sluice import extractors
from sluice.config import Config, Settings
from sluice.downloader import download
from sluice.extractors.base import Context
from sluice.limiter import Limiter
from sluice.naming import Layout
from sluice.store import Store

logger = logging.getLogger(__name__)

#: Quanti thread tengo pronti a prendere una sorgente. Quante ne lavorino
#: davvero insieme lo decide il limitatore, che si regola a caldo.
SOURCE_WORKERS = 16
#: Il timeout vale solo per l'ispezione della sorgente, mai per il
#: trasferimento: un file grande e' lento per natura, non e' un blocco.
INSPECT_TIMEOUT = 120

TERMINAL_ITEM_STATES = {"done"}
ACTIVE_JOB_STATES = {"queued", "preparing", "running"}


class Engine:
    """Coordina estrattori, coda e trasferimenti.

    Sa fare tre cose che sembrano ovvie ma che quasi sempre mancano: riprendere
    un trasferimento interrotto invece di ributtarlo via, non dichiarare finito
    un lavoro che ha ancora pezzi in sospeso, e sopravvivere a un riavvio senza
    perdere la coda.
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

    # ------------------------------------------------------------------ avvio
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
                logger.warning("Impostazioni salvate non valide, uso i valori iniziali")
        self.apply_settings()

        # Si riprende qualunque lavoro con elementi non conclusi, non solo
        # quelli che risultavano in corso: un riavvio puo' averne lasciato uno
        # marcato come finito con dei pezzi ancora in sospeso, e senza questo
        # controllo resterebbe fermo per sempre.
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
            logger.info("Ripresi %d lavori dallo stato salvato", resumed)

    def apply_settings(self) -> None:
        self._transfer_slots.set_limit(self.settings.concurrent_transfers)
        self._source_slots.set_limit(self.settings.parallel_sources)

    def save(self) -> None:
        self.store.save({"jobs": self.jobs, "order": self.order,
                         "watches": self.watches, "settings": self.settings.as_dict()})

    # ------------------------------------------------------------------ rete
    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": self.config.user_agent})
        if self._proxies:
            with self._proxy_lock:
                proxy = next(self._proxies)
            session.proxies.update({"http": proxy, "https": proxy})
        return session

    # ------------------------------------------------------------------ API
    def inspect(self, url: str) -> dict[str, Any]:
        """Guarda cosa c'e' a quell'URL, senza scaricare niente."""
        extractor_cls = extractors.find(url)
        if not extractor_cls:
            msg = "nessun estrattore sa gestire questo URL"
            raise ValueError(msg)
        session = self._session()
        ctx = Context(session=session, timeout=self.config.timeout)
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
            msg = "nessun estrattore sa gestire questo URL"
            raise ValueError(msg)

        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = {
            "id": job_id,
            "url": url,
            "extractor": extractor_cls.name,
            # Il titolo si conosce gia' al momento dell'invio: salvarlo subito
            # evita di mostrare lavori anonimi finche' non vengono presi in
            # carico, che e' esattamente quando l'utente vuole sapere cosa sono.
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
            msg = "lavoro sconosciuto"
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
        """Rimette in coda tutto cio' che manca, su ogni lavoro fermo."""
        jobs = items = 0
        for job_id in list(self.order):
            count = self.retry(job_id) if self.jobs.get(job_id) else 0
            if count:
                jobs += 1
                items += count
        return {"jobs": jobs, "items": items}

    @staticmethod
    def incomplete(job: dict) -> list[str]:
        """Elementi da recuperare: falliti o rimasti a meta'."""
        if job.get("status") in ACTIVE_JOB_STATES:
            return []   # gia' in lavorazione: non si tocca
        return [key for key, state in job.get("items", {}).items()
                if state.get("status") not in TERMINAL_ITEM_STATES]

    # -------------------------------------------------------------- sorgenti
    def watch(self, url: str, *, layout: dict | None = None, known: int = 0) -> str:
        for watch_id, existing in self.watches.items():
            if existing["url"] == url:
                existing.update({"enabled": True, "layout": layout or existing.get("layout")})
                self.save()
                return watch_id
        watch_id = uuid.uuid4().hex[:8]
        self.watches[watch_id] = {
            "id": watch_id, "url": url, "title": None, "layout": layout or {},
            # Da qui in poi: quello che c'e' gia' non si riscarica.
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
                    # Raccolta chiusa e niente di nuovo: smettiamo di
                    # interrogare la sorgente a vuoto per sempre.
                    watch["enabled"] = False
                    watch["closed"] = "raccolta completa"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ricontrollo fallito per %s: %s", watch["url"], exc)
                watch["last_error"] = str(exc)[:120]
            self.save()
        return found

    def _recheck_worker(self) -> None:
        while True:
            time.sleep(self.settings.recheck_interval_seconds)
            try:
                self.check_watches()
            except Exception:  # noqa: BLE001
                logger.exception("Errore nel ricontrollo delle sorgenti")

    # ---------------------------------------------------------- esecuzione
    def _source_worker(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id in self.jobs:
                    with self._source_slots:
                        self._run(job_id)
            except BaseException:  # noqa: BLE001
                # Nemmeno un SystemExit sollevato da una libreria deve poter
                # uccidere il worker: se muore, la coda si ferma in silenzio.
                logger.exception("Errore non gestito sul lavoro %s", job_id)
            finally:
                self._queue.task_done()

    def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job["status"] = "preparing"
        self.save()

        extractor_cls = extractors.find(job["url"])
        if not extractor_cls:
            job.update({"status": "failed", "error": "estrattore non disponibile"})
            self.save()
            return
        extractor = extractor_cls()

        try:
            result: dict = {}
            done = threading.Event()

            def prepare() -> None:
                try:
                    session = self._session()
                    ctx = Context(session=session, timeout=self.config.timeout)
                    result["source"] = extractor.inspect(job["url"], ctx)
                    result["items"] = extractor.items(job["url"], ctx)
                except Exception as exc:  # noqa: BLE001
                    result["error"] = exc
                finally:
                    done.set()

            threading.Thread(target=prepare, daemon=True).start()
            if not done.wait(INSPECT_TIMEOUT):
                job.update({"status": "failed",
                            "error": f"la sorgente non risponde entro {INSPECT_TIMEOUT}s"})
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

            # Tanti thread quanti i trasferimenti consentiti, non uno per
            # elemento: con una raccolta da centinaia di file gli altri
            # resterebbero comunque fermi, e intanto occuperebbero memoria
            # sottraendo spazio alle altre sorgenti in lavorazione.
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
            logger.exception("Lavoro %s fallito", job_id)
            job.update({"status": "failed", "error": str(exc)[:160]})
        finally:
            self.save()

    def _item_worker(self, job_id: str, extractor: Any, source: Any,
                     pending: queue.Queue) -> None:
        job = self.jobs[job_id]
        # Senza uno schema esplicito si sceglie in base alla sorgente: un file
        # singolo non va infilato in una cartella che porta il suo stesso nome.
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
                logger.exception("Elemento %s non gestito", item.key)
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
                    # Risoluzione e scaricamento condividono la sessione: se la
                    # sorgente firma il collegamento legandolo a chi lo chiede,
                    # separarli lo farebbe rifiutare.
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
                    self.save()
                    return
                except Exception as exc:  # noqa: BLE001
                    state["error"] = self._short_error(exc)
                    logger.warning("%s: tentativo %d/%d fallito (%s)",
                                   item.title, attempt, self.settings.max_retries, exc)
                    if attempt == self.settings.max_retries:
                        state.update({"status": "failed", "speed": 0})
                        self.save()
                        return
                    time.sleep(min(60, 5 * 2 ** (attempt - 1)))

    @staticmethod
    def _short_error(exc: Exception) -> str:
        """Messaggio compatto per l'interfaccia: il resto sta nel registro."""
        response = getattr(exc, "response", None)
        if response is not None:
            return f"HTTP {response.status_code}"
        if isinstance(exc, requests.Timeout):
            return "timeout di rete"
        if isinstance(exc, requests.ConnectionError):
            return "connessione interrotta"
        return str(exc)[:80]

    @staticmethod
    def _finalize(job: dict) -> None:
        states = [i["status"] for i in job["items"].values()]
        done = states.count("done")
        failed = states.count("failed")
        pending = len(states) - done - failed
        # Un lavoro con pezzi ancora in sospeso non e' "finito": dichiararlo
        # tale e' il modo piu' semplice per perderli di vista per sempre.
        if pending:
            job["status"] = "interrupted"
        elif failed and done:
            job["status"] = "partial"
        elif failed:
            job["status"] = "failed"
        else:
            job["status"] = "done"

    # ------------------------------------------------------------- riepilogo
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
