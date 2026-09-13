"""HTTP API and web interface."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Flask, jsonify, request, send_from_directory

from sluice import extractors
from sluice.engine import Engine

if TYPE_CHECKING:
    from sluice.config import Config, Settings

STATIC_DIR = "static"


def create_app(engine: Engine | None = None, *, config: Config | None = None,
               settings: Settings | None = None) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR)
    app.engine = engine or Engine(config=config, settings=settings)  # type: ignore[attr-defined]
    app.engine.start()  # type: ignore[attr-defined]

    def core() -> Engine:
        return app.engine  # type: ignore[attr-defined,no-any-return]

    @app.after_request
    def cors(response):  # noqa: ANN001, ANN202
        # The interface may be served from a different origin (a browser
        # extension, an external panel): without these headers the call would
        # be blocked.
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE"
        return response

    @app.get("/")
    def index():  # noqa: ANN202
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/extractors")
    def list_extractors():  # noqa: ANN202
        return jsonify([{"name": e.name, "description": e.description}
                        for e in extractors.available()])

    @app.post("/api/inspect")
    def inspect():  # noqa: ANN202
        url = (request.json or {}).get("url", "").strip()
        if not url:
            return jsonify({"error": "missing URL"}), 400
        try:
            return jsonify(core().inspect(url))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)[:160]}), 502

    @app.post("/api/jobs")
    def create_job():  # noqa: ANN202
        data = request.json or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "missing URL"}), 400
        try:
            job_id = core().submit(
                url, data.get("items"), title=data.get("title"),
                layout=data.get("layout"), watch=bool(data.get("watch")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job": job_id})

    @app.get("/api/jobs")
    def list_jobs():  # noqa: ANN202
        return jsonify(core().snapshot())

    @app.post("/api/jobs/<job_id>/retry")
    def retry(job_id: str):  # noqa: ANN202
        try:
            return jsonify({"requeued": core().retry(job_id)})
        except KeyError:
            return jsonify({"error": "unknown job"}), 404

    @app.post("/api/retry-all")
    def retry_all():  # noqa: ANN202
        return jsonify(core().retry_all())

    @app.get("/api/watches")
    def list_watches():  # noqa: ANN202
        return jsonify({"watches": list(core().watches.values()),
                        "interval": core().settings.recheck_interval_seconds})

    @app.post("/api/watches")
    def add_watch():  # noqa: ANN202
        data = request.json or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "missing URL"}), 400
        try:
            info = core().inspect(url)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)[:160]}), 502
        # Without "include existing" the starting point is what is already
        # published: only future items will be fetched.
        known = 0 if data.get("include_existing") else len(info["items"])
        watch_id = core().watch(url, layout=data.get("layout"), known=known)
        core().watches[watch_id]["title"] = info["title"]
        core().save()
        return jsonify({"watch": watch_id, "title": info["title"],
                        "ongoing": info["ongoing"], "known": known})

    @app.post("/api/watches/check")
    def check_watches():  # noqa: ANN202
        return jsonify({"found": core().check_watches()})

    @app.delete("/api/watches/<watch_id>")
    def remove_watch(watch_id: str):  # noqa: ANN202
        if not core().unwatch(watch_id):
            return jsonify({"error": "source is not watched"}), 404
        return jsonify({"removed": watch_id})

    @app.get("/api/settings")
    def get_settings():  # noqa: ANN202
        from sluice.config import BOUNDS
        return jsonify({"settings": core().settings.as_dict(), "bounds": BOUNDS})

    @app.post("/api/settings")
    def update_settings():  # noqa: ANN202
        try:
            applied = core().settings.update(request.json or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        core().apply_settings()   # takes effect at once, no restart
        core().save()
        return jsonify({"settings": core().settings.as_dict(), "applied": applied})

    return app
