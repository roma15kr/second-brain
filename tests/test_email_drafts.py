"""Reply drafts saved to the mailbox's Drafts, never sent (assistant-actions: propose, never
act alone; web-os-v1 task 12.1)."""

from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy

import pytest
from fastapi.testclient import TestClient

from kb import db, indexer, loops
from kb.api import auth
from kb.api.app import build_app
from kb.archive import RawRecord
from kb.assistant import suggestions
from kb.connectors.base import store
from tests.fakes import FakeImap, make_email
from tests.test_loops import reply

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CSRF = {"X-KB-Request": "1"}


def thread(conn, key="q", author="Olga <olga@dealer.example>"):
    item = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,"
        " last_activity_at) VALUES ('mail-test', %s, 'email_thread', '{quokka}', 'Terms',"
        " 'Can you confirm?', %s) RETURNING id",
        (key, NOW),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO messages (source_id, message_key, kind, unit_key, author, participants,"
        " sent_at, body, subject, refs) VALUES ('mail-test', %s, 'email', %s,"
        " %s, %s, %s, 'Can you confirm?', 'Terms', '{<m0@dealer.example>}')",
        (
            "<m1@dealer.example>" if key == "q" else f"<{key}@dealer.example>",
            key,
            author,
            [author, "me@example.com"],
            NOW - timedelta(hours=1),
        ),
    )
    return item


@pytest.fixture
def server():
    fake = FakeImap()
    fake.add_folder("Drafts", (b"\\Drafts",))
    return fake


def test_draft_saved_to_drafts_not_sent(conn, config, server):
    item = thread(conn)
    sid = suggestions.reply_draft(conn, item)
    assert suggestions.reply_draft(conn, item) == sid  # one pending draft per thread
    with pytest.raises(suggestions.SuggestionError, match="empty"):
        suggestions.approve(conn, sid, NOW)
    assert suggestions.approve(conn, sid, NOW, {"body": "Confirmed, thank you."}) == "queued"
    assert suggestions.apply_mail(conn, config, NOW, open_imap=lambda box: server) == 1
    [(raw, _, extra)] = server.folders["Drafts"].values()
    assert extra[b"FLAGS"] == (b"\\Draft",) and server.folders["INBOX"] == {}
    msg = message_from_bytes(raw, policy=policy.default)
    assert msg["To"] == "Olga <olga@dealer.example>" and msg["From"] == "me@example.com"
    assert msg["Subject"] == "Re: Terms" and msg["In-Reply-To"] == "<m1@dealer.example>"
    assert msg["References"] == "<m0@dealer.example> <m1@dealer.example>"
    assert "Confirmed, thank you." in msg.get_content()
    s = suggestions.get(conn, sid)
    assert s["status"] == "applied" and s["applied_ref"] == msg["Message-ID"]
    # a retry after a crash (status still approved) finds the saved draft
    conn.execute("UPDATE suggestions SET status = 'approved' WHERE id = %s", (sid,))
    suggestions.apply_mail(conn, config, NOW, open_imap=lambda box: server)
    assert len(server.folders["Drafts"]) == 1


def test_failed_draft_is_recorded_and_can_be_retried(conn, config):
    sid = suggestions.reply_draft(conn, thread(conn))
    suggestions.approve(conn, sid, NOW, {"body": "Yes"})
    no_drafts = FakeImap()
    assert suggestions.apply_mail(conn, config, NOW, open_imap=lambda box: no_drafts) == 0
    s = suggestions.get(conn, sid)
    assert s["status"] == "failed" and "Drafts" in s["error"]
    assert suggestions.approve(conn, sid, NOW) == "queued"  # retry keeps the edited body


def test_draft_not_ingested_and_loop_stays_open(conn, config):
    store(
        conn,
        RawRecord(
            source_id="mail-test",
            external_id="[Gmail]/All Mail:1:9",
            kind="email",
            occurred_at=NOW,
            payload={"folder": "[Gmail]/All Mail", "gm_thrid": "5", "gm_labels": ["Draft"]},
            blob=make_email("Re: Terms", "draft text", message_id="<kb-suggestion-1@example.com>"),
        ),
    )
    while indexer.run_once(conn, config):
        pass
    assert conn.execute("SELECT count(*) AS n FROM messages").fetchone()["n"] == 0
    # drafts already stored (label kept as Gmail returns it, without the backslash) are no reply
    item = thread(conn)
    loops.open_needs_reply(conn, item, "Answer Olga", NOW)
    reply(conn, "q", "Me <me@example.com>", NOW + timedelta(minutes=5), labels=["Draft"])
    assert loops.close_answered(conn, {"me@example.com"}, NOW + timedelta(hours=1)) == 0


@pytest.fixture
def client(conn, pg_url, config):
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_reply_draft_api_and_queue(client, conn):
    item = thread(conn)
    sid = client.post(f"/api/items/{item}/reply-draft", headers=CSRF).json()["id"]
    [pending] = client.get("/api/suggestions").json()["suggestions"]
    assert pending["id"] == sid and pending["item_title"] == "Terms"
    r = client.post(
        f"/api/suggestions/{sid}/approve", json={"payload": {"body": "Ok"}}, headers=CSRF
    )
    assert r.json() == {"applied_ref": "queued"}
    [recent] = client.get("/api/suggestions?status=recent").json()["suggestions"]
    assert recent["status"] == "approved" and recent["payload"]["body"] == "Ok"
    tg = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, title) VALUES ('tg', 'c1',"
        " 'tg_conversation', 'chat') RETURNING id"
    ).fetchone()["id"]
    assert client.post(f"/api/items/{tg}/reply-draft", headers=CSRF).status_code == 400


# --- send on tap (12.2) -------------------------------------------------------------------------


class FakeSmtp:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        pass


def test_send_only_after_tap_single_message(conn, config, server):
    item = thread(conn)
    loops.open_needs_reply(conn, item, "Answer Olga", NOW)
    sid = suggestions.reply_draft(conn, item)
    smtp = FakeSmtp()

    def run(at):
        suggestions.apply_mail(
            conn, config, at, open_imap=lambda b: server, open_smtp=lambda b: smtp
        )

    run(NOW)
    assert smtp.sent == []  # proposing sends nothing
    after = suggestions.send_on_tap(conn, sid, NOW, {"body": "Confirmed."})
    assert after == NOW + timedelta(seconds=10)
    run(NOW + timedelta(seconds=5))
    assert smtp.sent == []  # still inside the undo window
    run(NOW + timedelta(seconds=11))
    [msg] = smtp.sent
    assert msg["In-Reply-To"] == "<m1@dealer.example>" and msg["From"] == "me@example.com"
    run(NOW + timedelta(seconds=40))
    assert len(smtp.sent) == 1  # once
    assert suggestions.get(conn, sid)["status"] == "applied"
    assert conn.execute("SELECT status FROM loops").fetchone()["status"] == "done"
    assert server.folders["Drafts"] == {}  # sent, not saved as a draft


def test_sent_threaded_and_copied_to_sent_non_gmail(conn, config, server):
    server.add_folder("Sent", (b"\\Sent",))
    sid = suggestions.reply_draft(conn, thread(conn))
    smtp = FakeSmtp()
    suggestions.send_on_tap(conn, sid, NOW, {"body": "Confirmed."})
    suggestions.apply_mail(
        conn,
        config,
        NOW + timedelta(seconds=11),
        open_imap=lambda b: server,
        open_smtp=lambda b: smtp,
    )
    [(raw, _, extra)] = server.folders["Sent"].values()
    assert extra[b"FLAGS"] == (b"\\Seen",)
    assert message_from_bytes(raw)["Message-ID"] == smtp.sent[0]["Message-ID"]


def test_undo_within_10s_nothing_sent(conn, config, server):
    sid = suggestions.reply_draft(conn, thread(conn))
    smtp = FakeSmtp()
    suggestions.send_on_tap(conn, sid, NOW, {"body": "Confirmed."})
    suggestions.undo_send(conn, sid)
    suggestions.apply_mail(
        conn,
        config,
        NOW + timedelta(minutes=1),
        open_imap=lambda b: server,
        open_smtp=lambda b: smtp,
    )
    assert smtp.sent == []
    s = suggestions.get(conn, sid)
    assert s["status"] == "proposed" and s["payload"]["body"] == "Confirmed."  # back in the queue


def test_interrupted_send_is_not_repeated(conn, config, server):
    sid = suggestions.reply_draft(conn, thread(conn))
    suggestions.send_on_tap(conn, sid, NOW, {"body": "Confirmed."})
    conn.execute("UPDATE outbox SET status = 'sending'")  # crashed mid-send
    conn.execute("UPDATE suggestions SET status = 'applying'")
    smtp = FakeSmtp()
    suggestions.apply_mail(
        conn,
        config,
        NOW + timedelta(minutes=1),
        open_imap=lambda b: server,
        open_smtp=lambda b: smtp,
    )
    assert smtp.sent == []
    s = suggestions.get(conn, sid)
    assert s["status"] == "failed" and "Sent folder" in s["error"]
    with pytest.raises(suggestions.SuggestionError, match="too late"):
        suggestions.undo_send(conn, sid)


def test_no_bulk_send_endpoint(client):
    paths = client.app.openapi()["paths"]
    sending = sorted(
        p
        for p in paths
        if any(seg.startswith("send") and "sender" not in seg for seg in p.split("/"))
    )
    assert sending == ["/api/suggestions/{sid}/send"]
    r = client.post("/api/suggestions/send", json={"ids": [1, 2]}, headers=CSRF)
    assert r.status_code in (404, 405)
