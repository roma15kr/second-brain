"""Focus blocks, meeting load, declines, attention audit, neglected goals, decisions (13.5)."""

from datetime import UTC, datetime, timedelta

from kb import focus
from kb.assistant import suggestions
from kb.embed import vector_literal
from kb.routines import KYIV
from tests.test_brief_ai import FakeLlm
from tests.test_meeting_prep import event, setup_calendar

DAY = datetime(2026, 10, 20, tzinfo=KYIV)


def at(h, m=0, day=DAY):
    return day.replace(hour=h, minute=m)


def meeting(conn, cal, h, m, minutes, title="Sync", status="ACCEPTED", day=DAY):
    eid = event(conn, cal, at(h, m, day), title)
    conn.execute(
        "UPDATE events SET end_at = start_at + make_interval(mins => %s), my_status = %s"
        " WHERE id = %s",
        (minutes, status, eid),
    )
    return eid


def test_focus_blocks_and_meeting_load_warning(conn):
    cal = setup_calendar(conn)
    meeting(conn, cal, 9, 0, 60)
    meeting(conn, cal, 12, 30, 30)  # 10:00-12:30 is free (150 min); 13:00-18:00 free
    text = focus.focus_section(conn, at(8), [{"title": "Quokka launch plan"}, {"title": "Hiring"}])
    assert text is not None
    assert text.splitlines() == [
        "10:00-12:30 (2 h 30 min) → Quokka launch plan",
        "13:00-18:00 (5 h) → Hiring",
    ]
    # tomorrow: 5 of 9 working hours in meetings → the evening wrap warns
    tomorrow = DAY + timedelta(days=1)
    meeting(conn, cal, 9, 0, 120, "Board", day=tomorrow)
    meeting(conn, cal, 13, 0, 90, "Agency review", day=tomorrow)
    meeting(conn, cal, 15, 0, 90, "Dealer call", day=tomorrow)
    warning = focus.tomorrow_warning(conn, at(19))
    assert warning is not None
    assert warning.startswith("Tomorrow meetings fill 5 h of 9 h working hours.")
    assert "“Board” (09:00, 120 min)" in warning
    assert focus.tomorrow_warning(conn, at(19, day=DAY - timedelta(days=1))) is None
    heavy = focus.focus_section(conn, at(8, day=tomorrow), [])
    assert heavy is not None
    assert "⚠ Meetings fill 5 h of 9 h working hours today." in heavy


def test_declined_meetings_do_not_count(conn):
    cal = setup_calendar(conn)
    meeting(conn, cal, 9, 0, 480, "Offsite", status="DECLINED")
    assert focus.day_load(conn, DAY.date()).meeting_minutes == 0


def test_decline_suggestion_on_overloaded_day(conn, config):
    cal = setup_calendar(conn)  # scope rdim, no confirmed goal there
    tomorrow = DAY + timedelta(days=1)
    meeting(conn, cal, 9, 0, 300, "Workshop", day=tomorrow)
    invite = meeting(conn, cal, 15, 0, 60, "Vendor demo", status="NEEDS-ACTION", day=tomorrow)
    llm = FakeLlm({"body": "Дякую за запрошення, але цього дня мій графік заповнений."})
    assert focus.decline_suggestions(conn, config, llm, at(9)) == 1
    [s] = suggestions.listing(conn)
    assert s["kind"] == "decline" and s["payload"]["event_id"] == invite
    assert "serves no confirmed goal" in s["reason"]
    assert focus.decline_suggestions(conn, config, llm, at(10)) == 0  # once per invitation
    assert suggestions.approve(conn, s["id"], at(10)) == "copied"
    # a goal in that area: no decline suggestions
    conn.execute(
        "INSERT INTO goals (title, scope, status) VALUES ('Grow RDIM', 'rdim', 'confirmed')"
    )
    meeting(conn, cal, 16, 30, 60, "Another invite", status="NEEDS-ACTION", day=tomorrow)
    assert focus.decline_suggestions(conn, config, llm, at(11)) == 0


def test_neglected_goal_in_weekly_review(conn):
    def vec(axis):
        v = [0.0] * 1024
        v[axis] = 1.0
        return vector_literal(v)

    conn.execute(
        "INSERT INTO goals (title, scope, status, embedding) VALUES"
        " ('Run a half marathon', 'personal', 'confirmed', %s::vector),"
        " ('Launch Quokka on Prom', 'quokka', 'confirmed', %s::vector)",
        (vec(1), vec(2)),
    )
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, last_activity_at,"
        " embedding) VALUES ('mail-test', 'p', 'email_thread', '{quokka}', 'Prom listing',"
        " %s, %s::vector)",
        (DAY - timedelta(days=3), vec(2)),
    )
    [g] = focus.neglected_goals(conn, DAY)
    assert g["title"] == "Run a half marathon" and "Block 90 minutes" in g["first_step"]


def test_attention_and_decisions_of_the_week(conn):
    start = DAY - timedelta(days=1)
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, outcome,"
        " participants, last_activity_at) VALUES ('mail-test', 'd', 'email_thread', '{quokka}',"
        " 'Commission', 'Commission set at 5%%', '{Олена}', %s)",
        (DAY,),
    )
    conn.execute(
        "INSERT INTO goals (title, scope, status) VALUES ('Launch', 'quokka', 'confirmed')"
    )
    lines = focus.attention(conn, start, DAY + timedelta(days=1))
    assert lines[0] == "quokka: 1 conversations, 0 h meetings, 0 tasks · 1 goals"
    log = focus.decisions(conn, start, DAY + timedelta(days=1))
    [d] = log["quokka"]
    assert d["title"] == "Commission set at 5%" and d["summary"] == "Commission · Олена"
    assert d["link"].startswith("/c/")


def test_weekly_review_has_audit_sections(conn, config):
    from kb.routines import weekly

    conn.execute(
        "INSERT INTO goals (title, scope, status)"
        " VALUES ('Run a half marathon', 'personal', 'confirmed')"
    )
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, outcome,"
        " last_activity_at) VALUES ('mail-test', 'd', 'email_thread', '{quokka}', 'Commission',"
        " 'Commission set at 5%%', %s)",
        (datetime(2026, 10, 23, 10, tzinfo=UTC),),
    )
    bid = weekly.run_review(conn, datetime(2026, 10, 23, 16, tzinfo=UTC), None, config)
    titles = [
        s["title"]
        for s in conn.execute("SELECT sections FROM briefs WHERE id = %s", (bid,)).fetchone()[
            "sections"
        ]
    ]
    assert "Where attention went" in titles and "No progress (14 days)" in titles
    assert "Decisions · quokka" in titles
