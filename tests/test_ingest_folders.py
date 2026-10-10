from datetime import date, datetime

import pytest

from kb import indexer
from kb.config import Config, ImapSource, ScopeRule
from kb.connectors import imap
from kb.search import search
from tests.fakes import FakeImap, make_email

TODAY = date(2026, 10, 10)


@pytest.fixture
def src(monkeypatch):
    monkeypatch.setenv("U", "me@example.com")
    monkeypatch.setenv("P", "x")
    return ImapSource(
        id="mail",
        type="imap",
        host="h",
        username_env="U",
        password_env="P",
        scopes=["digisoft"],
        backfill_batch=2,
    )


def index_all(conn, config):
    while indexer.run_once(conn, config):
        pass


def mail(subject, mid, body="hello"):
    return make_email(subject, body, message_id=mid)


def test_gmail_reads_only_all_mail_with_thread_ids_and_labels(conn, src):
    fake = FakeImap(gmail=True)
    fake.add_folder("[Gmail]/All Mail", (b"\\HasNoChildren", b"\\All"))
    fake.add_folder("[Gmail]/Spam", (b"\\Junk",))
    fake.add(
        1,
        mail("Offer v1", "<a@x>"),
        datetime(2026, 9, 1),
        folder="[Gmail]/All Mail",
        **{"X-GM-THRID": 777, "X-GM-MSGID": 1, "X-GM-LABELS": (b"\\Inbox", b"RDIM")},
    )
    # different subject, no References: only Gmail's thread id ties it to the first message
    fake.add(
        2,
        mail("Totally new subject", "<b@x>"),
        datetime(2026, 9, 2),
        folder="[Gmail]/All Mail",
        **{"X-GM-THRID": 777, "X-GM-MSGID": 2, "X-GM-LABELS": (b"\\Sent",)},
    )
    fake.add(3, mail("Spam!", "<c@x>"), datetime(2026, 9, 2), folder="[Gmail]/Spam")
    assert imap.discover_folders(fake, src) == ["[Gmail]/All Mail"]
    imap.sync(conn, fake, src)
    imap.sync(conn, fake, src)
    cfg = Config(sources=[src], scope_rules=[ScopeRule(scopes=["rdim"], folder="RDIM")])
    index_all(conn, cfg)
    threads = conn.execute("SELECT * FROM items WHERE NOT hidden").fetchall()
    assert len(threads) == 1 and threads[0]["metadata"]["message_count"] == 2
    assert threads[0]["source_item_key"] == "gmail:777"
    # labelled message → rule "rdim"; the other → mailbox default "digisoft"; thread holds both
    assert threads[0]["scopes"] == ["rdim", "digisoft"]
    assert search(conn, "Spam") == []
    assert all("X-GM-THRID" in call for call in fake.fetch_calls)


def test_inbox_copy_then_all_mail_merges_into_gmail_thread(conn, src):
    cfg = Config(sources=[src])
    old = FakeImap(gmail=False)  # first ingested INBOX-only, no Gmail ids
    old.add(1, mail("Budget", "<a@x>"), datetime(2026, 9, 1))
    imap.sync_folder(conn, old, src, "INBOX", today=TODAY)
    index_all(conn, cfg)
    fake = FakeImap(gmail=True)
    fake.add_folder("[Gmail]/All Mail", (b"\\All",))
    fake.add(
        1,
        mail("Budget", "<a@x>"),
        datetime(2026, 9, 1),
        folder="[Gmail]/All Mail",
        **{"X-GM-THRID": 5, "X-GM-MSGID": 1, "X-GM-LABELS": ()},
    )
    fake.add(
        2,
        mail("Re: other words", "<b@x>"),
        datetime(2026, 9, 2),
        folder="[Gmail]/All Mail",
        **{"X-GM-THRID": 5, "X-GM-MSGID": 2, "X-GM-LABELS": ()},
    )
    imap.sync(conn, fake, src)
    imap.sync(conn, fake, src)
    index_all(conn, cfg)
    [thread] = conn.execute("SELECT * FROM items WHERE NOT hidden").fetchall()
    assert thread["source_item_key"] == "gmail:5" and thread["metadata"]["message_count"] == 2


def test_generic_folder_discovery_skips_junk_trash_drafts_and_excluded(src):
    fake = FakeImap()
    for name, flags in [
        ("Sent", (b"\\Sent",)),
        ("Spam", ()),
        ("Trash", (b"\\Trash",)),
        ("Drafts", (b"\\Drafts",)),
        ("Архів", ()),
        ("Корзина", ()),
        ("Projects/Old", ()),
        ("Projects/Live", ()),
        ("Virtual", (b"\\All",)),
    ]:
        fake.add_folder(name, flags)
    src.exclude_folders = ["Projects/Old"]
    assert imap.discover_folders(fake, src) == ["INBOX", "Sent", "Архів", "Projects/Live"]
    src.folders = ["INBOX"]
    assert imap.discover_folders(fake, src) == ["INBOX"]


def five(fake):
    for uid in range(1, 6):
        fake.add(uid, mail(f"Old {uid}", f"<o{uid}@x>"), datetime(2026, 9, uid))


def test_restart_resumes_backfill_cursor(conn, src):
    fake = FakeImap()
    five(fake)
    assert imap.sync_folder(conn, fake, src, "INBOX", today=TODAY) == 2  # first chunk
    restarted = FakeImap()  # fresh connection after a restart, same mailbox
    five(restarted)
    assert imap.sync_folder(conn, restarted, src, "INBOX", today=TODAY) == 2
    assert imap.sync_folder(conn, restarted, src, "INBOX", today=TODAY) == 1
    assert imap.sync_folder(conn, restarted, src, "INBOX", today=TODAY) == 0
    assert imap.backfill_done(conn, "mail", "INBOX")
    n = conn.execute("SELECT count(*) AS n FROM raw_records").fetchone()["n"]
    assert n == 5


def test_new_mail_not_blocked_by_backfill(conn, src):
    fake = FakeImap()
    five(fake)
    imap.sync_folder(conn, fake, src, "INBOX", today=TODAY)  # backfill started, 3 left
    fake.add(6, mail("Fresh", "<new@x>"), datetime(2026, 10, 10))
    imap.sync_folder(conn, fake, src, "INBOX", today=TODAY)
    ids = {r["external_id"] for r in conn.execute("SELECT external_id FROM raw_records")}
    assert "INBOX:1:6" in ids  # new mail arrived while backfill still in progress
    assert not imap.backfill_done(conn, "mail", "INBOX")


def test_rebuild_from_archive_makes_no_connector_calls(conn, src):
    cfg = Config(sources=[src])
    fake = FakeImap()
    five(fake)
    for _ in range(3):
        imap.sync_folder(conn, fake, src, "INBOX", today=TODAY)
    index_all(conn, cfg)
    before = sorted(r["title"] for r in conn.execute("SELECT title FROM items WHERE NOT hidden"))
    calls = (len(fake.fetch_calls), len(fake.search_calls))
    conn.execute("UPDATE items SET raw_text = 'stale'")
    assert indexer.rebuild(conn, "mail") == 5
    index_all(conn, cfg)
    after = sorted(r["title"] for r in conn.execute("SELECT title FROM items WHERE NOT hidden"))
    assert after == before and before
    assert (
        conn.execute("SELECT count(*) AS n FROM items WHERE raw_text = 'stale'").fetchone()["n"]
        == 0
    )
    assert (len(fake.fetch_calls), len(fake.search_calls)) == calls
