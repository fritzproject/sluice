"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from sluicebox import __version__, extractors
from sluicebox.config import Config, Settings
from sluicebox.engine import Engine


def _config(args: argparse.Namespace) -> Config:
    """Command line beats the environment, which beats the defaults.

    The flags must default to None for this to work: passing their value
    unconditionally would silently override SLUICEBOX_DOWNLOAD_ROOT and
    SLUICEBOX_STATE_DIR, which is exactly how a container ends up trying to write
    its queue into a read-only working directory.
    """
    overrides: dict[str, Path] = {}
    if args.output:
        overrides["download_root"] = Path(args.output)
    if args.state:
        overrides["state_dir"] = Path(args.state)
    return Config(**overrides)


def _engine(args: argparse.Namespace) -> Engine:
    engine = Engine(config=_config(args), settings=Settings())
    engine.start()
    return engine


def _cmd_get(args: argparse.Namespace) -> int:
    engine = _engine(args)
    job_id = engine.submit(args.url, watch=args.watch)
    print(f"queued: {job_id}")

    # With no web interface the process must stay alive while there is work,
    # otherwise it would exit and leave its threads half-way through.
    while True:
        job = engine.jobs[job_id]
        items = job.get("items", {})
        done = sum(1 for i in items.values() if i["status"] == "done")
        if job["status"] not in {"queued", "preparing", "running"}:
            print(f"\r{job['title'] or args.url}: {job['status']} ({done}/{len(items)})")
            return 0 if job["status"] == "done" else 1
        speed = sum(i.get("speed") or 0 for i in items.values())
        print(f"\r{done}/{len(items) or '?'} · {speed / 1048576:.1f} MB/s", end="", flush=True)
        time.sleep(1)


def _cmd_inspect(args: argparse.Namespace) -> int:
    info = _engine(args).inspect(args.url)
    print(f"{info['title']}  [{info['extractor']}, {info['kind']}]")
    print(f"{len(info['items'])} items" + (", still open" if info["ongoing"] else ""))
    for item in info["items"][:20]:
        print(f"  {item['index'] or '-':>4}  {item['title']}")
    if len(info["items"]) > 20:
        print(f"  … {len(info['items']) - 20} more")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from sluicebox.web.app import create_app
    config = _config(args)
    app = create_app(config=config)
    print(f"Sluice on http://{args.host}:{args.port}  ->  {config.download_root}")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


def _cmd_extractors(_: argparse.Namespace) -> int:
    extractors.load_plugins()
    for extractor in extractors.available():
        print(f"  {extractor.name:<14} {extractor.description}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sluice", description="Pluggable download manager")
    parser.add_argument("--version", action="version", version=f"sluice {__version__}")
    parser.add_argument("-o", "--output", default=None,
                        help="destination folder (default: SLUICEBOX_DOWNLOAD_ROOT or ./downloads)")
    parser.add_argument("--state", default=None,
                        help="where queue and log are kept (default: SLUICEBOX_STATE_DIR or ./state)")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    get = sub.add_parser("get", help="download everything behind a URL")
    get.add_argument("url")
    get.add_argument("--watch", action="store_true", help="re-check and fetch new items")
    get.set_defaults(func=_cmd_get)

    inspect = sub.add_parser("inspect", help="show what is behind a URL, without downloading")
    inspect.add_argument("url")
    inspect.set_defaults(func=_cmd_inspect)

    serve = sub.add_parser("serve", help="start the web interface and API")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104
    serve.add_argument("--port", type=int, default=8420)
    serve.set_defaults(func=_cmd_serve)

    sub.add_parser("extractors", help="list available extractors").set_defaults(
        func=_cmd_extractors)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
