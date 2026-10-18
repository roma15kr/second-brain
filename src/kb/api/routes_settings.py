"""Settings (web-dashboard spec: Settings page). Owner identities decide loop direction."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb import loops
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


@router.get("/api/settings/owner")
def get_owner(request: Request, conn: Db) -> dict[str, Any]:
    added = loops.get_setting(conn, "owner_emails", [])
    return {
        "emails": sorted(loops.owner_emails(conn, request.app.state.config)),
        "added_emails": added,
        "telegram_ids": sorted(loops.owner_telegram_ids(conn)),
    }


@router.put("/api/settings/owner")
def put_owner(
    conn: Db,
    emails: Annotated[list[str], Body(embed=True)],
    telegram_ids: Annotated[list[str], Body(embed=True)],
) -> dict[str, bool]:
    clean = sorted({e.strip().lower() for e in emails if e.strip()})
    if any("@" not in e for e in clean):
        raise HTTPException(400, "every email needs an @")
    ids = sorted({t.strip() for t in telegram_ids if t.strip()})
    if any(not t.lstrip("-").isdigit() for t in ids):
        raise HTTPException(400, "Telegram ids are numbers (see `kb telegram chats`)")
    loops.set_setting(conn, "owner_emails", clean)
    loops.set_setting(conn, "owner_telegram_ids", ids)
    return {"ok": True}


# --- app settings (schedule, passes, quiet hours, AI budget) ---------------------------------


@router.get("/api/settings")
def get_settings(request: Request, conn: Db) -> dict[str, Any]:
    from datetime import UTC, datetime

    from kb import distill, settings_store

    config = request.app.state.config
    return {
        "app": settings_store.load(conn).model_dump(mode="json"),
        "budget_default_usd": config.llm.monthly_budget_usd,
        "month_spend_usd": round(distill.month_spend_usd(conn, datetime.now(UTC).date()), 2),
    }


@router.put("/api/settings")
def put_settings(conn: Db, app: Annotated[dict[str, Any], Body(embed=True)]) -> dict[str, Any]:
    from kb import settings_store

    try:
        saved = settings_store.save(conn, app)
    except settings_store.SettingsError as e:
        raise HTTPException(400, str(e)) from e
    return {"app": saved.model_dump(mode="json")}


# --- push per device ------------------------------------------------------------------------

ROUTINE_NAMES = ["morning", "revision", "evening", "weekly_review", "weekly_plan"]


@router.get("/api/settings/push")
def push_devices(conn: Db) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT id, endpoint, device, routines, created_at, last_sent_at, last_error"
        " FROM push_subscriptions ORDER BY id"
    ).fetchall()
    return {
        "routines": ROUTINE_NAMES,
        "devices": [
            {
                "id": r["id"],
                "endpoint": r["endpoint"],
                "device": r["device"],
                "routines": list(r["routines"]),
                "created_at": r["created_at"].isoformat(),
                "last_sent_at": r["last_sent_at"].isoformat() if r["last_sent_at"] else None,
                "last_error": r["last_error"],
            }
            for r in rows
        ],
    }


@router.put("/api/settings/push/{sub_id}")
def push_routines(
    conn: Db, sub_id: int, routines: Annotated[list[str], Body(embed=True)]
) -> dict[str, bool]:
    bad = [r for r in routines if r not in ROUTINE_NAMES]
    if bad:
        raise HTTPException(400, f"unknown routines {bad}; valid: {', '.join(ROUTINE_NAMES)}")
    row = conn.execute(
        "UPDATE push_subscriptions SET routines = %s WHERE id = %s RETURNING id",
        (sorted(set(routines)), sub_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no device {sub_id}")
    return {"ok": True}


@router.delete("/api/settings/push/{sub_id}")
def push_remove(conn: Db, sub_id: int) -> dict[str, bool]:
    conn.execute("DELETE FROM push_subscriptions WHERE id = %s", (sub_id,))
    return {"ok": True}


# --- scope rules and unsorted review ---------------------------------------------------------


@router.get("/api/settings/rules")
def rules(conn: Db) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT id, kind, value, scopes, source_id, created_at FROM scope_rules ORDER BY id"
    ).fetchall()
    return {
        "rules": [
            {**dict(r), "scopes": list(r["scopes"]), "created_at": r["created_at"].isoformat()}
            for r in rows
        ]
    }


@router.post("/api/settings/rules")
def add_rule(
    request: Request,
    conn: Db,
    kind: Annotated[Literal["address", "domain", "chat", "folder"], Body(embed=True)],
    value: Annotated[str, Body(embed=True)],
    scopes: Annotated[list[str], Body(embed=True)],
) -> dict[str, Any]:
    from kb import scopes as scope_mod

    try:
        scope_mod.validate_scopes(scopes, scope_mod.known(conn))
    except scope_mod.ReviewError as e:
        raise HTTPException(400, str(e)) from e
    if not value.strip():
        raise HTTPException(400, "a rule needs a value")
    row = conn.execute(
        "INSERT INTO scope_rules (kind, value, scopes) VALUES (%s, %s, %s)"
        " ON CONFLICT (kind, value, source_id) DO UPDATE SET scopes = EXCLUDED.scopes"
        " RETURNING id",
        (kind, value.strip().lower(), scopes),
    ).fetchone()
    changed = scope_mod.rescope(conn, request.app.state.config)
    return {"id": row["id"] if row else None, "rescoped_messages": changed}


@router.delete("/api/settings/rules/{rule_id}")
def delete_rule(request: Request, conn: Db, rule_id: int) -> dict[str, int]:
    from kb import scopes as scope_mod

    conn.execute("DELETE FROM scope_rules WHERE id = %s", (rule_id,))
    return {"rescoped_messages": scope_mod.rescope(conn, request.app.state.config)}


@router.get("/api/unsorted")
def unsorted(conn: Db) -> dict[str, Any]:
    from kb import scopes as scope_mod

    return {
        "items": [
            {
                "item_id": r["id"],
                "kind": r["kind"],
                "title": r["title"],
                "participants": list(r["participants"]),
                "last_activity_at": r["last_activity_at"].isoformat()
                if r["last_activity_at"]
                else None,
            }
            for r in scope_mod.list_unsorted(conn, 100)
        ]
    }
