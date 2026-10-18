"""Scope assignment: which part of the owner's life a message belongs to.

Layers are tried in order and the first that yields scopes wins:
1. rules created from the unsorted review (stored in the database: the owner's latest decisions)
2. `scope_rules` from config
3. per-chat scopes of a Telegram source
4. the source's default scopes (e.g. one mailbox per project)
5. an AI classifier, when provided (slice 7), accepted only above a confidence threshold
6. `unsorted`
A per-item override (unsorted review without "apply to") replaces a unit's scopes entirely.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from kb.config import SCOPES, Config, ConfigError, ImapSource, Source, TelegramSource
from kb.connectors.base import get_state, set_state
from kb.db import Conn

log = logging.getLogger(__name__)

CLASSIFIER_MIN_CONFIDENCE = 0.7
VALID = (*SCOPES,)


@dataclass(frozen=True)
class Facts:
    """What rules can look at for one message."""

    source_id: str
    kind: str  # 'email' | 'tg'
    author: str | None = None
    participants: tuple[str, ...] = ()
    chat_id: int | None = None
    chat_username: str | None = None
    folder: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    kind: str  # address | domain | chat | folder
    value: str
    scopes: tuple[str, ...]
    source_id: str | None = None

    def matches(self, f: Facts) -> bool:
        if self.source_id and self.source_id != f.source_id:
            return False
        v = self.value.strip().lower()
        if self.kind == "address":
            return f.kind == "email" and v in {p.lower() for p in f.participants}
        if self.kind == "domain":
            d = v.lstrip("@")
            return f.kind == "email" and any(
                p.lower().endswith("@" + d) or p.lower().endswith("." + d) for p in f.participants
            )
        if self.kind == "chat":
            if f.kind != "tg":
                return False
            if v.lstrip("-").isdigit():
                return f.chat_id == int(v)
            return bool(f.chat_username) and v.lstrip("@") == (f.chat_username or "").lower()
        if self.kind == "folder":  # mail folder or Gmail label
            return f.kind == "email" and v in {
                (f.folder or "").lower(),
                *(x.lower() for x in f.labels),
            }
        return False


Classifier = Callable[[Facts], tuple[list[str], float]]


@dataclass
class Resolver:
    db_rules: list[Rule] = field(default_factory=list)
    config_rules: list[Rule] = field(default_factory=list)
    config: Config | None = None
    classify: Classifier | None = None

    def resolve(self, f: Facts) -> tuple[list[str], str]:
        """Return (scopes, decided_by)."""
        for layer, rules in (("review", self.db_rules), ("rule", self.config_rules)):
            found = _union(r.scopes for r in rules if r.matches(f))
            if found:
                return found, layer
        source = _source(self.config, f.source_id)
        if isinstance(source, TelegramSource) and f.chat_id is not None:
            chat = source.chat_config(f.chat_id, f.chat_username)
            if chat and chat.scopes:
                return list(chat.scopes), "chat"
        if source is not None and list(source.scopes) != ["unsorted"]:
            return list(source.scopes), "source"
        if self.classify is not None:
            scopes, confidence = self.classify(f)
            scopes = [s for s in scopes if s in VALID]
            if scopes and confidence >= CLASSIFIER_MIN_CONFIDENCE:
                return scopes, "classifier"
        return ["unsorted"], "none"


def _union(groups: Iterable[Iterable[str]]) -> list[str]:
    out: list[str] = []
    for g in groups:
        for s in g:
            if s not in out:
                out.append(s)
    return out


def _source(config: Config | None, source_id: str) -> Source | None:
    if config is None:
        return None
    try:
        return config.source(source_id)
    except ConfigError:
        return None


def config_rules(config: Config) -> list[Rule]:
    rules = []
    for r in config.scope_rules:
        kind = next(k for k in ("address", "domain", "chat", "folder") if getattr(r, k))
        rules.append(Rule(kind, str(getattr(r, kind)), tuple(r.scopes), r.source))
    return rules


def db_rules(conn: Conn) -> list[Rule]:
    rows = conn.execute("SELECT kind, value, scopes, source_id FROM scope_rules ORDER BY id")
    return [Rule(r["kind"], r["value"], tuple(r["scopes"]), r["source_id"]) for r in rows]


def resolver(conn: Conn, config: Config, classify: Classifier | None = None) -> Resolver:
    from kb.connectors import accounts

    effective = accounts.effective_config(conn, config)  # + mailboxes connected in the web OS
    return Resolver(db_rules(conn), config_rules(config), effective, classify)


def facts_from_row(row: dict[str, Any]) -> Facts:
    md = row.get("metadata") or {}
    return Facts(
        source_id=row["source_id"],
        kind=row["kind"],
        author=row.get("author"),
        participants=tuple(row.get("participants") or ()),
        chat_id=row.get("chat_id"),
        chat_username=md.get("chat_username"),
        folder=md.get("folder"),
        labels=tuple(md.get("labels") or ()),
    )


# --- re-scoping existing messages -------------------------------------------------------


def rescope(conn: Conn, config: Config, where: str = "TRUE", params: Any = None) -> int:
    """Recompute scopes for stored messages (optionally filtered) and rebuild changed units.
    Returns the number of messages whose scopes changed."""
    from kb import units

    res = resolver(conn, config)
    rows = conn.execute(
        f"SELECT id, source_id, kind, unit_key, scopes, author, participants, chat_id, metadata "
        f"FROM messages WHERE {where}",
        params or (),
    ).fetchall()
    changed_units: set[tuple[str, str]] = set()
    changed = 0
    for row in rows:
        scopes, _ = res.resolve(facts_from_row(row))
        if list(row["scopes"]) != scopes:
            conn.execute("UPDATE messages SET scopes = %s WHERE id = %s", (scopes, row["id"]))
            changed_units.add((row["source_id"], row["unit_key"]))
            changed += 1
    for source_id, unit_key in changed_units:
        units.rebuild(conn, source_id, unit_key)
    return changed


def rules_fingerprint(config: Config) -> str:
    data = {
        "rules": [r.model_dump() for r in config.scope_rules],
        "sources": [
            {
                "id": s.id,
                "scopes": list(s.scopes),
                "chats": [c.model_dump() for c in s.chats] if isinstance(s, TelegramSource) else [],
            }
            for s in config.sources
        ],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def ensure_rules_current(conn: Conn, config: Config) -> int:
    """Re-scope everything when the scope configuration changed since the last run."""
    fp = rules_fingerprint(config)
    state = get_state(conn, "_scopes", "fingerprint") or {}
    if state.get("fingerprint") == fp:
        return 0
    n = rescope(conn, config)
    set_state(conn, "_scopes", "fingerprint", {"fingerprint": fp})
    log.info("scope configuration changed: re-scoped %d messages", n)
    return n


# --- unsorted review ------------------------------------------------------------------------


class ReviewError(ValueError):
    pass


def known(conn: Conn) -> tuple[str, ...]:
    """Scopes the owner can use: personal, the four initial projects and projects added in the
    web OS (scope-assignment spec: projects can be added)."""
    rows = conn.execute("SELECT name FROM projects ORDER BY created_at, name").fetchall()
    extra = tuple(r["name"] for r in rows if r["name"] not in VALID)
    return (*VALID, *extra)


def validate_scopes(scopes: list[str], valid: tuple[str, ...] = VALID) -> list[str]:
    bad = [s for s in scopes if s not in valid]
    if bad or not scopes:
        raise ReviewError(f"unknown scope(s) {bad}; valid scopes: {', '.join(valid)}")
    return scopes


def list_unsorted(conn: Conn, limit: int = 50) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, source_id, kind, title, participants, last_activity_at,
               metadata->>'message_count' AS messages
        FROM items WHERE NOT hidden AND 'unsorted' = ANY(scopes)
        ORDER BY last_activity_at DESC NULLS LAST LIMIT %s
        """,
        (limit,),
    ).fetchall()


def assign(
    conn: Conn, config: Config, item_id: int, scopes: list[str], apply_to: str | None = None
) -> str:
    """Resolve an item's scope. apply_to: None (this item only), 'chat' (Telegram chat),
    'sender' (email sender address). Returns a description of what was done."""
    from kb import units

    validate_scopes(scopes, known(conn))
    item = conn.execute("SELECT * FROM items WHERE id = %s", (item_id,)).fetchone()
    if item is None:
        raise ReviewError(f"no item with id {item_id}")
    first = conn.execute(
        "SELECT * FROM messages WHERE source_id = %s AND unit_key = %s "
        "ORDER BY sent_at, id LIMIT 1",
        (item["source_id"], item["source_item_key"]),
    ).fetchone()
    if first is None:
        raise ReviewError(f"item {item_id} has no messages")
    if apply_to is None:
        conn.execute(
            """
            INSERT INTO scope_overrides (source_id, unit_key, scopes) VALUES (%s, %s, %s)
            ON CONFLICT (source_id, unit_key) DO UPDATE SET scopes = EXCLUDED.scopes
            """,
            (item["source_id"], item["source_item_key"], scopes),
        )
        units.rebuild(conn, item["source_id"], item["source_item_key"])
        return f"item {item_id} → {', '.join(scopes)}"
    params: tuple[Any, ...]
    if apply_to == "chat":
        if first["kind"] != "tg":
            raise ReviewError(
                "--apply-to-chat only works for Telegram items; use --apply-to-sender"
            )
        kind, value = "chat", str(first["chat_id"])
        where, params = "source_id = %s AND chat_id = %s", (item["source_id"], first["chat_id"])
    elif apply_to == "sender":
        if first["kind"] != "email" or not first["author"]:
            raise ReviewError("--apply-to-sender only works for email items; use --apply-to-chat")
        kind, value = "address", first["author"].lower()
        where, params = "kind = 'email' AND %s = ANY(participants)", (value,)
    else:
        raise ReviewError("apply_to must be 'chat', 'sender' or omitted")
    conn.execute(
        """
        INSERT INTO scope_rules (kind, value, source_id, scopes) VALUES (%s, %s, %s, %s)
        ON CONFLICT (kind, value, source_id) DO UPDATE SET scopes = EXCLUDED.scopes
        """,
        (kind, value, item["source_id"], scopes),
    )
    n = rescope(conn, config, where, params)
    return f"rule {kind}={value} → {', '.join(scopes)}; re-scoped {n} messages"


# --- archived scopes ------------------------------------------------------------------------


def archived(conn: Conn) -> set[str]:
    return {r["scope"] for r in conn.execute("SELECT scope FROM archived_scopes")}


def set_archived(conn: Conn, scope: str, on: bool) -> None:
    validate_scopes([scope])
    if on:
        conn.execute(
            "INSERT INTO archived_scopes (scope) VALUES (%s) ON CONFLICT DO NOTHING", (scope,)
        )
    else:
        conn.execute("DELETE FROM archived_scopes WHERE scope = %s", (scope,))


def only_archived(scopes: Iterable[str], archived_set: set[str]) -> bool:
    """True when every scope is archived (so the thing should stop syncing)."""
    s = set(scopes)
    return bool(s) and s <= archived_set


def imap_source_archived(source: ImapSource, archived_set: set[str]) -> bool:
    return only_archived(source.scopes, archived_set)
