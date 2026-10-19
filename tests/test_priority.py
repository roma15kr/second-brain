"""Email priority with reasons (assistant-actions; web-os-v1 task 12.3)."""

from datetime import timedelta

import pytest
from psycopg.types.json import Jsonb

from kb.assistant import priority
from kb.embed import vector_literal
from tests.test_email_drafts import NOW, web_client

OWNER = {"me@example.com"}


def vec(axis):
    v = [0.0] * 1024
    v[axis] = 1.0
    return vector_literal(v)


def email(conn, key, sender, body, at, title="Hello", scopes="{quokka}", axis=None, entities=()):
    item = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, last_activity_at,"
        " identity_keys, entities, embedding) VALUES ('mail-test', %s, 'email_thread', %s, %s,"
        " %s, %s, %s, %s::vector) RETURNING id",
        (
            key,
            scopes,
            title,
            at,
            [f"email:{sender}"],
            Jsonb(list(entities)),
            vec(axis) if axis is not None else None,
        ),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO messages (source_id, message_key, kind, unit_key, author, sent_at, body)"
        " VALUES ('mail-test', %s, 'email', %s, %s, %s, %s)",
        (f"<{key}>", key, f"Someone <{sender}>", at, f"From: {sender}\n\n{body}"),
    )
    return item


def goal(conn, title, scope, axis):
    conn.execute(
        "INSERT INTO goals (title, scope, status, embedding) VALUES (%s, %s, 'confirmed',"
        " %s::vector)",
        (title, scope, vec(axis)),
    )


def test_priority_goal_linked_first_with_reason(conn):
    goal(conn, "marketplace launch", "quokka", axis=1)
    plain = email(conn, "a", "x@shop.example", "Can we talk next week?", NOW, axis=2)
    linked = email(conn, "b", "y@shop.example", "About the launch plan?", NOW, axis=1)
    other_scope = email(conn, "c", "z@shop.example", "Launch?", NOW, scopes="{rdim}", axis=1)
    p = priority.assess(conn, [plain, linked, other_scope], OWNER, NOW)
    assert priority.ordered(p, [plain, linked, other_scope])[0] == linked
    assert p[linked].reason == "Quokka goal: marketplace launch"
    assert p[other_scope].goal_id is None  # a goal only counts within its project


def test_quadrants_from_features(conn):
    conn.execute("INSERT INTO sender_prefs (address, pref) VALUES ('boss@x.example', 'important')")
    urgent_important = email(conn, "a", "boss@x.example", "Need the contract signed today", NOW)
    important = email(conn, "b", "boss@x.example", "Thoughts on Q1 when you have time", NOW)
    urgent = email(conn, "c", "new@x.example", "Hi", NOW - timedelta(days=4))
    neither = email(conn, "d", "new@x.example", "fyi", NOW)
    p = priority.assess(conn, [urgent_important, important, urgent, neither], OWNER, NOW)
    assert p[urgent_important].quadrant == "do_now"
    assert p[urgent_important].reason == 'important sender · money or contract · deadline: "today"'
    assert p[important].quadrant == "schedule"
    assert p[urgent].quadrant == "delegate" and p[urgent].reason == "waiting 4 days"
    assert p[neither].quadrant == "drop"


def test_frequent_contact_amounts_and_quick_replies(conn):
    for n in range(8):
        email(conn, f"old{n}", "olga@dealer.example", "earlier", NOW - timedelta(days=n + 1))
    long_body = "Please review the attached proposal. " * 20
    item = email(
        conn,
        "q",
        "olga@dealer.example",
        long_body,
        NOW,
        entities=[{"type": "amount", "value": "12 000 EUR"}],
    )
    short = email(conn, "s", "olga@dealer.example", "Is 10:00 ok?", NOW)
    p = priority.assess(conn, [item, short], OWNER, NOW)
    assert "frequent contact (10 conversations in 90 days)" in p[item].reason
    assert "money: 12 000 EUR" in p[item].reason
    assert p[short].quick and not p[item].quick


@pytest.fixture
def client(conn, pg_url, config):
    return web_client(conn, pg_url, config)


def test_inbox_lists_needs_reply_by_priority(client, conn):
    goal(conn, "marketplace launch", "quokka", axis=1)
    brief = conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES ('revision', %s, %s, 'r', '[]', 'data') RETURNING id",
        (NOW, NOW),
    ).fetchone()["id"]
    plain = email(conn, "a", "x@shop.example", "Next week?", NOW, axis=2)
    linked = email(conn, "b", "y@shop.example", "Launch plan?", NOW - timedelta(hours=2), axis=1)
    for item in (plain, linked):
        conn.execute(
            "INSERT INTO triage (brief_id, item_id, class) VALUES (%s, %s, 'needs_reply')",
            (brief, item),
        )
    rows = client.get("/api/inbox").json()["groups"]["needs_reply"]
    assert [r["item_id"] for r in rows] == [linked, plain]
    assert rows[0]["priority"]["reason"] == "Quokka goal: marketplace launch"
    assert rows[0]["priority"]["quadrant"] == "schedule"
