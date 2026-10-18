"""Connectors hub (connectors spec): projects and accounts connected from the web OS."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
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
