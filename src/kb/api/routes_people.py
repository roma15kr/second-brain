"""People, Person and Scope pages (web-dashboard spec)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb import loops, people, scopes
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


def _channels(keys: list[str]) -> list[str]:
    kinds = {k.split(":", 1)[0] for k in keys}
    return [
        c
        for c, ks in (("email", {"email"}), ("telegram", {"tg", "tgu"}), ("phone", {"phone"}))
        if kinds & ks
    ]


def _open_loops(conn: Conn, name: str, keys: list[str]) -> list[dict[str, Any]]:
    emails = [k.removeprefix("email:") for k in keys if k.startswith("email:")]
    return conn.execute(
        "SELECT id, kind, title, due_date FROM loops WHERE status = 'open' AND"
        " (counterpart ILIKE '%%' || %s || '%%' OR"
        "  EXISTS (SELECT 1 FROM unnest(%s::text[]) e WHERE counterpart ILIKE '%%' || e || '%%'))"
        " ORDER BY due_date NULLS LAST, id",
        (name, emails),
    ).fetchall()


@router.get("/api/people")
def list_people(
    request: Request, conn: Db, q: str | None = None, limit: int = 50
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    if q and q.strip():
        return {
            "people": [
                {"id": p["id"], "name": p["display_name"]} for p in people.find(conn, q, limit)
            ]
        }
    owner = [f"email:{e}" for e in loops.owner_emails(conn, request.app.state.config)]
    owner += [f"tg:{t}" for t in loops.owner_telegram_ids(conn)]
    rows = conn.execute(
        """
        WITH pk AS (
            SELECT p.id, p.display_name, array_agg(i.key) AS keys
            FROM people p JOIN identities i ON i.person_id = p.id
            WHERE p.merged_into IS NULL GROUP BY p.id
            HAVING NOT (array_agg(i.key) && %(owner)s::text[])
        )
        SELECT pk.id, pk.display_name, pk.keys, a.last, a.scopes, a.n
        FROM pk JOIN LATERAL (
            SELECT max(it.last_activity_at) AS last, count(DISTINCT it.id) AS n,
                   array_agg(DISTINCT s) AS scopes
            FROM items it, unnest(it.scopes) s
            WHERE NOT it.hidden AND it.kind <> 'passage' AND it.identity_keys && pk.keys
        ) a ON a.last IS NOT NULL
        ORDER BY a.last DESC LIMIT %(limit)s
        """,
        {"owner": owner, "limit": limit},
    ).fetchall()
    return {
        "people": [
            {
                "id": r["id"],
                "name": r["display_name"],
                "channels": _channels(list(r["keys"])),
                "scopes": sorted(r["scopes"] or []),
                "last_interaction": r["last"].isoformat(),
                "conversations": r["n"],
                "open_loops": len(_open_loops(conn, r["display_name"], list(r["keys"]))),
            }
            for r in rows
        ]
    }


@router.get("/api/people/{person_id}")
def person(conn: Db, person_id: int) -> dict[str, Any]:
    try:
        pid = people.resolve(conn, person_id)
        prof = people.profile(conn, pid, recent=10)
    except people.PeopleError as e:
        raise HTTPException(404, str(e)) from e
    prof["channels"] = _channels(prof["identities"])
    prof["open_loops"] = [
        {**dict(r), "due_date": r["due_date"].isoformat() if r["due_date"] else None}
        for r in _open_loops(conn, prof["display_name"], prof["identities"])
    ]
    return prof


@router.post("/api/people/{person_id}/merge")
def merge(conn: Db, person_id: int, other_id: Annotated[int, Body(embed=True)]) -> dict[str, int]:
    if other_id == person_id:
        raise HTTPException(400, "cannot merge a person with themselves")
    try:
        merge_id = people.merge(conn, person_id, other_id)
    except people.PeopleError as e:
        raise HTTPException(400, str(e)) from e
    return {"merge_id": merge_id}


@router.post("/api/people/merges/{merge_id}/undo")
def undo_merge(conn: Db, merge_id: int) -> dict[str, bool]:
    try:
        people.split(conn, merge_id)
    except people.PeopleError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.post("/api/people/{person_id}/link")
def link(conn: Db, person_id: int, key: Annotated[str, Body(embed=True)]) -> dict[str, Any]:
    try:
        merge_id = people.link(conn, person_id, key)
    except people.PeopleError as e:
        raise HTTPException(400, str(e)) from e
    return {"merged": merge_id}


@router.get("/api/scopes/{scope}")
def scope_page(conn: Db, scope: str) -> dict[str, Any]:
    if scope not in scopes.VALID:
        raise HTTPException(404, f"unknown scope {scope!r}; valid: {', '.join(scopes.VALID)}")
    now = datetime.now(UTC)
    week_ago, month_ago = now - timedelta(days=7), now - timedelta(days=30)
    days = conn.execute(
        "SELECT (last_activity_at AT TIME ZONE 'Europe/Kyiv')::date AS d, kind, count(*) AS n"
        " FROM items WHERE NOT hidden AND kind <> 'passage' AND %s = ANY(scopes)"
        " AND last_activity_at > %s GROUP BY d, kind ORDER BY d",
        (scope, week_ago),
    ).fetchall()
    key_people = conn.execute(
        "SELECT p, count(*) AS n FROM items, unnest(participants) p WHERE NOT hidden"
        " AND kind <> 'passage' AND %s = ANY(scopes) AND last_activity_at > %s"
        " GROUP BY p ORDER BY n DESC LIMIT 8",
        (scope, month_ago),
    ).fetchall()
    decisions = conn.execute(
        "SELECT id, title, outcome, last_activity_at, locator FROM items WHERE NOT hidden"
        " AND kind <> 'passage' AND %s = ANY(scopes) AND outcome IS NOT NULL AND outcome <> ''"
        " ORDER BY last_activity_at DESC LIMIT 10",
        (scope,),
    ).fetchall()
    return {
        "scope": scope,
        "archived": scope in scopes.archived(conn),
        "activity": [{"day": r["d"].isoformat(), "kind": r["kind"], "n": r["n"]} for r in days],
        "open_loops": loops.list_loops(conn, now, "open", scope=scope),
        "key_people": [{"name": r["p"], "conversations": r["n"]} for r in key_people],
        "decisions": [
            {
                "item_id": r["id"],
                "title": r["title"],
                "outcome": r["outcome"],
                "at": r["last_activity_at"].isoformat() if r["last_activity_at"] else None,
            }
            for r in decisions
        ],
    }


@router.post("/api/scopes/{scope}/archive")
def archive(conn: Db, scope: str, archived: Annotated[bool, Body(embed=True)]) -> dict[str, bool]:
    if scope not in scopes.VALID or scope == "unsorted":
        raise HTTPException(400, f"cannot archive {scope!r}")
    scopes.set_archived(conn, scope, archived)
    return {"archived": archived}
