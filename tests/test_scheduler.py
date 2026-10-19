from datetime import datetime, time, timedelta
from typing import Any

import pytest

from kb.routines import KYIV
from kb.routines.scheduler import RoutineSettings, Slot, claim, due_slots, run_due


def k(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=KYIV)


def slots_at(now):
    return {(s.routine, s.at) for s in due_slots(RoutineSettings(), now)}


def test_due_slots_kyiv_dst():
    # Kyiv leaves summer time on Sun 25 Oct 2026: 08:00 local is 05:00 UTC before, 06:00 after.
    before = due_slots(RoutineSettings(), k(2026, 10, 24, 8, 1))
    after = due_slots(RoutineSettings(), k(2026, 10, 26, 8, 1))
    morning_before = next(s for s in before if s.routine == "morning").at
    morning_after = next(s for s in after if s.routine == "morning").at
    assert morning_before.utcoffset() == timedelta(hours=3)
    assert morning_after.utcoffset() == timedelta(hours=2)
    assert (morning_before.hour, morning_after.hour) == (8, 8)


def daily_at(now):
    return {(r, at) for r, at in slots_at(now) if not r.startswith("weekly")}


def test_default_tuesday_schedule():
    assert daily_at(k(2026, 10, 20, 7, 59)) == set()  # nothing due yet today
    assert daily_at(k(2026, 10, 20, 15, 0)) == {
        ("morning", k(2026, 10, 20, 8)),
        ("revision", k(2026, 10, 20, 14)),  # the latest pass only
    }
    assert ("evening", k(2026, 10, 20, 19)) in slots_at(k(2026, 10, 20, 19, 0))


def test_weekly_slots_and_catch_up_window():
    friday_evening = k(2026, 10, 23, 19, 0)
    assert ("weekly_review", friday_evening) in slots_at(k(2026, 10, 23, 19, 1))
    assert ("weekly_review", friday_evening) in slots_at(k(2026, 10, 24, 18, 0))  # within 24 h
    assert not any(r == "weekly_review" for r, _ in slots_at(k(2026, 10, 24, 20, 0)))
    assert ("weekly_plan", k(2026, 10, 26, 8)) in slots_at(k(2026, 10, 26, 8, 0))


def test_yesterdays_missed_slot_is_not_run_today():
    assert not any(r == "morning" for r, _ in slots_at(k(2026, 10, 21, 7, 0)))


def test_changed_time_moves_the_slot():
    settings = RoutineSettings(morning=(time(7, 30),))
    assert ("morning", k(2026, 10, 20, 7, 30)) in {
        (s.routine, s.at) for s in due_slots(settings, k(2026, 10, 20, 7, 31))
    }


def test_claim_is_idempotent(conn):
    slot = Slot("morning", k(2026, 10, 20, 8))
    first = claim(conn, slot, k(2026, 10, 20, 8, 0))
    assert first is not None
    assert claim(conn, slot, k(2026, 10, 20, 8, 0)) is None  # second scheduler / restart


def test_catch_up_once_after_downtime(conn):
    calls = []

    def morning(c, now):
        calls.append(now)
        return c.execute(
            "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
            " VALUES ('morning', %s, %s, 'h', '[]', 'data') RETURNING id",
            (now, now),
        ).fetchone()["id"]

    # Server down 07:00 to 09:30: one delayed morning brief at about 09:30, then nothing more.
    assert run_due(conn, {"morning": morning}, k(2026, 10, 20, 9, 30))
    assert run_due(conn, {"morning": morning}, k(2026, 10, 20, 9, 31)) == []
    assert len(calls) == 1
    run = conn.execute("SELECT * FROM routine_runs").fetchone()
    assert run["status"] == "done" and run["delayed"] is True and run["brief_id"] is not None


def test_on_time_run_is_not_delayed(conn):
    run_due(
        conn,
        {"morning": lambda c, now: _brief(c)},
        k(
            2026,
            10,
            20,
            8,
            0,
        ),
    )
    assert conn.execute("SELECT delayed FROM routine_runs").fetchone()["delayed"] is False


def _brief(c):
    return c.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES ('morning', now(), now(), 'h', '[]', 'data') RETURNING id"
    ).fetchone()["id"]


def test_failed_run_is_retried_once_after_five_minutes(conn):
    attempts = []

    def flaky(c, now):
        attempts.append(now)
        raise RuntimeError("OpenAI timeout")

    t0 = k(2026, 10, 20, 8, 0)
    run_due(conn, {"morning": flaky}, t0)
    assert run_due(conn, {"morning": flaky}, t0 + timedelta(minutes=2)) == []  # too early
    run_due(conn, {"morning": flaky}, t0 + timedelta(minutes=6))
    run_due(conn, {"morning": flaky}, t0 + timedelta(minutes=20))  # no third attempt
    assert len(attempts) == 2
    run = conn.execute("SELECT status, attempts, error FROM routine_runs").fetchone()
    assert run == {"status": "failed", "attempts": 2, "error": "OpenAI timeout"}


def test_routines_without_runner_are_not_claimed(conn):
    run_due(conn, {}, k(2026, 10, 20, 19, 0))
    assert conn.execute("SELECT count(*) AS n FROM routine_runs").fetchone()["n"] == 0


@pytest.mark.parametrize("argv", [["routines"]])
def test_kb_routines_starts_scheduler_with_morning_runner(argv, monkeypatch):
    from kb import cli
    from kb.routines import scheduler

    seen: dict[str, Any] = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("KB_CONFIG_YAML", "sources: []")
    monkeypatch.setattr(
        scheduler, "serve", lambda connect, runners, **kw: seen.update(runners, **kw)
    )
    cli.main(argv)
    assert "morning" in seen
    assert [t.__name__ for t in seen["maintenance"]] == [
        "close_answered_loops",
        "wake_snoozed",
        "push_clickup",
        "apply_mail",
        "draft_replies",
        "propose_actions",
        "clean_threads",
        "detect_loops",
        "propose_goals",
    ]
