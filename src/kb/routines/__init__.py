"""Assistant routines (web-os-v1): scheduled briefs built from the owner's own data."""

from typing import Literal
from zoneinfo import ZoneInfo

RoutineName = Literal["morning", "revision", "evening", "weekly_review", "weekly_plan"]
ROUTINES: tuple[RoutineName, ...] = (
    "morning",
    "revision",
    "evening",
    "weekly_review",
    "weekly_plan",
)
KYIV = ZoneInfo("Europe/Kyiv")
