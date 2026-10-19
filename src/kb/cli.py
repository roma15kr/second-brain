"""Command line: `kb migrate | ingest | index | mcp | search`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from kb import db, health, idf, indexer, scopes
from kb.config import Config, ConfigError, TelegramSource, database_url, load_config
from kb.connectors import accounts, imap

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
        try:  # mailboxes connected in the web OS are re-read every cycle (no restart)
            with db.connect(database_url()) as conn:
                connected = accounts.imap_sources(conn)
        except Exception:
            log.exception("cannot read connected mailboxes")
            connected = []
        for source in [*config.imap_sources(), *connected]:
            if time.monotonic() - last_run.get(source.id, -1e9) < source.poll_seconds:
                continue
            if scopes.imap_source_archived(source, archived_set):
                continue
            last_run[source.id] = time.monotonic()
            try:
                client = imap.open_client(source)
                try:
                    with db.connect(database_url()) as conn:
                        new, backfilling = imap.sync(conn, client, source)
                        health.record_ok(
                            conn,
                            source.id,
                            new=new,
                            backfilling=backfilling,
                            folders=imap.folder_cursors(conn, source.id),
                        )
                    if backfilling:  # keep going quickly until the backfill is done
                        last_run[source.id] -= source.poll_seconds - 5
                finally:
                    client.logout()
            except Exception as exc:
                log.exception("sync failed for %s", source.id)
                _record_error(source.id, exc)
        _sync_clickup(last_run)
        _sync_calendars(config)
        if args.once:
            return
        time.sleep(5)


CLICKUP_EVERY = 300  # seconds between ClickUp syncs
CLICKUP_LISTS_EVERY = 3600  # refresh the spaces/lists catalogue hourly
CLICKUP_COMMENTS_EVERY = 1800  # check recently active open tasks for new comments
CLICKUP_SLICE_SECONDS = 60  # ClickUp work per turn, so mail sync is never held up for long


def _sync_clickup(last_run: dict[str, float]) -> None:
    """ClickUp accounts connected in the web OS: changed tasks every 5 minutes (design D14)."""
    from kb.connectors import clickup

    try:
        with db.connect(database_url()) as conn:
            connected = clickup.accounts(conn)
    except Exception:
        log.exception("cannot read ClickUp accounts")
        return
    for acc in connected:
        sid = clickup.source_id(acc.id)
        now = time.monotonic()
        if now < last_run.get(f"{sid}:until", 0) or now - last_run.get(sid, -1e9) < CLICKUP_EVERY:
            continue
        last_run[sid] = now
        client = clickup.ClickUpClient(acc.token)
        try:
            with db.connect(database_url()) as conn:
                hourly = now - last_run.get(f"{sid}:lists", -1e9) >= CLICKUP_LISTS_EVERY
                try:  # notifications need it; syncing must not wait on it
                    clickup.ensure_identity(
                        conn, client, acc, datetime.now(UTC), refresh_group=hourly
                    )
                except clickup.RateLimited:
                    raise
                except Exception:
                    log.exception("%s: cannot read the ClickUp user or groups", sid)
                if hourly:
                    clickup.refresh_lists(conn, client, acc)
                    last_run[f"{sid}:lists"] = now
                n, finished = clickup.sync_account_for(conn, client, acc, CLICKUP_SLICE_SECONDS)
                if not finished:  # a big first pass: continue soon, mail sync runs in between
                    last_run[sid] = now - CLICKUP_EVERY + 10
                try:  # followed chat channels (ClickUp Chat API v3)
                    n += clickup.sync_chat(conn, client, acc, datetime.now(UTC))
                except clickup.RateLimited:
                    raise
                except Exception:
                    log.exception("%s: chat sync failed", sid)
                if (
                    finished
                    and now - last_run.get(f"{sid}:comments", -1e9) >= CLICKUP_COMMENTS_EVERY
                ):
                    n += clickup.refresh_recent_comments(conn, client, acc)
                    last_run[f"{sid}:comments"] = now
                health.record_ok(conn, sid, new=n)
        except clickup.RateLimited as exc:  # pause until ClickUp's reset; the cursor is saved
            last_run[f"{sid}:until"] = now + max(5.0, exc.reset_at - time.time())
            log.warning("%s: %s", sid, exc)
        except Exception as exc:
            log.exception("ClickUp sync failed for %s", sid)
            _record_error(sid, exc)


def _record_error(source_id: str, exc: BaseException) -> None:
    try:
        with db.connect(database_url()) as conn:
            health.record_error(conn, source_id, f"{type(exc).__name__}: {exc}")
    except Exception:
        log.exception("cannot record error for %s", source_id)


def cmd_status(_: argparse.Namespace) -> None:
    config = load_config()
    with db.connect(database_url()) as conn:
        print(json.dumps(health.status(conn, config), ensure_ascii=False, indent=2, default=str))


def _telegram_source(source_id: str | None) -> TelegramSource:
    sources = load_config().telegram_sources()
    found = [s for s in sources if s.id == source_id] if source_id else sources[:1]
    if not found:
        raise ConfigError(f"no telegram source {source_id!r} in config")
    return found[0]


def _sync_calendars(config: Config) -> None:
    """Marked calendars every 10 minutes (each calendar keeps its own last sync time)."""
    from datetime import UTC, datetime

    from kb import loops
    from kb.connectors import calendar

    try:
        with db.connect(database_url()) as conn:
            calendar.sync_due(conn, datetime.now(UTC), loops.owner_emails(conn, config))
    except Exception:
        log.exception("calendar sync failed")


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
                _record_error(source.id, exc)
            except Exception as exc:
                log.exception("telegram %s stopped; restarting in 60s", source.id)
                _record_error(source.id, exc)
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


def cmd_people(args: argparse.Namespace) -> None:
    from kb import people

    with db.connect(database_url()) as conn:
        if args.people_command == "show":
            found = people.find(conn, args.ref) if not args.ref.isdigit() else []
            if len(found) > 1:
                for p in found:
                    print(f"{p['id']:>8}  {p['display_name']}")
                return
            pid = people.resolve(conn, args.ref)
            print(json.dumps(people.profile(conn, pid), ensure_ascii=False, indent=2))
        elif args.people_command == "merge":
            keep, other = people.resolve(conn, args.keep), people.resolve(conn, args.other)
            merge_id = people.merge(conn, keep, other)
            print(f"merged {other} into {keep}; undo with: kb people split {merge_id}")
        elif args.people_command == "split":
            people.split(conn, args.merge_id)
            print(f"merge {args.merge_id} undone")
        elif args.people_command == "link":
            linked = people.link(conn, people.resolve(conn, args.person), args.identity)
            print("linked" + (f" (merged; undo with: kb people split {linked})" if linked else ""))


def cmd_eval(args: argparse.Namespace) -> None:
    """Run acceptance questions; against a live MCP server with --mcp-url (full pipeline)."""
    from kb import evaluate

    cases = evaluate.load(args.file)
    if args.mcp_url:
        token = os.environ.get(args.token_env, "")
        if not token:
            raise ConfigError(f"set {args.token_env} to the MCP bearer token")
        search_fn = evaluate.mcp_search(args.mcp_url, token)
    else:
        from kb import embed, rerank
        from kb.search import search

        config = load_config()
        embedder = embed.default_embedder(config)
        reranker = rerank.default_reranker(config)
        url = database_url()

        def search_fn(q: str, k: int) -> list[dict[str, Any]]:
            with db.connect(url) as conn:
                hits = search(
                    conn, q, limit=k, embedder=embedder, reranker=reranker, settings=config.search
                )
            return [h.to_dict() for h in hits]

    result = evaluate.report(evaluate.run(cases, search_fn, args.k), args.k)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.min_recall is not None and (result[f"recall@{args.k}"] or 0) < args.min_recall:
        raise SystemExit(f"recall@{args.k} below {args.min_recall}")


def cmd_rebuild(args: argparse.Namespace) -> None:
    with db.connect(database_url()) as conn:
        n = indexer.rebuild(conn, args.source)
    print(f"queued {n} archived records; the index service rebuilds them (no source is contacted)")


def cmd_cost_estimate(_: argparse.Namespace) -> None:
    from kb import distill

    config = load_config()
    with db.connect(database_url()) as conn:
        print(json.dumps(distill.cost_estimate(conn, config), indent=2))


def cmd_index(args: argparse.Namespace) -> None:
    config = load_config()
    from kb import distill, embed, passages

    client = distill.default_client(config)
    embedder = embed.default_embedder(config)
    if client is None:
        log.warning("AI summaries disabled: set llm.enabled: true and OPENAI_API_KEY to enable")
    last_cycle = 0.0
    last_idf = 0.0
    with db.connect(database_url()) as conn:
        if not indexer.ensure_index_version(conn):
            scopes.ensure_rules_current(conn, config)
        while True:
            if indexer.run_once(conn, config):
                continue
            if time.monotonic() - last_idf > 600:
                last_idf = time.monotonic()
                try:
                    idf.refresh(conn)
                except Exception:
                    log.exception("idf refresh failed")
            try:
                if passages.backfill_cycle(conn):
                    continue
            except Exception:
                log.exception("passage backfill failed")
            if embedder is not None:
                try:
                    embed.embed_goals(conn, embedder)
                    if embed.run_cycle(conn, config, embedder):
                        continue  # keep embedding while there is work
                except Exception as exc:
                    log.exception("embedding cycle failed")
                    health.record_error(conn, "_embeddings", f"{type(exc).__name__}: {exc}")
                    time.sleep(10)
            if client is not None and time.monotonic() - last_cycle > 30:
                last_cycle = time.monotonic()
                try:
                    stats = distill.run_cycle(conn, config, client)
                    if any(stats.values()):
                        log.info("distill: %s", stats)
                except Exception:
                    log.exception("distill cycle failed")
                continue
            if args.once:
                return
            time.sleep(2)


def build_mcp_app(config: Config, url: str, token: str, preload: bool = True) -> Any:
    """The MCP app with everything search uses: embedder and reranker (models load in the
    background when `preload`)."""
    from kb import embed, rerank
    from kb.mcp_server import build_app

    embedder = embed.default_embedder(config)
    reranker = rerank.default_reranker(config)
    if preload:
        if isinstance(embedder, embed.FastEmbedder):
            embedder.preload()
        if isinstance(reranker, rerank.FastReranker):
            reranker.preload()
    return build_app(lambda: db.connect(url), token, config, embedder, reranker)


def build_web_app() -> Any:
    """The web OS app: SPA from KB_WEB_DIST (set by the Docker image), passkeys bound to
    KB_WEB_ORIGIN, data from DATABASE_URL."""
    from pathlib import Path

    from kb.api.app import build_app
    from kb.api.auth import RelyingParty

    dist = os.environ.get("KB_WEB_DIST")
    origin = os.environ.get("KB_WEB_ORIGIN", "")
    url = database_url()
    try:
        from kb.api import routes_requests

        with db.connect(url) as conn:
            routes_requests.fail_interrupted(conn)
    except Exception:
        log.exception("cannot mark interrupted assistant requests")
    return build_app(
        Path(dist) if dist else None,
        connect=lambda: db.connect(url),
        rp=RelyingParty(origin) if origin else None,
        config=load_config(),
        searcher=_web_searcher(),
    )


def _web_searcher() -> Any:
    """Search through the MCP service (models loaded there) when KB_SEARCH_URL is set."""
    from kb.api.routes_search import remote_searcher

    url, token = os.environ.get("KB_SEARCH_URL"), os.environ.get("KB_MCP_TOKEN")
    return remote_searcher(url, token) if url and token else None


def cmd_web(args: argparse.Namespace) -> None:
    if args.action == "vapid-keys":
        from kb import push

        public, private = push.generate_vapid_keys()
        print("Set these in Coolify (never commit them):")
        print(f"WEB_PUSH_VAPID_PUBLIC_KEY={public}")
        print(f"WEB_PUSH_VAPID_PRIVATE_KEY={private}")
        return
    if args.action == "setup-code":
        from datetime import UTC, datetime

        from kb.api import auth

        with db.connect(database_url()) as conn:
            code = auth.new_setup_code(conn, datetime.now(UTC))
        print(f"setup code: {code}  (valid 1 hour, single use; enter it for the first passkey)")
        return
    import uvicorn

    uvicorn.run(
        build_web_app(), host=args.host, port=args.port, log_level="info", proxy_headers=True
    )


def cmd_routines(args: argparse.Namespace) -> None:
    from datetime import UTC, datetime

    from kb.routines import briefs, scheduler

    config = load_config()
    runners = briefs.runners(config, briefs.default_llm(config))
    if args.routines_command == "run":
        if args.routine not in runners:
            raise ConfigError(f"routine {args.routine!r} is not available yet")
        with db.connect(database_url()) as conn:
            brief_id = runners[args.routine](conn, datetime.now(UTC))
            brief = briefs.latest(conn, [args.routine])
        print(f"brief {brief_id}: {brief['headline'] if brief else ''}")
        return
    url = database_url()
    from kb import loops, push

    def close_answered_loops(conn: db.Conn, now: datetime) -> int:
        return loops.close_answered(conn, loops.owner_emails(conn, config), now)

    llm = briefs.default_llm(config)

    def push_clickup(conn: db.Conn, now: datetime) -> int:
        from kb.connectors import clickup

        return clickup.push_pending(conn, now)

    def propose_goals(conn: db.Conn, now: datetime) -> int:
        from kb import goals

        return goals.cycle(conn, config, llm, now)

    def apply_mail(conn: db.Conn, now: datetime) -> int:
        from kb.assistant import suggestions

        return suggestions.apply_mail(conn, config, now)

    searcher = _web_searcher()

    def draft_replies(conn: db.Conn, now: datetime) -> int:
        from kb.assistant import drafting

        return drafting.cycle(conn, config, llm, now, searcher)

    def propose_actions(conn: db.Conn, now: datetime) -> int:
        from kb.assistant import proactive

        return proactive.cycle(conn, config, llm, now)

    from kb import dictation

    transcriber = dictation.default_transcriber()

    def maintain_dictations(conn: db.Conn, now: datetime) -> int:
        return dictation.maintain(conn, config, transcriber, now)

    def remind_meetings(conn: db.Conn, now: datetime) -> int:
        from kb import meetings

        return meetings.remind_due(conn, now)

    def prepare_meetings(conn: db.Conn, now: datetime) -> int:
        from kb import meetings

        return meetings.prepare_due(conn, config, llm, now)

    def clean_threads(conn: db.Conn, now: datetime) -> int:
        from kb.api import routes_requests

        return routes_requests.delete_old_threads(conn, now)

    def detect_loops(conn: db.Conn, now: datetime) -> int:
        from kb import loop_detect

        # a few conversations per cycle so scheduled briefs are never delayed
        return loop_detect.detect_cycle(conn, config, llm, now, limit=5)

    scheduler.serve(
        lambda: db.connect(url),
        runners,
        notify=push.notify_brief,
        maintenance=[
            close_answered_loops,
            loops.wake_snoozed,
            push_clickup,
            prepare_meetings,
            remind_meetings,
            apply_mail,
            draft_replies,
            propose_actions,
            clean_threads,
            maintain_dictations,
            detect_loops,
            propose_goals,
        ],
    )


def cmd_mcp(args: argparse.Namespace) -> None:
    import uvicorn

    app = build_mcp_app(load_config(), database_url(), os.environ.get("KB_MCP_TOKEN", ""))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def cmd_search(args: argparse.Namespace) -> None:
    from kb.search import SearchFilters, search

    with db.connect(database_url()) as conn:
        results = search(conn, args.query, SearchFilters(scopes=args.scope or None), args.limit)
    print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
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
    sub.add_parser("status", help="sync health, index queue, counts").set_defaults(func=cmd_status)
    sub.add_parser("cost-estimate", help="dry run: what AI summaries would cost now").set_defaults(
        func=cmd_cost_estimate
    )
    p = sub.add_parser("people", help="people directory: show, merge, split, link")
    pp = p.add_subparsers(dest="people_command", required=True)
    p = pp.add_parser("show", help="kb people show <id | name | email>")
    p.add_argument("ref")
    p.set_defaults(func=cmd_people)
    p = pp.add_parser("merge", help="kb people merge <keep> <other>")
    p.add_argument("keep")
    p.add_argument("other")
    p.set_defaults(func=cmd_people)
    p = pp.add_parser("split", help="kb people split <merge id>  (undo a merge)")
    p.add_argument("merge_id", type=int)
    p.set_defaults(func=cmd_people)
    p = pp.add_parser("link", help="kb people link <person> phone:+380… | email:a@b.c")
    p.add_argument("person")
    p.add_argument("identity")
    p.set_defaults(func=cmd_people)
    p = sub.add_parser("eval", help="acceptance questions: recall@k, MRR, latency, misses")
    p.add_argument("file", help="YAML question file (see eval/questions.example.yaml)")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--mcp-url", help="evaluate a live server, e.g. https://…/mcp")
    p.add_argument("--token-env", default="KB_MCP_TOKEN")
    p.add_argument("--min-recall", type=float, help="exit non-zero below this recall@k")
    p.set_defaults(func=cmd_eval)
    p = sub.add_parser("rebuild", help="rebuild search data from the archive")
    p.add_argument("--source", help="only this source id (default: all)")
    p.set_defaults(func=cmd_rebuild)
    p = sub.add_parser("index", help="process indexing jobs")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_index)
    p = sub.add_parser("mcp", help="serve MCP over streamable HTTP")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_mcp)
    p = sub.add_parser("web", help="serve the web OS (JSON API + SPA)")
    p.add_argument(
        "action", nargs="?", choices=["serve", "setup-code", "vapid-keys"], default="serve"
    )
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8001)
    p.set_defaults(func=cmd_web)
    p = sub.add_parser("routines", help="assistant routines: scheduler, or `run <routine>` now")
    rs = p.add_subparsers(dest="routines_command")  # no subcommand: run the scheduler
    rr = rs.add_parser("run", help="run one routine now, e.g. kb routines run morning")
    rr.add_argument(
        "routine", choices=["morning", "revision", "evening", "weekly_review", "weekly_plan"]
    )
    p.set_defaults(func=cmd_routines)
    p = sub.add_parser("search", help="search from the command line")
    p.add_argument("query")
    p.add_argument("--scope", action="append")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
