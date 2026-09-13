"""Interfaccia da riga di comando."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from sluice import __version__, extractors
from sluice.config import Config, Settings
from sluice.engine import Engine


def _engine(args: argparse.Namespace) -> Engine:
    config = Config(download_root=Path(args.output), state_dir=Path(args.state))
    engine = Engine(config=config, settings=Settings())
    engine.start()
    return engine


def _cmd_get(args: argparse.Namespace) -> int:
    engine = _engine(args)
    job_id = engine.submit(args.url, watch=args.watch)
    print(f"in coda: {job_id}")

    # Senza interfaccia web il processo deve restare vivo finche' c'e' lavoro,
    # altrimenti uscirebbe lasciando i thread a meta'.
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
    print(f"{len(info['items'])} elementi"
          + (", raccolta ancora aperta" if info["ongoing"] else ""))
    for item in info["items"][:20]:
        print(f"  {item['index'] or '-':>4}  {item['title']}")
    if len(info["items"]) > 20:
        print(f"  … altri {len(info['items']) - 20}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from sluice.web.app import create_app
    config = Config(download_root=Path(args.output), state_dir=Path(args.state))
    app = create_app(config=config)
    print(f"Sluice su http://{args.host}:{args.port}  ->  {config.download_root}")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


def _cmd_extractors(_: argparse.Namespace) -> int:
    extractors.load_plugins()
    for extractor in extractors.available():
        print(f"  {extractor.name:<14} {extractor.description}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sluice", description=__doc__)
    parser.add_argument("--version", action="version", version=f"sluice {__version__}")
    parser.add_argument("-o", "--output", default="./downloads", help="cartella di destinazione")
    parser.add_argument("--state", default="./state", help="dove salvare coda e registro")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    get = sub.add_parser("get", help="scarica tutto quello che c'e' a un URL")
    get.add_argument("url")
    get.add_argument("--watch", action="store_true", help="ricontrolla e prendi i nuovi elementi")
    get.set_defaults(func=_cmd_get)

    inspect = sub.add_parser("inspect", help="mostra cosa c'e' a un URL senza scaricare")
    inspect.add_argument("url")
    inspect.set_defaults(func=_cmd_inspect)

    serve = sub.add_parser("serve", help="avvia interfaccia web e API")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104
    serve.add_argument("--port", type=int, default=8420)
    serve.set_defaults(func=_cmd_serve)

    sub.add_parser("extractors", help="elenca gli estrattori disponibili").set_defaults(
        func=_cmd_extractors)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
