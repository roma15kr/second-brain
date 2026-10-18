from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from kb import indexer
from kb.config import TelegramChat
from kb.connectors import telegram
from kb.connectors.telegram import ChatInfo, ReadOnlyClient
from kb.search import SearchFilters, search

ALLOWED = ChatInfo(chat_id=-1001234, title="Quokka team", username=None, peer_type="channel")
OTHER = ChatInfo(chat_id=-1009999, title="Random chat", username=None, peer_type="channel")
DM = ChatInfo(chat_id=555, title="Oleh", username="oleh_q", peer_type="user")


def msg(msg_id, text, date=datetime(2026, 9, 1, 10, tzinfo=UTC), edit_date=None, **kw):
    sender = SimpleNamespace(first_name="Oleh", last_name="K", username="oleh_q")
    return SimpleNamespace(
        id=msg_id,
        date=date,
        message=text,
        edit_date=edit_date,
        sender=sender,
        sender_id=77,
        reply_to=kw.get("reply_to"),
        reactions=None,
        media=None,
    )


def index_all(conn, config):
    while indexer.run_once(conn, config):
        pass


FORBIDDEN = {
    "send_message",
    "send_file",
    "send_read_acknowledge",
    "edit_message",
    "delete_messages",
    "forward_messages",
    "pin_message",
    "send_reaction",
    "mark_read",
    "__getattr__",
}


def test_telegram_wrapper_has_no_write_methods():
    names = {n for n in dir(ReadOnlyClient) if not n.startswith("_ReadOnlyClient__")}
    assert not (names & FORBIDDEN)
    public = {n for n in names if not n.startswith("_")}
    assert public == {"iter_messages", "iter_dialogs", "get_entity", "get_me"}


def test_not_allowlisted_chat_stores_nothing(conn, tg_source):
    assert telegram.on_message(conn, tg_source, OTHER, msg(1, "secret plans")) is False
    assert conn.execute("SELECT count(*) AS n FROM raw_records").fetchone()["n"] == 0


def test_allowlisted_by_username(conn, tg_source):
    assert telegram.on_message(conn, tg_source, DM, msg(1, "hi")) is True


def test_message_is_searchable_with_chat_scope_and_link(conn, tg_source, tg_config):
    telegram.on_message(conn, tg_source, ALLOWED, msg(42, "Rozetka listing approved"))
    index_all(conn, tg_config)
    [r] = search(conn, "Rozetka")
    assert r.kind == "tg_conversation"
    assert r.scopes == ["quokka"]
    assert r.title == "Quokka team"
    assert r.locator == "https://t.me/c/1234/42"
    assert "Oleh K (@oleh_q)" in r.participants[0]


def test_chat_without_own_scope_uses_source_default(conn, tg_source, tg_config):
    telegram.on_message(conn, tg_source, DM, msg(7, "dinner tomorrow"))
    index_all(conn, tg_config)
    assert search(conn, "dinner")[0].scopes == ["personal"]


def test_tg_edit_updates_search_delete_hides(conn, tg_source, tg_config):
    telegram.on_message(conn, tg_source, ALLOWED, msg(5, "budget is 5000"))
    index_all(conn, tg_config)
    edited = msg(5, "budget is 7000", edit_date=datetime(2026, 9, 1, 11, tzinfo=UTC))
    telegram.on_message(conn, tg_source, ALLOWED, edited)
    index_all(conn, tg_config)
    assert search(conn, "7000") and not search(conn, "5000")

    telegram.on_deleted(conn, tg_source, ALLOWED.chat_id, [5])
    index_all(conn, tg_config)
    assert search(conn, "7000") == []
    raw = conn.execute("SELECT count(*) AS n FROM raw_records WHERE kind='tg_message'").fetchone()
    assert raw["n"] == 2  # archive keeps both versions


def test_older_version_never_overwrites_newer(conn, tg_source, tg_config):
    new = msg(9, "final text", edit_date=datetime(2026, 9, 2, tzinfo=UTC))
    telegram.on_message(conn, tg_source, ALLOWED, new)
    telegram.on_message(conn, tg_source, ALLOWED, msg(9, "draft text"))
    index_all(conn, tg_config)
    assert search(conn, "final") and not search(conn, "draft")


def test_private_delete_without_chat_id_spares_channels(conn, tg_source, tg_config):
    telegram.on_message(conn, tg_source, DM, msg(100, "private note"))
    telegram.on_message(conn, tg_source, ALLOWED, msg(100, "channel note"))
    index_all(conn, tg_config)
    telegram.on_deleted(conn, tg_source, None, [100])
    index_all(conn, tg_config)
    assert search(conn, "private") == []
    assert search(conn, "channel")


def test_media_without_text_is_archived_not_indexed(conn, tg_source, tg_config):
    telegram.on_message(conn, tg_source, ALLOWED, msg(3, ""))
    index_all(conn, tg_config)
    assert conn.execute("SELECT count(*) AS n FROM items").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM raw_records").fetchone()["n"] == 1


class FakeClient:
    def __init__(self, history):
        self.history = history  # chat_id -> list of messages (ascending)
        self.calls = []

    def iter_messages(self, entity, **kw):
        self.calls.append((entity.chat_id, kw))
        msgs = self.history[entity.chat_id]
        if "min_id" in kw:
            msgs = [m for m in msgs if m.id > kw["min_id"]]
        else:
            msgs = [m for m in msgs if m.date >= kw["offset_date"]]

        async def gen():
            for m in msgs:
                yield m

        return gen()


@pytest.fixture
def no_resolve(monkeypatch):
    monkeypatch.setattr(telegram, "chat_info", lambda entity: entity)


async def test_catch_up_backfill_then_min_id(conn, tg_source, no_resolve):
    old = msg(1, "too old", date=datetime(2024, 1, 1, tzinfo=UTC))
    history = {ALLOWED.chat_id: [old, msg(2, "in window"), msg(3, "also in window")]}
    client = FakeClient(history)
    now = datetime(2026, 10, 10, tzinfo=UTC)
    assert await telegram.catch_up(conn, client, tg_source, [ALLOWED], now=now) == 2
    history[ALLOWED.chat_id].append(msg(4, "later"))
    assert await telegram.catch_up(conn, client, tg_source, [ALLOWED], now=now) == 1
    assert client.calls[1][1]["min_id"] == 3


def test_search_kind_filter(conn, tg_source, tg_config):
    telegram.on_message(conn, tg_source, ALLOWED, msg(1, "contract signed"))
    index_all(conn, tg_config)
    assert search(conn, "contract", SearchFilters(kinds=["email_thread"])) == []
    assert search(conn, "contract", SearchFilters(kinds=["tg_conversation"]))


def test_telegram_chat_matching():
    c = TelegramChat(chat="@Oleh_Q")
    assert c.matches(555, "oleh_q") and not c.matches(555, None)
    assert TelegramChat(chat="-1001234").matches(-1001234, None)


def test_session_snapshot_reads_while_live_file_is_write_locked(tmp_path):
    import os
    import sqlite3

    from telethon.crypto import AuthKey
    from telethon.sessions import SQLiteSession

    live = SQLiteSession(str(tmp_path / "kb"))
    live.set_dc(2, "149.154.167.51", 443)
    key = os.urandom(256)
    live.auth_key = AuthKey(data=key)
    live.save()

    holder = sqlite3.connect(tmp_path / "kb.session")
    holder.execute("BEGIN IMMEDIATE")  # what the running ingest service can hold
    holder.execute("DELETE FROM sessions")  # uncommitted write by the other process
    try:
        snap = telegram.session_snapshot(str(tmp_path / "kb.session"))
    finally:
        holder.rollback()
        holder.close()
    assert snap.auth_key.key == key
    assert snap.server_address == "149.154.167.51"


def test_session_snapshot_requires_login(tmp_path):
    from kb.config import ConfigError

    with pytest.raises(ConfigError, match="kb auth telegram"):
        telegram.session_snapshot(str(tmp_path / "missing.session"))


def test_owner_telegram_id_recorded_once(conn):
    from types import SimpleNamespace

    from kb import loops

    telegram.record_self(conn, SimpleNamespace(id=507325261))
    telegram.record_self(conn, SimpleNamespace(id=507325261))
    assert loops.owner_telegram_ids(conn) == {"507325261"}
