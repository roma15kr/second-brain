"""Settings (web-dashboard spec: Settings page). Owner identities decide loop direction."""

from __future__ import annotations

from typing import Annotated, Any

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
