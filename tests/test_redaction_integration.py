from datetime import UTC, date, datetime
from types import SimpleNamespace

from kb import db, indexer
from kb.config import Config, TelegramChat, TelegramSource
from kb.connectors import imap, telegram
from kb.mcp_server import build_server
from kb.search import search
from tests.fakes import FakeImap, make_email

BODY = "Your verification code is 482913. Server login: admin, password: Zx9!qq2L"


def ingest_email(conn, source, config):
    fake = FakeImap()
    fake.add(1, make_email("Access for hosting", BODY), datetime(2026, 9, 1))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    while indexer.run_once(conn, config):
        pass


def test_search_shows_redacted_text_archive_keeps_original(conn, source, config):
    ingest_email(conn, source, config)
    [hit] = search(conn, "hosting")
    assert "482913" not in hit.excerpt and "Zx9!qq2L" not in hit.excerpt
    item = conn.execute("SELECT raw_text FROM items").fetchone()["raw_text"]
    assert "482913" not in item and "Zx9!qq2L" not in item
    assert "[REDACTED:otp]" in item and "[REDACTED:password]" in item
    blob = bytes(conn.execute("SELECT blob FROM raw_records").fetchone()["blob"])
    assert b"482913" in blob and b"Zx9!qq2L" in blob


def test_secret_itself_is_not_searchable(conn, source, config):
    ingest_email(conn, source, config)
    assert search(conn, "482913") == []
    assert search(conn, '"Zx9!qq2L"') == []


async def test_mcp_output_is_redacted(conn, pg_url, source, config):
    ingest_email(conn, source, config)
    server = build_server(lambda: db.connect(pg_url))
    result = str(await server.call_tool("search_mail", {"query": "verification"}))
    assert "Access for hosting" in result
    assert "482913" not in result and "Zx9!qq2L" not in result


def test_telegram_message_redacted(conn):
    src = TelegramSource(id="tg", type="telegram", chats=[TelegramChat(chat=1)])
    cfg = Config(sources=[src])
    chat = telegram.ChatInfo(chat_id=1, title="Ops", username=None, peer_type="user")
    msg = SimpleNamespace(
        id=5,
        date=datetime(2026, 9, 1, tzinfo=UTC),
        message="card 4111 1111 1111 1111 for ads",
        edit_date=None,
        sender=None,
        sender_id=9,
        reply_to=None,
        reactions=None,
        media=None,
    )
    telegram.on_message(conn, src, chat, msg)
    while indexer.run_once(conn, cfg):
        pass
    [hit] = search(conn, "ads")
    assert "4111" not in hit.excerpt


def test_old_index_version_triggers_full_reindex(conn, source, config):
    ingest_email(conn, source, config)
    # Simulate items built by the pre-redaction indexer.
    conn.execute("UPDATE items SET raw_text = %s", (BODY,))
    conn.execute("DELETE FROM sync_state WHERE source_id = '_indexer'")
    assert indexer.ensure_index_version(conn) == 1
    while indexer.run_once(conn, config):
        pass
    assert "482913" not in conn.execute("SELECT raw_text FROM items").fetchone()["raw_text"]
    assert indexer.ensure_index_version(conn) == 0  # already current
