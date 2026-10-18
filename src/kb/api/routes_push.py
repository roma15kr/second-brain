"""Push subscriptions per device (web-access spec)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb import push
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


@router.get("/api/push/key")
def key() -> dict[str, str]:
    return {"public_key": push.vapid_public_key()}


@router.post("/api/push/subscribe")
def subscribe(
    request: Request, conn: Db, subscription: Annotated[dict[str, Any], Body(embed=True)]
) -> dict[str, Any]:
    try:
        sid = push.subscribe(conn, subscription, request.headers.get("user-agent", ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": sid}


@router.post("/api/push/unsubscribe")
def unsubscribe(conn: Db, endpoint: Annotated[str, Body(embed=True)]) -> dict[str, bool]:
    push.unsubscribe(conn, endpoint)
    return {"ok": True}


@router.post("/api/push/test")
def test(conn: Db, endpoint: Annotated[str, Body(embed=True)]) -> dict[str, int]:
    sent = push.send(
        conn,
        "test",
        "Notifications work on this device",
        "/",
        datetime.now(UTC),
        only_endpoint=endpoint,
    )
    return {"sent": sent}
