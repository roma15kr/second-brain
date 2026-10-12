from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kb import db, indexer, people
from kb.config import Config, ImapSource, TelegramChat, TelegramSource
from kb.connectors import imap, telegram
from kb.mcp_server import build_server
from kb.people import PeopleError
from kb.search import SearchFilters, search
from tests.fakes import FakeImap, call, make_email

T0 = datetime(2026, 9, 1, 10, tzinfo=UTC)
CHAT = telegram.ChatInfo(chat_id=-1001, title="Quokka team", username=None, peer_type="channel")


@pytest.fixture
def world(conn, monkeypatch):
    monkeypatch.setenv("U", "me@dgs.ai")
    monkeypatch.setenv("P", "x")
    mail = ImapSource(
        id="mail", type="imap", host="h", username_env="U", password_env="P", scopes=["quokka"]
    )
    tg = TelegramSource(
        id="tg", type="telegram", chats=[TelegramChat(chat=-1001, scopes=["quokka"])]
    )
    return mail, tg, Config(sources=[mail, tg])


def index_all(conn, cfg):
    while indexer.run_once(conn, cfg):
        pass


def send_mail(conn, src, cfg, *mails):
    fake = FakeImap()
    for i, (subject, sender) in enumerate(mails, 1):
        fake.add(
            i,
            make_email(subject, f"about {subject}", sender=sender, message_id=f"<{i}@x>"),
            datetime(2026, 9, 1),
        )
    imap.sync_folder(conn, fake, src, "INBOX", today=date(2026, 10, 10))
    index_all(conn, cfg)


def tg_msg(i, text, sender_id, first, username=None, phone=None, minutes=0):
    sender = SimpleNamespace(first_name=first, last_name="", username=username, phone=phone)
    return SimpleNamespace(
        id=i,
        date=T0 + timedelta(hours=3 * i, minutes=minutes),
        message=text,
        edit_date=None,
        sender=sender,
        sender_id=sender_id,
        reply_to=None,
        reactions=None,
        media=None,
    )


def send_tg(conn, tg, cfg, *msgs):
    for m in msgs:
        telegram.on_message(conn, tg, CHAT, m)
    index_all(conn, cfg)


def person_of(conn, key):
    return conn.execute("SELECT person_id FROM identities WHERE key = %s", (key,)).fetchone()[
        "person_id"
    ]


def test_link_identities_exact_email_phone_not_name(conn, world):
    mail, tg, cfg = world
    send_mail(conn, mail, cfg, ("Prices", "Oleh K <oleh@quokka.ua>"), ("Again", "oleh@quokka.ua"))
    send_tg(
        conn,
        tg,
        cfg,
        tg_msg(1, "price list attached", 101, "Andrii", username="andrii_a"),
        tg_msg(2, "different Andrii here", 202, "Andrii"),
        tg_msg(3, "hi", 303, "Oleh", phone="+380 98 111 22 33"),
    )
    # the same address twice is one person, with the header display name
    oleh_mail = person_of(conn, "email:oleh@quokka.ua")
    assert people.profile(conn, oleh_mail)["display_name"] == "Oleh K"
    # a Telegram id and its username belong together
    assert person_of(conn, "tg:101") == person_of(conn, "tgu:andrii_a")
    # same name, different accounts: different people
    assert person_of(conn, "tg:101") != person_of(conn, "tg:202")
    # a phone seen on Telegram, configured for the email contact → one person
    oleh_tg = person_of(conn, "tg:303")
    assert oleh_tg != oleh_mail
    merge_id = people.link(conn, oleh_mail, "phone:+380981112233")
    assert merge_id is not None
    assert person_of(conn, "tg:303") == person_of(conn, "email:oleh@quokka.ua")


def test_merge_then_split_restores(conn, world):
    mail, tg, cfg = world
    send_mail(conn, mail, cfg, ("Budget", "oleh@quokka.ua"))
    send_tg(conn, tg, cfg, tg_msg(1, "budget in chat", 101, "Oleh"))
    a, b = person_of(conn, "email:oleh@quokka.ua"), person_of(conn, "tg:101")
    merge_id = people.merge(conn, a, b)
    assert person_of(conn, "tg:101") == a
    with pytest.raises(PeopleError, match="was merged into"):
        people.merge(conn, a, b)
    people.split(conn, merge_id)
    assert person_of(conn, "tg:101") == b
    assert people.profile(conn, b)["identities"] == ["tg:101"]
    with pytest.raises(PeopleError, match="already undone"):
        people.split(conn, merge_id)


def test_merged_person_filter_returns_both_channels(conn, world):
    mail, tg, cfg = world
    send_mail(conn, mail, cfg, ("Budget Q4", "oleh@quokka.ua"), ("Budget other", "ann@quokka.ua"))
    send_tg(conn, tg, cfg, tg_msg(1, "budget for Q4 in chat", 101, "Oleh"))
    oleh = person_of(conn, "email:oleh@quokka.ua")
    keys = people.keys_of(conn, oleh)
    assert {r.kind for r in search(conn, "budget", SearchFilters(person_keys=keys))} == {
        "email_thread"
    }
    people.merge(conn, oleh, person_of(conn, "tg:101"))
    keys = people.keys_of(conn, oleh)
    hits = search(conn, "budget", SearchFilters(person_keys=keys))
    assert {r.kind for r in hits} == {"email_thread", "tg_conversation"}
    assert all("ann" not in " ".join(h.participants) for h in hits)


def test_lookup_partial_name_and_profile(conn, world):
    mail, tg, cfg = world
    send_mail(conn, mail, cfg, ("Hello", "Oleh K <oleh@quokka.ua>"))
    send_tg(conn, tg, cfg, tg_msg(1, "hi", 101, "Oleh"), tg_msg(2, "hey", 202, "Olena"))
    names = {p["display_name"] for p in people.find(conn, "ole")}
    assert {"Oleh K", "Oleh", "Olena"} <= names
    with pytest.raises(PeopleError, match="matches several people"):
        people.resolve(conn, "ole")
    prof = people.profile(conn, people.resolve(conn, "oleh@quokka.ua"))
    assert prof["scopes"] == ["quokka"] and prof["conversations"] == 1
    assert prof["recent"][0]["title"] == "Hello" and prof["last_interaction"]


async def test_person_tool_and_search_person_param(conn, pg_url, world):
    mail, tg, cfg = world
    send_mail(conn, mail, cfg, ("Budget", "Oleh K <oleh@quokka.ua>"))
    send_tg(conn, tg, cfg, tg_msg(1, "hi", 202, "Olena"))
    server = build_server(lambda: db.connect(pg_url), cfg)
    prof = (await call(server, "person", {"name_or_id": "oleh@quokka.ua"})).structured_content
    assert prof["display_name"] == "Oleh K"
    many = (await call(server, "person", {"name_or_id": "ole"})).structured_content
    assert len(many["candidates"]) >= 2
    hits = await call(server, "search", {"query": "budget", "person": "oleh@quokka.ua"})
    assert "Budget" in str(hits.structured_content)
    with pytest.raises(ToolError, match="no person matches"):
        await call(server, "search", {"query": "budget", "person": "nobody-here"})
