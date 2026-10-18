"""Web Push to the owner's devices (design D3).

Payloads carry only a headline and the page to open, never message content. Nothing is pushed
during quiet hours (the brief page is still produced). A subscription the push service reports
as gone (404/410) is deleted.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, time
from typing import Any

from pywebpush import WebPushException, webpush

from kb.db import Conn
from kb.routines import KYIV

log = logging.getLogger(__name__)

QUIET_START = time(22, 0)
QUIET_END = time(7, 30)
GONE = {404, 410}

Sender = Callable[..., Any]


def vapid_public_key() -> str:
    return os.environ.get("WEB_PUSH_VAPID_PUBLIC_KEY", "")


def in_quiet_hours(now: datetime, start: time = QUIET_START, end: time = QUIET_END) -> bool:
    t = now.astimezone(KYIV).time()
    return (t >= start or t < end) if start > end else start <= t < end


def payload(headline: str, url: str) -> str:
    return json.dumps({"title": "Second brain", "body": headline, "url": url})


def subscribe(conn: Conn, sub: dict[str, Any], device: str) -> int:
    keys = sub.get("keys") or {}
    if not sub.get("endpoint") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("subscription needs endpoint and keys.p256dh/auth")
    row = conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, device) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (endpoint) DO UPDATE SET p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth,"
        " device = EXCLUDED.device RETURNING id",
        (sub["endpoint"], keys["p256dh"], keys["auth"], device[:200]),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def unsubscribe(conn: Conn, endpoint: str) -> None:
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))


def send(
    conn: Conn,
    routine: str,
    headline: str,
    url: str,
    now: datetime,
    sender: Sender | None = None,
    only_endpoint: str | None = None,
) -> int:
    """Pushes to every device that wants this routine; returns how many accepted it."""
    if in_quiet_hours(now) and only_endpoint is None:
        log.info("quiet hours: no push for %s", routine)
        return 0
    private_key = os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY", "")
    subject = os.environ.get("WEB_PUSH_SUBJECT", "mailto:owner@example.com")
    if not private_key:
        log.warning("WEB_PUSH_VAPID_PRIVATE_KEY is not set; push disabled")
        return 0
    rows = conn.execute(
        "SELECT id, endpoint, p256dh, auth FROM push_subscriptions"
        " WHERE (%s::text IS NULL AND %s = ANY(routines)) OR endpoint = %s",
        (only_endpoint, routine, only_endpoint),
    ).fetchall()
    send_one = sender or webpush
    sent = 0
    for r in rows:
        info = {"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}}
        try:
            send_one(
                subscription_info=info,
                data=payload(headline, url),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                ttl=3600,
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in GONE:
                conn.execute("DELETE FROM push_subscriptions WHERE id = %s", (r["id"],))
                log.info("push subscription %s is gone; removed", r["id"])
            else:
                conn.execute(
                    "UPDATE push_subscriptions SET last_error = %s WHERE id = %s",
                    (str(e)[:500], r["id"]),
                )
            continue
        conn.execute(
            "UPDATE push_subscriptions SET last_sent_at = %s, last_error = NULL WHERE id = %s",
            (now, r["id"]),
        )
        sent += 1
    return sent


def notify_brief(conn: Conn, brief_id: int, now: datetime) -> int:
    row = conn.execute("SELECT routine, headline FROM briefs WHERE id = %s", (brief_id,)).fetchone()
    if row is None:
        return 0
    return send(conn, row["routine"], row["headline"], f"/briefs/{brief_id}", now)


def generate_vapid_keys() -> tuple[str, str]:
    """(public key for the browser, private key for the server), both base64url, one line."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    v = Vapid02()
    v.generate_keys()
    public = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    raw = v.private_key.private_numbers().private_value.to_bytes(32, "big")

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    return b64(public), b64(raw)
