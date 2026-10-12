"""People directory: one person across email addresses, Telegram accounts and phone numbers.

Messages and conversation items carry identity keys (`email:…`, `tg:<user id>`, `tgu:<username>`,
`phone:+…`). Each key belongs to exactly one person. Identities are linked automatically only on
exact matches (the same key, or keys seen together for one sender, e.g. a Telegram id and its
username); never by name. Merging and splitting move identities between people and are recorded,
so every merge — manual or automatic — can be undone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from kb.db import Conn


class PeopleError(ValueError):
    pass


# --- identity keys --------------------------------------------------------------------------


def email_key(address: str) -> str:
    return "email:" + address.strip().lower()


def phone_key(phone: str) -> str | None:
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 9:
        return None
    return "phone:+" + digits


def tg_keys(sender_id: Any, sender_name: str | None, phone: str | None = None) -> list[str]:
    keys = []
    if sender_id:
        keys.append(f"tg:{sender_id}")
    m = re.search(r"\(@([A-Za-z0-9_]{3,})\)", sender_name or "")
    if m:
        keys.append("tgu:" + m.group(1).lower())
    if phone and (pk := phone_key(phone)):
        keys.append(pk)
    return keys


def display_from_key(key: str) -> str:
    kind, _, value = key.partition(":")
    if kind == "email":
        return value.split("@")[0]
    return value


# --- registration and auto-linking -----------------------------------------------------------


def _person_of(conn: Conn, key: str) -> int | None:
    row = conn.execute("SELECT person_id FROM identities WHERE key = %s", (key,)).fetchone()
    return int(row["person_id"]) if row else None


def register(conn: Conn, keys: Iterable[str], display_name: str | None = None) -> int | None:
    """Make sure these keys exist; keys seen together for one sender belong to one person.
    Returns that person's id (None for no keys)."""
    keys = [k for k in dict.fromkeys(keys) if k]
    if not keys:
        return None
    owners = [p for p in (_person_of(conn, k) for k in keys) if p is not None]
    if owners:
        person = owners[0]
        for other in dict.fromkeys(owners[1:]):
            if other != person:
                merge(conn, person, other, reason="auto:" + keys[0])
    else:
        name = (display_name or display_from_key(keys[0])).strip() or keys[0]
        row = conn.execute(
            "INSERT INTO people (display_name) VALUES (%s) RETURNING id", (name,)
        ).fetchone()
        assert row is not None
        person = int(row["id"])
    for k in keys:
        conn.execute(
            """
            INSERT INTO identities (person_id, key, display_name) VALUES (%s, %s, %s)
            ON CONFLICT (key) DO NOTHING
            """,
            (person, k, display_name),
        )
    return person


# --- merge / split -------------------------------------------------------------------------


def _alive(conn: Conn, person_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM people WHERE id = %s", (person_id,)).fetchone()
    if row is None:
        raise PeopleError(f"no person with id {person_id}")
    if row["merged_into"]:
        raise PeopleError(f"person {person_id} was merged into {row['merged_into']}")
    return row


def merge(conn: Conn, keep: int, other: int, reason: str = "manual") -> int:
    """Move all identities of `other` to `keep`. Returns the merge id (for `split`)."""
    if keep == other:
        raise PeopleError("cannot merge a person with themselves")
    _alive(conn, keep)
    _alive(conn, other)
    moved = [
        r["id"]
        for r in conn.execute(
            "UPDATE identities SET person_id = %s WHERE person_id = %s RETURNING id", (keep, other)
        ).fetchall()
    ]
    conn.execute("UPDATE people SET merged_into = %s WHERE id = %s", (keep, other))
    row = conn.execute(
        "INSERT INTO person_merges (kept_id, merged_id, identity_ids, reason) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (keep, other, moved, reason),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def split(conn: Conn, merge_id: int) -> None:
    """Undo a merge: the identities it moved go back to the merged person."""
    m = conn.execute("SELECT * FROM person_merges WHERE id = %s", (merge_id,)).fetchone()
    if m is None:
        raise PeopleError(f"no merge with id {merge_id}")
    if m["undone_at"]:
        raise PeopleError(f"merge {merge_id} was already undone")
    conn.execute(
        "UPDATE identities SET person_id = %s WHERE id = ANY(%s)",
        (m["merged_id"], m["identity_ids"]),
    )
    conn.execute("UPDATE people SET merged_into = NULL WHERE id = %s", (m["merged_id"],))
    conn.execute("UPDATE person_merges SET undone_at = now() WHERE id = %s", (merge_id,))


def link(conn: Conn, person_id: int, key: str) -> int | None:
    """Attach an identity (e.g. 'phone:+380…' or 'email:x@y') to a person. If another person
    already has it, that person is merged in (recorded, so it can be split). Returns merge id."""
    _alive(conn, person_id)
    if ":" not in key:
        raise PeopleError("identity must look like email:a@b.c, phone:+380…, tg:<id> or tgu:<name>")
    kind, _, value = key.partition(":")
    if kind == "phone":
        normalized = phone_key(value)
        if normalized is None:
            raise PeopleError(f"not a phone number: {value!r}")
        key = normalized
    elif kind == "email":
        key = email_key(value)
    owner = _person_of(conn, key)
    if owner == person_id:
        return None
    if owner is not None:
        return merge(conn, person_id, owner, reason="manual-link:" + key)
    conn.execute("INSERT INTO identities (person_id, key) VALUES (%s, %s)", (person_id, key))
    return None


# --- lookup --------------------------------------------------------------------------------


def keys_of(conn: Conn, person_id: int) -> list[str]:
    return [
        r["key"]
        for r in conn.execute("SELECT key FROM identities WHERE person_id = %s", (person_id,))
    ]


def find(conn: Conn, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """People whose name or any identity contains `query` (case-insensitive)."""
    pattern = f"%{query.strip()}%"
    return conn.execute(
        """
        SELECT DISTINCT p.id, p.display_name FROM people p
        LEFT JOIN identities i ON i.person_id = p.id
        WHERE p.merged_into IS NULL
          AND (p.display_name ILIKE %(p)s OR i.key ILIKE %(p)s OR i.display_name ILIKE %(p)s)
        ORDER BY p.display_name LIMIT %(n)s
        """,
        {"p": pattern, "n": limit},
    ).fetchall()


def resolve(conn: Conn, ref: str | int) -> int:
    """A person id from an id or a name/identity fragment; ambiguous names list the candidates."""
    if isinstance(ref, int) or str(ref).strip().isdigit():
        pid = int(ref)
        person = conn.execute("SELECT * FROM people WHERE id = %s", (pid,)).fetchone()
        if person is None:
            raise PeopleError(f"no person with id {pid}")
        return int(person["merged_into"] or pid)
    found = find(conn, str(ref))
    if not found:
        raise PeopleError(f"no person matches {ref!r}")
    if len(found) > 1:
        options = "; ".join(f"{p['id']}: {p['display_name']}" for p in found)
        raise PeopleError(f"{ref!r} matches several people, pass one id: {options}")
    return int(found[0]["id"])


def profile(conn: Conn, person_id: int, recent: int = 5) -> dict[str, Any]:
    person = _alive(conn, person_id)
    idents = conn.execute(
        "SELECT key, display_name FROM identities WHERE person_id = %s ORDER BY key", (person_id,)
    ).fetchall()
    keys = [i["key"] for i in idents]
    stats = conn.execute(
        """
        SELECT min(occurred_at) AS first, max(last_activity_at) AS last, count(*) AS n
        FROM items WHERE NOT hidden AND kind <> 'passage' AND identity_keys && %s
        """,
        (keys,),
    ).fetchone()
    scope_rows = conn.execute(
        """
        SELECT DISTINCT unnest(scopes) AS s FROM items
        WHERE NOT hidden AND kind <> 'passage' AND identity_keys && %s
        """,
        (keys,),
    ).fetchall()
    convs = conn.execute(
        """
        SELECT id, kind, title, last_activity_at, summary FROM items
        WHERE NOT hidden AND kind <> 'passage' AND identity_keys && %s
        ORDER BY last_activity_at DESC NULLS LAST LIMIT %s
        """,
        (keys, recent),
    ).fetchall()
    names = sorted({i["display_name"] for i in idents if i["display_name"]})
    merges = conn.execute(
        "SELECT id, merged_id, reason FROM person_merges "
        "WHERE kept_id = %s AND undone_at IS NULL ORDER BY id",
        (person_id,),
    ).fetchall()
    return {
        "person_id": person_id,
        "display_name": person["display_name"],
        "names": names,
        "identities": keys,
        "scopes": sorted(r["s"] for r in scope_rows),
        "first_interaction": stats["first"].isoformat() if stats and stats["first"] else None,
        "last_interaction": stats["last"].isoformat() if stats and stats["last"] else None,
        "conversations": int(stats["n"]) if stats else 0,
        "recent": [
            {
                "item_id": c["id"],
                "kind": c["kind"],
                "title": c["title"],
                "last_activity_at": c["last_activity_at"].isoformat()
                if c["last_activity_at"]
                else None,
                "summary": c["summary"],
            }
            for c in convs
        ],
        "merges": [dict(m) for m in merges],
    }
