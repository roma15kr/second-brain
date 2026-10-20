"""Owner settings for the web OS (design D9): schedule, mail passes, quiet hours, AI budget.

Stored as one JSON document in app_settings ('app'), validated by Pydantic, with defaults from
the assistant-routines spec. Readers call `load` each time, so a change applies to the next
scheduler cycle without a restart.
"""

from __future__ import annotations

from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from kb.config import Config
from kb.db import Conn

KEY = "app"


def _sorted_unique(values: list[time]) -> list[time]:
    return sorted(set(values))


class Schedule(BaseModel):
    morning: time = time(8, 0)
    revision: list[time] = Field(default_factory=lambda: [time(11, 0), time(14, 0), time(17, 0)])
    evening: time = time(19, 0)
    weekly_review_day: int = Field(default=4, ge=0, le=6)  # Monday = 0
    weekly_review_time: time = time(19, 0)
    weekly_plan_day: int = Field(default=0, ge=0, le=6)
    weekly_plan_time: time = time(8, 0)

    @field_validator("revision")
    @classmethod
    def _passes(cls, v: list[time]) -> list[time]:
        v = _sorted_unique(v)
        if len(v) > 8:
            raise ValueError("at most 8 mail revision passes a day")
        return v


class QuietHours(BaseModel):
    start: time = time(22, 0)
    end: time = time(7, 30)


class WorkingHours(BaseModel):
    start: time = time(9, 0)
    end: time = time(18, 0)


class AppSettings(BaseModel):
    schedule: Schedule = Schedule()  # pydantic copies defaults per instance
    quiet_hours: QuietHours = QuietHours()
    ai_budget_usd: float | None = Field(default=None, ge=0, le=1000)  # None: config default
    reply_drafts_per_day: int = Field(default=5, ge=0, le=20)  # owner decision 2026-10-18: 3-5
    working_hours: WorkingHours = WorkingHours()  # focus blocks and meeting load
    # cloud transcription of calls (when the Mac app is set to "Cloud" or speakers are asked for)
    calls_provider: Literal["openai-diarize", "openai-whisper", "groq"] = "openai-diarize"


class SettingsError(ValueError):
    pass


def load(conn: Conn) -> AppSettings:
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (KEY,)).fetchone()
    if row is None:
        return AppSettings()
    try:
        return AppSettings.model_validate(row["value"])
    except ValidationError:
        return AppSettings()  # never let a bad stored value stop the routines


def save(conn: Conn, data: dict[str, Any]) -> AppSettings:
    try:
        settings = AppSettings.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise SettingsError(f"{where}: {first['msg']}") from e
    from psycopg.types.json import Jsonb

    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (%s, %s) ON CONFLICT (key)"
        " DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (KEY, Jsonb(settings.model_dump(mode="json"))),
    )
    return settings


def budget_usd(conn: Conn, config: Config) -> float:
    s = load(conn)
    return s.ai_budget_usd if s.ai_budget_usd is not None else config.llm.monthly_budget_usd


def routine_settings(conn: Conn) -> Any:
    """The scheduler's RoutineSettings built from the stored schedule."""
    from kb.routines.scheduler import RoutineSettings

    s = load(conn).schedule
    return RoutineSettings(
        morning=(s.morning,),
        revision=tuple(s.revision),
        evening=(s.evening,),
        weekly_review=(s.weekly_review_day, s.weekly_review_time),
        weekly_plan=(s.weekly_plan_day, s.weekly_plan_time),
    )
