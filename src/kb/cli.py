"""Command line: `kb migrate | ingest | index | mcp | search`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

from kb import db, indexer, scopes
from kb.config import ConfigError, TelegramSource, database_url, load_config
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
        try:
            with db.connect(database_url()) as conn:
                archived_set = scopes.archived(conn)
        except Exception:
            log.exception("cannot read archived scopes")
            archived_set = set()
        for source in config.imap_sources():
            if time.monotonic() - last_run.get(source.id, -1e9) < source.poll_seconds:
                continue
            if scopes.imap_source_archived(source, archived_set):
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


def _telegram_source(source_id: str | None) -> TelegramSource:
    sources = load_config().telegram_sources()
    found = [s for s in sources if s.id == source_id] if source_id else sources[:1]
    if not found:
        raise ConfigError(f"no telegram source {source_id!r} in config")
    return found[0]


def cmd_ingest_telegram(_: argparse.Namespace) -> None:
    import asyncio

    from kb.connectors import telegram

    sources = load_config().telegram_sources()
    if not sources:
        raise ConfigError("no telegram source in config")
    url = database_url()

    async def follow(source: TelegramSource) -> None:
        # Not logged in yet / missing API credentials: wait for the owner instead of crash-looping.
        while True:
            try:
                await telegram.run(source, lambda: db.connect(url))
            except ConfigError as exc:
                log.error("%s; retrying in 60s", exc)
            except Exception:
                log.exception("telegram %s stopped; restarting in 60s", source.id)
            await asyncio.sleep(60)

    async def main() -> None:
        await asyncio.gather(*(follow(s) for s in sources))

    asyncio.run(main())


def cmd_auth_telegram(args: argparse.Namespace) -> None:
    """Interactive one-time login (phone, code, 2FA password); stores the session file."""
    import asyncio
    import os as _os

    from kb.connectors import telegram

    source = _telegram_source(args.source)
    _os.makedirs(_os.path.dirname(source.session_path) or ".", exist_ok=True)

    import getpass

    from kb import telegram_auth

    async def main() -> None:
        client = telegram.make_client(source)
        await client.connect()
        if not await client.is_user_authorized():
            if args.qr:
                await telegram_auth.login_with_qr(client, getpass.getpass, print)
            else:
                await telegram_auth.login_with_code(client, input, getpass.getpass, print)
        me = await client.get_me()
        print(f"logged in as {me.first_name} (id {me.id}); session saved to {source.session_path}")
        await client.disconnect()

    asyncio.run(main())


def cmd_telegram_chats(args: argparse.Namespace) -> None:
    """List your chats (id, type, title, @username) to build the allowlist."""
    import asyncio

    from kb.connectors import telegram

    source = _telegram_source(args.source)

    async def main() -> None:
        raw = telegram.make_client(source, snapshot=True)
        await raw.connect()
        if not await raw.is_user_authorized():
            raise ConfigError(f"not logged in; run `kb auth telegram {source.id}`")
        client = telegram.ReadOnlyClient(raw)
        async for dialog in client.iter_dialogs():
            info = telegram.chat_info(dialog.entity)
            mark = "✓" if source.chat_config(info.chat_id, info.username) else " "
            user = f"@{info.username}" if info.username else ""
            print(f"{mark} {info.chat_id:>16}  {info.peer_type:<7}  {info.title}  {user}")
        await raw.disconnect()

    asyncio.run(main())


def cmd_unsorted(args: argparse.Namespace) -> None:
    config = load_config()
    with db.connect(database_url()) as conn:
        if args.unsorted_command == "list":
            rows = scopes.list_unsorted(conn, args.limit)
            for r in rows:
                when = r["last_activity_at"].strftime("%Y-%m-%d") if r["last_activity_at"] else "-"
                who = ", ".join(r["participants"][:3])
                print(f"{r['id']:>8}  {when}  {r['kind']:<15} {r['title'] or ''}  [{who}]")
            print(f"{len(rows)} unsorted item(s)")
        else:
            apply_to = "chat" if args.apply_to_chat else "sender" if args.apply_to_sender else None
            print(scopes.assign(conn, config, args.item_id, args.scopes, apply_to))


def cmd_scope(args: argparse.Namespace) -> None:
    with db.connect(database_url()) as conn:
        if args.scope_command in ("archive", "unarchive"):
            scopes.set_archived(conn, args.scope, args.scope_command == "archive")
        print("archived scopes:", ", ".join(sorted(scopes.archived(conn))) or "none")


def cmd_index(args: argparse.Namespace) -> None:
    config = load_config()
    with db.connect(database_url()) as conn:
        if not indexer.ensure_index_version(conn):
            scopes.ensure_rules_current(conn, config)
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
    sub.add_parser("ingest-telegram", help="follow allowlisted Telegram chats").set_defaults(
        func=cmd_ingest_telegram
    )
    p = sub.add_parser("auth", help="one-time interactive logins")
    auth = p.add_subparsers(dest="provider", required=True)
    p = auth.add_parser("telegram", help="log in to Telegram as yourself (read-only use)")
    p.add_argument("source", nargs="?")
    p.add_argument("--qr", action="store_true", help="log in by scanning a QR code instead")
    p.set_defaults(func=cmd_auth_telegram)
    p = sub.add_parser("telegram", help="Telegram helpers")
    tg = p.add_subparsers(dest="tg_command", required=True)
    p = tg.add_parser("chats", help="list your chats with ids for the allowlist")
    p.add_argument("source", nargs="?")
    p.set_defaults(func=cmd_telegram_chats)
    p = sub.add_parser("unsorted", help="review items without a scope")
    us = p.add_subparsers(dest="unsorted_command", required=True)
    p = us.add_parser("list")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_unsorted)
    p = us.add_parser("assign", help="kb unsorted assign ITEM_ID SCOPE [SCOPE...]")
    p.add_argument("item_id", type=int)
    p.add_argument("scopes", nargs="+")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--apply-to-chat", action="store_true", help="rule for the whole chat")
    group.add_argument("--apply-to-sender", action="store_true", help="rule for this sender")
    p.set_defaults(func=cmd_unsorted)
    p = sub.add_parser("scope", help="archive scopes of ended engagements")
    sc = p.add_subparsers(dest="scope_command", required=True)
    for name in ("archive", "unarchive"):
        p = sc.add_parser(name)
        p.add_argument("scope")
        p.set_defaults(func=cmd_scope)
    sc.add_parser("list").set_defaults(func=cmd_scope)
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
