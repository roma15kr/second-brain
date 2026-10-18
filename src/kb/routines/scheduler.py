"""Routine scheduler (design D4): runs each routine at its Kyiv-time slots, at most once per slot.

Only the latest due slot of a routine runs, and only within its catch-up window (the same local
day for daily routines, 24 h for weekly ones), so after downtime a routine runs once, not once
per missed slot. The unique (routine, slot) row makes runs idempotent across restarts and
duplicate schedulers. A failed run is retried once after 5 minutes.
"""

from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from kb.db import Conn
from kb.routines import KYIV, RoutineName

log = logging.getLogger(__name__)

DELAYED_AFTER = timedelta(minutes=5)
RETRY_AFTER = timedelta(minutes=5)
MAX_ATTEMPTS = 2
WEEKLY_CATCH_UP = timedelta(hours=24)

Runner = Callable[[Conn, datetime], int]  # returns the brief id


@dataclass(frozen=True)
class Slot:
    routine: RoutineName
    at: datetime  # aware, Kyiv


@dataclass(frozen=True)
class RoutineSettings:
    """Default schedule (assistant-routines spec); editable in Settings later."""

    morning: tuple[time, ...] = (time(8, 0),)
    revision: tuple[time, ...] = (time(11, 0), time(14, 0), time(17, 0))
    evening: tuple[time, ...] = (time(19, 0),)
    weekly_review: tuple[int, time] = (4, time(19, 0))  # Friday (Monday = 0)
    weekly_plan: tuple[int, time] = (0, time(8, 0))  # Monday
    daily: tuple[RoutineName, ...] = field(default=("morning", "revision", "evening"))


def _latest_daily(times: tuple[time, ...], local: datetime) -> datetime | None:
    """The latest slot today that is not in the future (same-day catch-up)."""
    due = [datetime.combine(local.date(), t, tzinfo=KYIV) for t in times]
    past = [d for d in due if d <= local]
    return max(past) if past else None


def _latest_weekly(weekday: int, at: time, local: datetime) -> datetime | None:
    days_back = (local.weekday() - weekday) % 7
    slot = datetime.combine(local.date() - timedelta(days=days_back), at, tzinfo=KYIV)
    if slot > local:
        slot -= timedelta(days=7)
    return slot if local - slot <= WEEKLY_CATCH_UP else None


def due_slots(settings: RoutineSettings, now: datetime) -> list[Slot]:
    local = now.astimezone(KYIV)
    slots: list[Slot] = []
    for name in settings.daily:
        times: tuple[time, ...] = getattr(settings, name)
        if (at := _latest_daily(times, local)) is not None:
            slots.append(Slot(name, at))
    for name in ("weekly_review", "weekly_plan"):
        weekday, at_time = getattr(settings, name)
        if (at := _latest_weekly(weekday, at_time, local)) is not None:
            slots.append(Slot(name, at))
    return slots


def claim(conn: Conn, slot: Slot, now: datetime) -> int | None:
    """Creates the run for a slot; None if it already exists (another run or scheduler had it)."""
    row = conn.execute(
        "INSERT INTO routine_runs (routine, slot, delayed, started_at) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (routine, slot) DO NOTHING RETURNING id",
        (slot.routine, slot.at, now - slot.at > DELAYED_AFTER, now),
    ).fetchone()
    return int(row["id"]) if row else None


def _retry(conn: Conn, slot: Slot, now: datetime) -> int | None:
    row = conn.execute(
        "UPDATE routine_runs SET status = 'running', attempts = attempts + 1, started_at = %s,"
        " error = NULL WHERE routine = %s AND slot = %s AND status = 'failed'"
        " AND attempts < %s AND finished_at <= %s RETURNING id",
        (now, slot.routine, slot.at, MAX_ATTEMPTS, now - RETRY_AFTER),
    ).fetchone()
    return int(row["id"]) if row else None


def run_due(
    conn: Conn,
    runners: dict[RoutineName, Runner],
    now: datetime,
    settings: RoutineSettings | None = None,
) -> list[int]:
    """Runs every due, unclaimed slot of the routines that have a runner; returns run ids."""
    ran = []
    for slot in due_slots(settings or RoutineSettings(), now):
        runner = runners.get(slot.routine)
        if runner is None:
            continue
        run_id = claim(conn, slot, now) or _retry(conn, slot, now)
        if run_id is None:
            continue
        try:
            brief_id = runner(conn, now)
        except Exception as e:  # one failing routine must not stop the others
            log.exception("routine %s failed", slot.routine)
            conn.execute(
                "UPDATE routine_runs SET status = 'failed', finished_at = %s, error = %s"
                " WHERE id = %s",
                (now, str(e)[:1000], run_id),
            )
        else:
            conn.execute(
                "UPDATE routine_runs SET status = 'done', finished_at = %s, brief_id = %s"
                " WHERE id = %s",
                (now, brief_id, run_id),
            )
        ran.append(run_id)
    return ran


def serve(
    connect: Callable[[], Conn],
    runners: dict[RoutineName, Runner],
    interval: float = 30.0,
    clock: Callable[[], datetime] | None = None,
) -> None:
    from datetime import UTC

    clock = clock or (lambda: datetime.now(UTC))
    log.info("routines scheduler started: %s", ", ".join(runners))
    while True:
        try:
            with connect() as conn:
                run_due(conn, runners, clock())
        except Exception:
            log.exception("scheduler cycle failed; retrying")
        _time.sleep(interval)
