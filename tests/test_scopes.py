from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from tests.fakes import FakeImap, make_email

from kb import indexer, scopes
from kb.config import Config, ImapSource, ScopeRule, TelegramChat, TelegramSource
from kb.connectors import imap, telegram
from kb.scopes import Facts, ReviewError, Rule
from kb.search import SearchFilters, search

T0 = datetime(2026, 9, 1, 10, tzinfo=UTC)


def index_all(conn, config):
    while indexer.run_once(conn, config):
        pass


# --- resolver layers -------------------------------------------------------------------------

EMAIL = Facts("mail", "email", "oleh@quokka.ua", ("oleh@quokka.ua", "me@dgs.ai"), folder="INBOX")
TG = Facts("tg", "tg", "Oleh", ("Oleh",), chat_id=-1001, chat_username="quokka_team")


def test_scope_rule_beats_llm():
    calls = []

    def classifier(f):
        calls.append(f)
        return ["personal"], 0.99

    res = scopes.Resolver(
        config_rules=[Rule("domain", "quokka.ua", ("quokka",))], classify=classifier
    )
    assert res.resolve(EMAIL) == (["quokka"], "rule")
    assert calls == []


def test_low_confidence_is_unsorted():
    res = scopes.Resolver(classify=lambda f: (["digisoft"], 0.4))
    assert res.resolve(EMAIL) == (["unsorted"], "none")
    res = scopes.Resolver(classify=lambda f: (["digisoft"], 0.9))
    assert res.resolve(EMAIL) == (["digisoft"], "classifier")


def test_layer_order_review_then_rule_then_chat_then_source():
    src = TelegramSource(
        id="tg",
        type="telegram",
        scopes=["personal"],
        chats=[TelegramChat(chat=-1001, scopes=["rdim"])],
    )
    cfg = Config(sources=[src])
    base = scopes.Resolver(config=cfg)
    assert base.resolve(TG) == (["rdim"], "chat")
    other_chat = Facts("tg", "tg", chat_id=-2002)
    assert base.resolve(other_chat) == (["personal"], "source")
    with_rule = scopes.Resolver(
        config_rules=[Rule("chat", "@quokka_team", ("quokka",))], config=cfg
    )
    assert with_rule.resolve(TG) == (["quokka"], "rule")
    with_review = scopes.Resolver(
        db_rules=[Rule("chat", "-1001", ("digisoft",))],
        config_rules=[Rule("chat", "@quokka_team", ("quokka",))],
        config=cfg,
    )
    assert with_review.resolve(TG) == (["digisoft"], "review")


@pytest.mark.parametrize(
    "rule, facts, hit",
    [
        (Rule("address", "oleh@quokka.ua", ("quokka",)), EMAIL, True),
        (Rule("domain", "@quokka.ua", ("quokka",)), EMAIL, True),
        (
            Rule("domain", "quokka.ua", ("quokka",)),
            Facts("mail", "email", participants=("a@mail.quokka.ua",)),
            True,
        ),
        (
            Rule("domain", "quokka.ua", ("quokka",)),
            Facts("mail", "email", participants=("a@notquokka.ua",)),
            False,
        ),
        (
            Rule("folder", "Projects/RDIM", ("rdim",)),
            Facts("mail", "email", folder="projects/rdim"),
            True,
        ),
        (Rule("chat", "-1001", ("rdim",)), TG, True),
        (Rule("chat", "@QUOKKA_TEAM", ("quokka",)), TG, True),
        (Rule("address", "oleh@quokka.ua", ("quokka",), source_id="other"), EMAIL, False),
        (Rule("chat", "-1001", ("rdim",)), EMAIL, False),
    ],
)
def test_rule_matchers(rule, facts, hit):
    assert rule.matches(facts) is hit


def test_scope_rule_config_validation():
    with pytest.raises(ValidationError, match="exactly one"):
        ScopeRule(scopes=["rdim"], domain="a.ua", chat=1)
    with pytest.raises(ValidationError, match="one or more of personal"):
        ScopeRule(scopes=["unsorted"], domain="a.ua")


# --- integration -----------------------------------------------------------------------------


@pytest.fixture
def mixed(monkeypatch):
    monkeypatch.setenv("U", "me@dgs.ai")
    monkeypatch.setenv("P", "x")
    mail_src = ImapSource(id="mail", type="imap", host="h", username_env="U", password_env="P")
    tg_src = TelegramSource(id="tg", type="telegram", chats=[TelegramChat(chat=-1001)])
    cfg = Config(
        sources=[mail_src, tg_src], scope_rules=[ScopeRule(scopes=["quokka"], domain="quokka.ua")]
    )
    return mail_src, tg_src, cfg


def ingest_mail(conn, src, cfg, *mails):
    fake = FakeImap()
    for i, (subject, sender) in enumerate(mails, 1):
        fake.add(
            i,
            make_email(subject, f"body {subject}", sender=sender, message_id=f"<{i}@x>"),
            datetime(2026, 9, 1),
        )
    imap.sync_folder(conn, fake, src, "INBOX", today=date(2026, 10, 10))
    index_all(conn, cfg)


CHAT = telegram.ChatInfo(chat_id=-1001, title="Unmapped chat", username=None, peer_type="channel")


def tmsg(i, text, at):
    return SimpleNamespace(
        id=i,
        date=at,
        message=text,
        edit_date=None,
        sender=None,
        sender_id=7,
        reply_to=None,
        reactions=None,
        media=None,
    )


def test_config_domain_rule_scopes_email_and_rest_is_unsorted(conn, mixed):
    mail_src, _, cfg = mixed
    ingest_mail(conn, mail_src, cfg, ("Listing", "oleh@quokka.ua"), ("Newsletter", "news@shop.com"))
    assert search(conn, "Listing")[0].scopes == ["quokka"]
    assert search(conn, "Newsletter")[0].scopes == ["unsorted"]
    assert search(conn, "body", SearchFilters(scopes=["quokka"]))[0].title == "Listing"


def test_resolve_as_chat_rule_applies_to_existing(conn, mixed):
    _, tg_src, cfg = mixed
    telegram.on_message(conn, tg_src, CHAT, tmsg(1, "first", T0))
    telegram.on_message(conn, tg_src, CHAT, tmsg(2, "second", T0 + timedelta(hours=5)))
    index_all(conn, cfg)
    unsorted = scopes.list_unsorted(conn)
    assert len(unsorted) == 2
    out = scopes.assign(conn, cfg, unsorted[0]["id"], ["quokka"], apply_to="chat")
    assert "re-scoped 2 messages" in out
    assert scopes.list_unsorted(conn) == []
    telegram.on_message(conn, tg_src, CHAT, tmsg(3, "third", T0 + timedelta(days=1)))
    index_all(conn, cfg)
    assert search(conn, "third")[0].scopes == ["quokka"]


def test_apply_to_sender_and_item_override(conn, mixed):
    mail_src, _, cfg = mixed
    ingest_mail(conn, mail_src, cfg, ("Promo A", "news@shop.com"), ("Invoice", "billing@host.com"))
    promo = search(conn, "Promo")[0]
    scopes.assign(conn, cfg, promo.item_id, ["personal"], apply_to="sender")
    assert search(conn, "Promo")[0].scopes == ["personal"]
    ingest_mail(
        conn,
        mail_src,
        cfg,
        ("Promo A", "news@shop.com"),
        ("Invoice", "billing@host.com"),
        ("Promo B", "news@shop.com"),
    )
    assert search(conn, '"Promo B"')[0].scopes == ["personal"]
    invoice = search(conn, "Invoice")[0]
    scopes.assign(conn, cfg, invoice.item_id, ["digisoft", "rdim"])
    assert search(conn, "Invoice")[0].scopes == ["digisoft", "rdim"]
    assert scopes.rescope(conn, cfg) == 0  # overrides and rules are stable


def test_review_errors_are_clear(conn, mixed):
    mail_src, _, cfg = mixed
    ingest_mail(conn, mail_src, cfg, ("Hello", "a@b.com"))
    item = search(conn, "Hello")[0]
    with pytest.raises(ReviewError, match="valid scopes"):
        scopes.assign(conn, cfg, item.item_id, ["acme"])
    with pytest.raises(ReviewError, match="only works for Telegram"):
        scopes.assign(conn, cfg, item.item_id, ["rdim"], apply_to="chat")
    with pytest.raises(ReviewError, match="no item with id 999"):
        scopes.assign(conn, cfg, 999, ["rdim"])


def test_archived_scope_stops_sync_keeps_search(conn):
    src = TelegramSource(
        id="tg", type="telegram", chats=[TelegramChat(chat=-1001, scopes=["rdim"])]
    )
    cfg = Config(sources=[src])
    telegram.on_message(conn, src, CHAT, tmsg(1, "before archive", T0))
    index_all(conn, cfg)
    scopes.set_archived(conn, "rdim", True)
    assert telegram.on_message(conn, src, CHAT, tmsg(2, "after archive", T0)) is False
    index_all(conn, cfg)
    assert search(conn, "before") and not search(conn, "after")
    scopes.set_archived(conn, "rdim", False)
    assert telegram.on_message(conn, src, CHAT, tmsg(3, "resumed", T0)) is True


def test_imap_source_archived_only_when_all_scopes_archived():
    src = ImapSource(
        id="m",
        type="imap",
        host="h",
        username_env="U",
        password_env="P",
        scopes=["rdim", "digisoft"],
    )
    assert not scopes.imap_source_archived(src, {"rdim"})
    assert scopes.imap_source_archived(src, {"rdim", "digisoft"})


def test_config_change_triggers_rescope(conn, mixed):
    mail_src, tg_src, cfg = mixed
    ingest_mail(conn, mail_src, cfg, ("Report", "x@rdim.ua"))
    scopes.ensure_rules_current(conn, cfg)
    assert search(conn, "Report")[0].scopes == ["unsorted"]
    cfg2 = Config(
        sources=[mail_src, tg_src],
        scope_rules=[*cfg.scope_rules, ScopeRule(scopes=["rdim"], domain="rdim.ua")],
    )
    assert scopes.ensure_rules_current(conn, cfg2) == 1
    assert search(conn, "Report")[0].scopes == ["rdim"]
    assert scopes.ensure_rules_current(conn, cfg2) == 0
