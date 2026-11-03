"""AI reply drafts (assistant-actions: reply drafts; web-os-v1 task 12.4), with a stubbed LLM."""

from datetime import timedelta

import pytest
from psycopg.types.json import Jsonb

from kb import loops, settings_store
from kb.assistant import drafting, suggestions
from tests.test_brief_ai import FakeLlm
from tests.test_email_drafts import NOW, thread


@pytest.fixture(autouse=True)
def drafts_on(conn):
    """Automatic drafts were switched on before this mail arrived (only new mail is drafted)."""
    loops.set_setting(conn, "reply_drafts_since", (NOW - timedelta(days=1)).isoformat())


def owner_reply(conn, key, to, body, scopes="{quokka}"):
    conn.execute(
        "INSERT INTO messages (source_id, message_key, kind, unit_key, author, participants,"
        " sent_at, body, scopes, metadata) VALUES ('mail-test', %s, 'email', %s,"
        " 'Me <me@example.com>', %s, %s, %s, %s, %s)",
        (
            f"{key}-o",
            key,
            ["me@example.com", to],
            NOW - timedelta(days=30),
            body,
            scopes,
            Jsonb({"labels": []}),
        ),
    )


def context_item(conn, key, title, summary, private=False):
    return conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, summary,"
        " identity_keys, last_activity_at, metadata) VALUES ('mail-test', %s, 'email_thread',"
        " '{quokka}', %s, %s, '{email:olga@dealer.example}', %s, %s) RETURNING id",
        (key, title, summary, NOW - timedelta(days=40), Jsonb({"private": private})),
    ).fetchone()["id"]


def needs_reply(conn, key="q", at=NOW):
    item = thread(conn, key)
    loops.open_needs_reply(conn, item, "Answer Olga", at)
    return item


def test_draft_uses_tone_and_context_and_keeps_only_given_refs(conn, config):
    item = needs_reply(conn)
    terms = context_item(conn, "old", "Delivery terms", "Delivery in 5 days, prepaid.")
    secret = context_item(conn, "priv", "Private plan", "Never share.", private=True)
    owner_reply(conn, "old", "Olga <olga@dealer.example>", "From: me\n\nHi Olga,\nsure.\nRoman")
    llm = FakeLlm(
        {
            "body": "Hi Olga,\ndelivery is 5 days, prepaid.\nRoman",
            "refs": [f"item:{terms}", "item:999"],
        }
    )
    assert drafting.cycle(conn, config, llm, NOW) == 1
    [call] = llm.calls
    assert "Hi Olga,\nsure.\nRoman" in call["text"]  # the owner's earlier reply as tone example
    assert "Delivery in 5 days" in call["text"] and "Never share" not in call["text"]
    assert f"item:{secret}" not in call["text"]
    [s] = suggestions.listing(conn, "approved")  # straight to the mailbox's Drafts
    assert s["item_id"] == item and s["payload"]["body"].startswith("Hi Olga")
    assert s["payload"]["ai_pending"] is False and s["payload"]["auto"] is True
    assert s["payload"]["action"] == "draft" and s["payload"]["auto_saved"] is True
    assert suggestions.listing(conn) == []  # nothing waits in the approval queue
    assert sorted(s["refs"]) == sorted([f"item:{item}", f"item:{terms}"])  # item:999 dropped


def test_daily_cap_respected_one_per_cycle(conn, config):
    items = [needs_reply(conn, f"t{n}") for n in range(4)]
    for n, item in enumerate(items):  # t3 has waited longest
        conn.execute(
            "UPDATE loops SET opened_at = %s WHERE item_id = %s",
            (NOW - timedelta(days=n), item),
        )
    settings_store.save(conn, {"reply_drafts_per_day": 2})
    llm = FakeLlm({"body": "Ok", "refs": []})
    for minute in range(5):
        drafting.cycle(conn, config, llm, NOW + timedelta(minutes=minute))
    assert len(llm.calls) == 2 and drafting.drafted_today(conn, NOW) == 2
    drafted = [s["item_id"] for s in reversed(suggestions.listing(conn, "approved"))]
    assert drafted == [items[3], items[2]]
    drafting.cycle(conn, config, llm, NOW + timedelta(days=1))  # a new day, a new allowance
    assert len(llm.calls) == 3


def test_requested_draft_filled_but_owner_text_never_overwritten(conn, config):
    item = needs_reply(conn)
    settings_store.save(conn, {"reply_drafts_per_day": 0})
    sid = suggestions.reply_draft(conn, item)
    assert suggestions.get(conn, sid)["payload"]["ai_pending"] is True
    conn.execute(
        'UPDATE suggestions SET payload = payload || \'{"body": "my own words"}\' WHERE id = %s',
        (sid,),
    )
    llm = FakeLlm({"body": "AI words", "refs": []})
    drafting.cycle(conn, config, llm, NOW)
    p = suggestions.get(conn, sid)["payload"]
    assert p["body"] == "my own words" and p["ai_pending"] is False
    drafting.cycle(conn, config, llm, NOW + timedelta(minutes=1))
    assert len(llm.calls) == 1  # not retried every cycle


def test_no_drafts_over_budget(conn, config):
    needs_reply(conn)
    settings_store.save(conn, {"ai_budget_usd": 0})
    llm = FakeLlm({"body": "Ok", "refs": []})
    assert drafting.cycle(conn, config, llm, NOW) == 0 and llm.calls == []


def test_deleted_draft_not_recreated(conn, config):
    item = needs_reply(conn)
    llm = FakeLlm({"body": "Ok", "refs": []})
    drafting.cycle(conn, config, llm, NOW)
    # the owner deleted the draft in Gmail: the thread still waits, but gets no second draft
    drafting.cycle(conn, config, llm, NOW + timedelta(minutes=2))
    assert len(llm.calls) == 1
    # a new message in the thread is a new question
    conn.execute(
        "UPDATE items SET last_activity_at = %s WHERE id = %s", (NOW + timedelta(hours=1), item)
    )
    drafting.cycle(conn, config, llm, NOW + timedelta(hours=2))
    assert len(llm.calls) == 2


def test_newsletter_and_cc_get_no_draft(conn, config):
    bulk = needs_reply(conn, "bulk")
    cc = needs_reply(conn, "cc")
    robot = thread(conn, "robot", author="Allegro <no-reply@allegro.pl>")
    loops.open_needs_reply(conn, robot, "Answer", NOW)
    conn.execute(
        "UPDATE messages SET metadata = %s WHERE unit_key = 'bulk'",
        (Jsonb({"bulk": True, "to": ["me@example.com"]}),),
    )
    conn.execute(  # the owner is only in Cc
        "UPDATE messages SET metadata = %s WHERE unit_key = 'cc'",
        (Jsonb({"bulk": False, "to": ["team@quokka.example"]}),),
    )
    llm = FakeLlm({"body": "Ok", "refs": []})
    for minute in range(3):
        drafting.cycle(conn, config, llm, NOW + timedelta(minutes=minute))
    assert llm.calls == [] and bulk and cc


def test_only_new_mail_is_drafted(conn, config):
    needs_reply(conn)  # arrived at NOW
    loops.set_setting(conn, "reply_drafts_since", (NOW + timedelta(hours=1)).isoformat())
    llm = FakeLlm({"body": "Ok", "refs": []})
    drafting.cycle(conn, config, llm, NOW + timedelta(hours=2))
    assert llm.calls == []


def test_needed_reply_saved_as_draft(conn, config):
    from tests.fakes import FakeImap

    item = needs_reply(conn)
    llm = FakeLlm({"body": "Hi Olga,\nconfirmed.\nRoman", "refs": []})
    drafting.cycle(conn, config, llm, NOW)
    imap = FakeImap()
    imap.add_folder("Drafts", (b"\\Drafts",))
    assert suggestions.apply_mail(conn, config, NOW, open_imap=lambda box: imap) == 1
    [(raw, _, extra)] = imap.folders["Drafts"].values()
    assert extra[b"FLAGS"] == (b"\\Draft",) and imap.folders["INBOX"] == {}  # not sent
    assert b"confirmed." in raw and b"In-Reply-To: <m1@dealer.example>" in raw
    assert suggestions.get(conn, suggestions.listing(conn, "applied")[0]["id"])["item_id"] == item
