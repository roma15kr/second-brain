"""Meeting preparation (calendar-meetings spec; web-os-v1 task 13.2)."""

from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from kb import loops, meetings
from kb.routines import KYIV
from tests.test_brief_ai import FakeLlm

OWNER = {"me@example.com"}


def setup_calendar(conn):
    account = conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret) VALUES ('calendar', 'RDIM',"
        " '{\"type\": \"ical\"}', '') RETURNING id"
    ).fetchone()["id"]
    return conn.execute(
        "INSERT INTO calendars (account_id, href, name, sync, scopes)"
        " VALUES (%s, 'x', 'RDIM', true, '{rdim}') RETURNING id",
        (account,),
    ).fetchone()["id"]


def event(conn, cal, start, title="Dealer call", attendees=None):
    attendees = attendees or [
        {"email": "dealer@shop.example", "name": "Dealer", "status": "ACCEPTED"},
        {"email": "me@example.com", "name": "Me", "status": "ACCEPTED"},
    ]
    return conn.execute(
        "INSERT INTO events (calendar_id, uid, start_at, end_at, title, attendees, my_status)"
        " VALUES (%s, %s, %s, %s, %s, %s, 'ACCEPTED') RETURNING id",
        (cal, title, start, start + timedelta(minutes=30), title, Jsonb(attendees)),
    ).fetchone()["id"]


def prep_of(conn, eid):
    m = meetings.get(conn, eid)
    assert m is not None
    return m["prep"]


def test_prep_and_reminder_times():
    def due(start_local, now_local):
        r = {"start_at": start_local}
        return meetings.prep_due(r, now_local)

    k = lambda h, m=0: datetime(2026, 10, 20, h, m, tzinfo=KYIV)  # noqa: E731
    # an afternoon meeting: 30 minutes before
    assert not due(k(15), k(14, 29)) and due(k(15), k(14, 30))
    # an early meeting: from 07:00, so the 08:00 morning brief has it
    assert not due(k(9, 30), k(6, 59)) and due(k(9, 30), k(7, 0))
    assert not due(k(15), k(15, 1))  # already started


def test_prep_lists_people_history_loops_and_sourced_agenda(conn, config):
    cal = setup_calendar(conn)
    thread = conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, summary,"
        " identity_keys, last_activity_at)"
        " VALUES ('mail-test', 'q', 'email_thread', '{rdim}', 'Price list',"
        " 'Dealer asked for the Q4 price list', '{email:dealer@shop.example}', %s) RETURNING id",
        (datetime(2026, 10, 15, tzinfo=UTC),),
    ).fetchone()["id"]
    promise = conn.execute(
        "INSERT INTO loops (kind, title, counterpart, scopes, due_date) VALUES ('i_owe',"
        " 'Send the Q4 price list', 'Dealer <dealer@shop.example>', '{rdim}', '2026-10-21')"
        " RETURNING id"
    ).fetchone()["id"]
    loops.add_manual(conn, "Unrelated", datetime(2026, 10, 1, tzinfo=UTC), counterpart="Somebody")
    start = datetime(2026, 10, 20, 15, 0, tzinfo=KYIV)
    eid = event(conn, cal, start)
    llm = FakeLlm(
        {
            "agenda": [
                {"text": "Confirm the Q4 price list", "ref": f"loop:{promise}"},
                {"text": "Invented topic", "ref": "item:999"},
            ]
        }
    )
    assert meetings.prepare_due(conn, config, llm, start - timedelta(minutes=40)) == 0
    assert meetings.prepare_due(conn, config, llm, start - timedelta(minutes=30)) == 1
    prep = prep_of(conn, eid)
    assert [p["email"] for p in prep["people"]] == ["dealer@shop.example"]  # not the owner
    assert [c["ref"] for c in prep["conversations"]] == [f"item:{thread}"]
    assert [lp["title"] for lp in prep["loops"]] == ["Send the Q4 price list"]
    assert prep["agenda"] == [{"text": "Confirm the Q4 price list", "ref": f"loop:{promise}"}]
    assert "Dealer asked for the Q4 price list" in llm.calls[0]["text"]
    meetings.prepare_due(conn, config, llm, start - timedelta(minutes=20))
    assert len(llm.calls) == 1  # once
    # the reminder now says the prep is ready
    row = conn.execute(meetings.EVENT_SQL + " AND e.id = %s", (eid,)).fetchone()
    assert meetings.headline(dict(row)) == "15:00 Dealer call — 2 people, prep ready"


def test_prep_without_ai_still_lists_facts(conn, config):
    cal = setup_calendar(conn)
    start = datetime(2026, 10, 20, 9, 0, tzinfo=KYIV)
    eid = event(conn, cal, start)
    meetings.prepare_due(conn, config, None, datetime(2026, 10, 20, 7, 5, tzinfo=KYIV))
    prep = prep_of(conn, eid)
    assert prep["agenda"] == [] and prep["people"][0]["name"] == "Dealer"


def test_morning_brief_lists_meetings_before_ten(conn):
    from kb.routines import briefs

    cal = setup_calendar(conn)
    event(conn, cal, datetime(2026, 10, 20, 9, 0, tzinfo=KYIV), "Early sync")
    event(conn, cal, datetime(2026, 10, 20, 11, 0, tzinfo=KYIV), "Later call")
    items = briefs.early_meetings(conn, datetime(2026, 10, 20, 8, 0, tzinfo=KYIV))
    assert [i["title"] for i in items] == ["09:00 Early sync"]
    assert items[0]["link"].startswith("/meetings/")
