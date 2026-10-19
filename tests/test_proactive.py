"""Nudges, delegation and learning from discards (assistant-actions; web-os-v1 task 12.5)."""

from datetime import date, timedelta

import pytest
from psycopg.types.json import Jsonb

from kb.assistant import proactive, suggestions
from tests.test_brief_ai import FakeLlm
from tests.test_email_drafts import NOW, FakeSmtp, thread, web_client
from tests.test_priority import vec


def owed(conn, item, title="Customs documents", due=date(2026, 10, 18), who="Olga"):
    return conn.execute(
        "INSERT INTO loops (kind, title, item_id, counterpart, scopes, due_date, source_link)"
        " VALUES ('owed_to_me', %s, %s, %s, '{quokka}', %s, 'https://mail.google.com/x')"
        " RETURNING id",
        (title, item, who, due),
    ).fetchone()["id"]


def test_nudge_for_overdue_owed_to_me(conn, config):
    item = thread(conn)
    loop = owed(conn, item)
    owed(conn, thread(conn, "later"), "Price list", due=date(2026, 10, 25))  # not due yet
    llm = FakeLlm({"body": "Hi Olga, just checking on the customs documents. Thanks!"})
    assert proactive.cycle(conn, config, llm, NOW) == 1
    [s] = suggestions.listing(conn)
    assert s["kind"] == "nudge" and s["payload"]["loop_id"] == loop
    assert s["payload"]["channel"] == "email" and s["payload"]["body"].startswith("Hi Olga")
    assert s["reason"] == "Olga: Customs documents — 2 days overdue"
    assert "2 days overdue" in llm.calls[0]["text"]
    proactive.cycle(conn, config, llm, NOW + timedelta(hours=1))
    assert len(llm.calls) == 1  # one pending nudge per promise


def test_email_nudge_sent_in_thread_and_telegram_nudge_copied(conn, config):
    item = thread(conn)
    owed(conn, item)
    proactive.cycle(conn, config, FakeLlm({"body": "Any news?"}), NOW)
    [s] = suggestions.listing(conn)
    suggestions.send_on_tap(conn, s["id"], NOW)
    smtp = FakeSmtp()
    suggestions.apply_mail(
        conn,
        config,
        NOW + timedelta(seconds=11),
        open_imap=lambda b: None,
        open_smtp=lambda b: smtp,
    )
    [msg] = smtp.sent
    assert msg["In-Reply-To"] == "<m1@dealer.example>"
    tg = suggestions.propose(conn, "nudge", {"channel": "telegram", "body": "Any news?"})
    assert suggestions.approve(conn, tg, NOW) == "copied"
    assert suggestions.get(conn, tg)["status"] == "applied"


def task(conn, key, axis, assignee="Олена", email="olena@quokka.example", list_id="L1"):
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, metadata, embedding)"
        " VALUES ('clickup-1', %s, 'clickup_task', '{quokka}', %s, %s, %s::vector)",
        (
            key,
            f"task {key}",
            Jsonb(
                {
                    "assignees": [assignee],
                    "assignee_emails": [email],
                    "list_id": list_id,
                    "list": "Marketplaces",
                }
            ),
            vec(axis),
        ),
    )


def triaged(conn, item, axis):
    conn.execute(
        "UPDATE items SET embedding = %s::vector, last_activity_at = %s WHERE id = %s",
        (vec(axis), NOW, item),
    )
    brief = conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES ('revision', %s, %s, 'r', '[]', 'data') RETURNING id",
        (NOW, NOW),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO triage (brief_id, item_id, class) VALUES (%s, %s, 'needs_reply')",
        (brief, item),
    )


def test_delegate_matches_teammate_area(conn, config):
    for n in range(4):
        task(conn, f"photos{n}", axis=1)
    task(conn, "me", axis=1, assignee="Me", email="me@example.com")  # the owner is never chosen
    task(conn, "ads", axis=2, assignee="Макс", email="max@quokka.example")
    photos = thread(conn, "photos")
    triaged(conn, photos, axis=1)
    unrelated = thread(conn, "other")
    triaged(conn, unrelated, axis=3)
    assert proactive.cycle(conn, config, None, NOW) == 1
    [s] = suggestions.listing(conn)
    assert s["kind"] == "delegate" and s["item_id"] == photos
    assert s["payload"]["assignee_emails"] == ["olena@quokka.example"]
    assert s["payload"]["list_id"] == "L1" and s["payload"]["name"] == "Terms"
    assert s["reason"] == "Олена handles similar tasks (4 in Marketplaces)"
    proactive.cycle(conn, config, None, NOW)
    assert len(suggestions.listing(conn)) == 1  # once per email


def test_discard_rate_lowers_frequency(conn, config):
    for n in range(5):
        sid = suggestions.propose(conn, "nudge", {"channel": "telegram", "body": "x"})
        suggestions.discard(conn, sid, "not needed", NOW - timedelta(days=2, minutes=n))
    conn.execute("UPDATE suggestions SET created_at = now() - interval '2 days'")
    assert proactive.cooling(conn, "nudge")
    for n in range(3):
        owed(conn, thread(conn, f"k{n}"), f"Promise {n}")
    llm = FakeLlm({"body": "Any news?"})
    proactive.cycle(conn, config, llm, NOW)
    proactive.cycle(conn, config, llm, NOW + timedelta(hours=1))
    assert len(llm.calls) == 1  # cooling: at most one a day
    rates = {r["kind"]: r for r in proactive.acceptance(conn, NOW)}
    assert rates["nudge"]["rate"] == 0.0 and rates["nudge"]["cooling"] is True


@pytest.fixture
def client(conn, pg_url, config):
    return web_client(conn, pg_url, config)


def test_status_shows_acceptance_per_kind(client, conn):
    a = suggestions.propose(conn, "nudge", {"channel": "telegram", "body": "x"})
    suggestions.approve(conn, a, NOW)
    b = suggestions.propose(conn, "nudge", {"channel": "telegram", "body": "y"})
    suggestions.discard(conn, b, None, NOW)
    conn.execute("UPDATE suggestions SET decided_at = now()")
    [row] = client.get("/api/status").json()["suggestions"]
    assert row == {
        "kind": "nudge",
        "accepted": 1,
        "edited": 0,
        "discarded": 1,
        "rate": 0.5,
        "cooling": False,
    }
