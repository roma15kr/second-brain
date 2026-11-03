"""The owner's team (assistant-moderation-v1): names from Settings → My team, matched to ClickUp
members and People despite spelling variants (Anastasiya / Anastasia, Stetsenko / Stecenko)."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from kb.db import Conn

DEFAULT = ["Anastasiya Tarasova", "Kate Oleksyuk", "Bogdan Stetsenko", "Galyna Tkachenko"]

# transliteration variants of Ukrainian names, folded before comparing
_FOLD = [("iy", "i"), ("ii", "i"), ("yi", "i"), ("ya", "a"), ("ia", "a"), ("y", "i"), ("ts", "c"),
         ("kh", "h"), ("g", "h"), ("j", "i"), ("w", "v")]  # fmt: skip


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = re.sub(r"[^a-z ]", "", s)
    for a, b in _FOLD:
        s = s.replace(a, b)
    return " ".join(s.split())


def same_person(name: str, candidate: str, email: str = "") -> bool:
    """True when `candidate` (a ClickUp username or People name) or `email` is `name`."""
    want = _fold(name).split()
    if not want:
        return False
    got = _fold(candidate)
    if got and SequenceMatcher(None, " ".join(want), got).ratio() >= 0.85:
        return True
    parts = got.split()
    # the surname alone, or with the first initial in any order ("Oleksyuk K.", "A. Tarasova")
    if len(want) > 1:
        for i, p in enumerate(parts):
            if SequenceMatcher(None, want[-1], p).ratio() >= 0.85:
                others = parts[:i] + parts[i + 1 :]
                if not others or any(o[0] == want[0][0] for o in others):
                    return True
    local = _fold(email.split("@")[0].replace(".", " ")).split()
    # g.tkachenko@… or anastasiya.tarasova@…
    return (
        len(want) > 1
        and bool(local)
        and SequenceMatcher(None, want[-1], local[-1]).ratio() >= 0.85
        and local[0][0] == want[0][0]
    )


def names(conn: Conn) -> list[str]:
    from kb import settings_store

    return settings_store.load(conn).team


def clickup_members(conn: Conn, members: dict[str, dict[str, Any]]) -> dict[str, str]:
    """ClickUp user id → team member name, for the workspace's members."""
    out: dict[str, str] = {}
    for name in names(conn):
        for uid, m in members.items():
            if same_person(name, m.get("username") or "", m.get("email") or ""):
                out[uid] = name
    return out


def mentions(conn: Conn, text: str, owner_names: list[str]) -> bool:
    """Whether a text @mentions the owner or a team member (first name or full name)."""
    low = _fold(text)
    for name in [*owner_names, *names(conn)]:
        first = _fold(name).split()[:1]
        if first and re.search(rf"(^| )@?{re.escape(first[0])}\b", low) and "@" in text:
            return True
    return False
