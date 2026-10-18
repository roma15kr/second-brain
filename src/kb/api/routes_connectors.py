"""Connectors hub (connectors spec): projects and accounts connected from the web OS."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from kb import scopes, secrets
from kb.api.deps import get_conn
from kb.connectors import accounts
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]
PROJECT_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


# --- projects ---------------------------------------------------------------------------------


@router.get("/api/projects")
def projects(conn: Db) -> dict[str, Any]:
    archived = scopes.archived(conn)
    rows = conn.execute("SELECT name, label FROM projects ORDER BY created_at, name").fetchall()
    return {
        "projects": [
            {"name": r["name"], "label": r["label"], "archived": r["name"] in archived}
            for r in rows
        ]
    }


@router.post("/api/projects")
def add_project(
    conn: Db,
    name: Annotated[str, Body(embed=True)],
    label: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, str]:
    name = name.strip().lower()
    if not PROJECT_NAME.match(name) or name == "unsorted":
        raise HTTPException(400, "a project name is 2-31 lowercase letters, digits, - or _")
    if conn.execute("SELECT 1 FROM projects WHERE name = %s", (name,)).fetchone():
        raise HTTPException(400, f"project {name!r} already exists")
    conn.execute(
        "INSERT INTO projects (name, label) VALUES (%s, %s)", (name, (label or name).strip())
    )
    return {"name": name}


@router.patch("/api/projects/{name}")
def rename_project(conn: Db, name: str, label: Annotated[str, Body(embed=True)]) -> dict[str, bool]:
    row = conn.execute(
        "UPDATE projects SET label = %s WHERE name = %s RETURNING name", (label.strip(), name)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no project {name!r}")
    return {"ok": True}


# --- mailboxes --------------------------------------------------------------------------------


class MailboxIn(BaseModel):
    preset: Literal["gmail", "imap"] = "gmail"
    label: str = ""
    address: str
    password: str = Field(min_length=1)
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: Literal["ssl", "starttls"] = "ssl"
    smtp_username: str | None = None
    smtp_password: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["unsorted"])


@router.get("/api/connectors/mail")
def mailboxes(conn: Db) -> dict[str, Any]:
    return {"mailboxes": accounts.list_mailboxes(conn)}


@router.post("/api/connectors/mail")
def connect_mailbox(conn: Db, mailbox: Annotated[MailboxIn, Body(embed=True)]) -> dict[str, int]:
    m = accounts.Mailbox(**{**mailbox.model_dump(), "scopes": tuple(mailbox.scopes)})
    try:
        account_id = accounts.add_mailbox(conn, m, scopes.known(conn), datetime.now(UTC))
    except accounts.ConnectorError as e:
        raise HTTPException(400, str(e)) from e
    except secrets.SecretsError as e:
        raise HTTPException(503, str(e)) from e
    return {"id": account_id}


@router.patch("/api/connectors/mail/{account_id}")
def update_mailbox(
    conn: Db,
    account_id: int,
    label: Annotated[str | None, Body(embed=True)] = None,
    scopes_: Annotated[list[str] | None, Body(embed=True, alias="scopes")] = None,
    password: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    try:
        accounts.update_mailbox(
            conn,
            account_id,
            datetime.now(UTC),
            label=label,
            scopes=scopes_,
            password=password,
            valid_scopes=scopes.known(conn),
        )
    except accounts.ConnectorError as e:
        raise HTTPException(404 if str(e).startswith("no mailbox") else 400, str(e)) from e
    return {"ok": True}


# --- Telegram ---------------------------------------------------------------------------------


def _qr_svg(url: str) -> str:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    img = qrcode.make(url, image_factory=SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding="unicode")


def _login_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "error": row["error"],
        "qr_svg": _qr_svg(row["qr_url"]) if row["status"] == "qr" and row["qr_url"] else None,
        "updated_at": row["updated_at"].isoformat(),
    }


@router.get("/api/connectors/telegram")
def telegram(conn: Db) -> dict[str, Any]:
    from kb import loops
    from kb.connectors import tg_dialogs

    login = conn.execute("SELECT * FROM telegram_login ORDER BY id DESC LIMIT 1").fetchone()
    return {
        **tg_dialogs.listing(conn),
        "self_ids": sorted(loops.owner_telegram_ids(conn)),
        "login": _login_view(login),
    }


@router.post("/api/connectors/telegram/dialogs/{chat_id}")
def telegram_dialog(
    request: Request,
    conn: Db,
    chat_id: int,
    included: Annotated[bool | None, Body(embed=True)] = None,
    scopes_: Annotated[list[str] | None, Body(embed=True, alias="scopes")] = None,
) -> dict[str, int]:
    from kb.connectors import tg_dialogs

    try:
        changed = tg_dialogs.set_dialog(conn, request.app.state.config, chat_id, included, scopes_)
    except scopes.ReviewError as e:
        raise HTTPException(404 if str(e).startswith("no Telegram") else 400, str(e)) from e
    return {"rescoped_messages": changed}


@router.post("/api/connectors/telegram/login")
def telegram_login(conn: Db) -> dict[str, Any]:
    conn.execute(
        "UPDATE telegram_login SET status = 'expired', updated_at = now()"
        " WHERE status IN ('pending', 'qr', 'password_needed')"
    )
    row = conn.execute("INSERT INTO telegram_login DEFAULT VALUES RETURNING *").fetchone()
    return _login_view(row) or {}


@router.get("/api/connectors/telegram/login/{login_id}")
def telegram_login_status(conn: Db, login_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM telegram_login WHERE id = %s", (login_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no login {login_id}")
    return _login_view(row) or {}


@router.post("/api/connectors/telegram/login/{login_id}/password")
def telegram_password(
    conn: Db, login_id: int, password: Annotated[str, Body(embed=True)]
) -> dict[str, bool]:
    row = conn.execute(
        "UPDATE telegram_login SET secret = %s, updated_at = now() WHERE id = %s"
        " AND status = 'password_needed' RETURNING id",
        (secrets.seal({"password": password}), login_id),
    ).fetchone()
    if row is None:
        raise HTTPException(400, "this login is not waiting for a password")
    return {"ok": True}


@router.post("/api/connectors/mail/{account_id}/disconnect")
def disconnect_mailbox(
    conn: Db,
    account_id: int,
    remove_from_search: Annotated[bool, Body(embed=True)] = False,
    delete_archive: Annotated[bool, Body(embed=True)] = False,
    confirm: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, int]:
    if delete_archive and confirm != "DELETE":
        raise HTTPException(400, 'deleting the archived originals needs confirm = "DELETE"')
    try:
        return accounts.disconnect_mailbox(conn, account_id, remove_from_search, delete_archive)
    except accounts.ConnectorError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/api/connectors/mail/senders")
def senders_to_mark(conn: Db) -> dict[str, Any]:
    """Senders of unsorted email in the last 30 days, to mark by address or domain."""
    rows = conn.execute(
        """
        SELECT lower(substring(m.author from '[^<\\s]+@[^>\\s]+')) AS address,
               count(DISTINCT i.id) AS threads, max(i.last_activity_at) AS last
        FROM items i JOIN messages m ON m.source_id = i.source_id AND m.unit_key = i.source_item_key
        WHERE i.kind = 'email_thread' AND NOT i.hidden AND 'unsorted' = ANY(i.scopes)
          AND i.last_activity_at > now() - interval '30 days'
        GROUP BY 1 HAVING lower(substring(m.author from '[^<\\s]+@[^>\\s]+')) IS NOT NULL
        ORDER BY threads DESC, last DESC LIMIT 50
        """
    ).fetchall()
    return {
        "senders": [
            {"address": r["address"], "threads": r["threads"], "last": r["last"].isoformat()}
            for r in rows
        ]
    }


CATALOG: list[dict[str, str]] = [
    {
        "key": "github",
        "name": "GitHub",
        "state": "planned",
        "adds": "Code, issues and PRs (Digisoft, RDIM B2B)",
    },
    {
        "key": "karakeep",
        "name": "Karakeep",
        "state": "planned",
        "adds": "Saved links and web clips",
    },
    {
        "key": "drive",
        "name": "Google Drive",
        "state": "planned",
        "adds": "Keep Library documents in sync",
    },
    {
        "key": "ads",
        "name": "GA4 · Meta Ads · Google Ads · TikTok Ads",
        "state": "planned",
        "adds": "Marketing metrics in CMO standups",
    },
    {
        "key": "commerce",
        "name": "Marketplaces · Shopify · Stripe",
        "state": "planned",
        "adds": "Sales and payments",
    },
    {
        "key": "ops",
        "name": "Vault & ops",
        "state": "planned",
        "adds": "Domain expiry and failed-payment reminders",
    },
    {
        "key": "whatsapp",
        "name": "WhatsApp",
        "state": "not_possible",
        "adds": "Personal WhatsApp has no official API; chat-export import is planned",
    },
]


@router.get("/api/connectors")
def hub(request: Request, conn: Db) -> dict[str, Any]:
    from kb import health, loops
    from kb.connectors import tg_dialogs

    config = request.app.state.config
    effective = accounts.effective_config(conn, config)
    now = datetime.now(UTC)
    counts = {
        r["source_id"]: r["n"]
        for r in conn.execute(
            "SELECT source_id, count(*) AS n FROM items WHERE NOT hidden"
            " AND kind NOT IN ('passage', 'doc_section') GROUP BY source_id"
        )
    }
    by_scope: dict[str, dict[str, int]] = {}
    for r in conn.execute(
        "SELECT source_id, s, count(*) AS n FROM items, unnest(scopes) s WHERE NOT hidden"
        " AND kind NOT IN ('passage', 'doc_section') GROUP BY source_id, s"
    ):
        by_scope.setdefault(r["source_id"], {})[r["s"]] = r["n"]
    connected = {m["source_id"]: m for m in accounts.list_mailboxes(conn)}
    mail = []
    for s in effective.imap_sources():
        st = health.source_status(conn, s, now)
        m = connected.get(s.id)
        mail.append(
            {
                "source_id": s.id,
                "account_id": m["id"] if m else None,
                "label": m["label"] if m else s.id,
                "address": m["address"] if m else _safe_username(s),
                "from_config": m is None,
                "scopes": list(s.scopes),
                "healthy": st["healthy"],
                "last_ok": st["last_ok"],
                "last_error": st["last_error"],
                "items": counts.get(s.id, 0),
                "by_scope": by_scope.get(s.id, {}),
            }
        )
    tg = []
    dialogs = tg_dialogs.listing(conn)
    for s in config.telegram_sources():
        st = health.source_status(conn, s, now)
        tg.append(
            {
                "source_id": s.id,
                "healthy": st["healthy"],
                "last_ok": st["last_ok"],
                "last_error": st["last_error"],
                "included": len(dialogs["included"]),
                "to_mark": len(dialogs["to_mark"]),
                "items": counts.get(s.id, 0),
                "by_scope": by_scope.get(s.id, {}),
            }
        )
    return {
        "mail": mail,
        "disconnected_mail": [m for m in connected.values() if m["state"] == "disconnected"],
        "telegram": tg,
        "telegram_self_ids": sorted(loops.owner_telegram_ids(conn)),
        "catalog": CATALOG,
    }


def _safe_username(source: Any) -> str:
    try:
        return str(source.username())
    except Exception:
        return ""
