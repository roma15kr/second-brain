"""Command line: `kb migrate | ingest | index | mcp | search`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

from kb import db, indexer
from kb.config import database_url, load_config
from kb.connectors import imap

log = logging.getLogger("kb")


def cmd_migrate(_: argparse.Namespace) -> None:
    with db.connect(database_url()) as conn:
        applied = db.migrate(conn)
    print("applied:", ", ".join(applied) if applied else "nothing (up to date)")


def cmd_ingest(args: argparse.Namespace) -> None:
    config = load_config()
    last_run: dict[str, float] = {}
    while True:
        for source in config.sources:
            if time.monotonic() - last_run.get(source.id, -1e9) < source.poll_seconds:
                continue
            last_run[source.id] = time.monotonic()
            try:
                client = imap.open_client(source)
                try:
                    with db.connect(database_url()) as conn:
                        imap.sync(conn, client, source)
                finally:
                    client.logout()
            except Exception:
                log.exception("sync failed for %s", source.id)
        if args.once:
            return
        time.sleep(5)


def cmd_index(args: argparse.Namespace) -> None:
    config = load_config()
    with db.connect(database_url()) as conn:
        while True:
            if not indexer.run_once(conn, config):
                if args.once:
                    return
                time.sleep(2)


def cmd_mcp(args: argparse.Namespace) -> None:
    import uvicorn

    from kb.mcp_server import build_app

    url = database_url()
    app = build_app(lambda: db.connect(url), os.environ.get("KB_MCP_TOKEN", ""))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def cmd_search(args: argparse.Namespace) -> None:
    from kb.search import SearchFilters, search

    with db.connect(database_url()) as conn:
        results = search(conn, args.query, SearchFilters(scopes=args.scope or None), args.limit)
    print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="kb")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    p = sub.add_parser("ingest", help="run source connectors")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_ingest)
    p = sub.add_parser("index", help="process indexing jobs")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_index)
    p = sub.add_parser("mcp", help="serve MCP over streamable HTTP")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_mcp)
    p = sub.add_parser("search", help="search from the command line")
    p.add_argument("query")
    p.add_argument("--scope", action="append")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
