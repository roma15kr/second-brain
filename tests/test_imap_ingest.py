from datetime import date, datetime

from kb import indexer
from kb.connectors import imap
from tests.fakes import FakeImap, make_email


def _count(conn, table):
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_ingest_idempotent_twice_same_rows(conn, source):
    fake = FakeImap()
    fake.add(1, make_email("Hello", "first"), datetime(2026, 9, 1))
    fake.add(2, make_email("Again", "second"), datetime(2026, 9, 2))
    assert imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10)) == 2
    assert imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10)) == 0
    assert _count(conn, "raw_records") == 2
    assert _count(conn, "jobs") == 2


def test_backfill_window_and_incremental_cursor(conn, source):
    fake = FakeImap()
    fake.add(1, make_email("Old", "too old"), datetime(2024, 1, 1))
    fake.add(2, make_email("Recent", "in window"), datetime(2026, 5, 1))
    assert imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10)) == 1
    fake.add(3, make_email("New", "arrived later"), datetime(2026, 10, 10))
    assert imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10)) == 1
    ids = {r["external_id"] for r in conn.execute("SELECT external_id FROM raw_records")}
    assert ids == {"INBOX:1:2", "INBOX:1:3"}


def test_uidvalidity_change_resyncs_window(conn, source):
    fake = FakeImap(uidvalidity=1)
    fake.add(1, make_email("A", "a"), datetime(2026, 9, 1))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    fake.uidvalidity = 2
    assert imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10)) == 1
    assert _count(conn, "raw_records") == 2  # archive keeps both; item dedupes by Message-ID


def test_reading_leaves_mail_unread(conn, source):
    fake = FakeImap()
    fake.add(1, make_email("Unread", "x"), datetime(2026, 9, 1))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    assert fake.readonly_selects == [True]
    assert all("BODY.PEEK[]" in call and "BODY[]" not in call for call in fake.fetch_calls)


def test_indexing_creates_one_item_per_message(conn, source, config):
    fake = FakeImap()
    raw = make_email("Invoice 4471", "Printing house invoice attached", message_id="<inv@x>")
    fake.add(1, raw, datetime(2026, 9, 1))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    fake.uidvalidity = 2  # same message archived again under a new UIDVALIDITY
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    while indexer.run_once(conn, config):
        pass
    items = conn.execute("SELECT * FROM items").fetchall()
    assert len(items) == 1
    assert items[0]["title"] == "Invoice 4471"
    assert items[0]["scopes"] == ["digisoft"]
    assert items[0]["locator"].startswith("imap://mail-test/INBOX;UID=")


def test_status_shows_cursor_and_server_next(conn, source):
    fake = FakeImap()
    fake.add(1, make_email("Hello", "first"), datetime(2026, 9, 1))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    fake.add(2, make_email("New", "second"), datetime(2026, 10, 10))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    assert imap.folder_cursors(conn, source.id) == [
        {"folder": "INBOX", "uidvalidity": 1, "cursor": 2, "server_next": 3}
    ]
