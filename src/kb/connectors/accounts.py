"""Accounts connected in the web OS (connectors spec, design D11).

Mailboxes: Gmail (servers preset) or any IMAP + SMTP provider. Both logins are checked before
saving; the password is stored sealed (kb.secrets) and never returned by the API. Active accounts
become ordinary ImapSources that the ingest loop, scope resolver and status read every cycle, so
connecting needs no restart and no configuration change.
"""

from __future__ import annotations

import contextlib
import logging
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from kb import secrets
from kb.config import Config, ImapSource
from kb.db import Conn

log = logging.getLogger(__name__)

SmtpSecurity = Literal["ssl", "starttls"]
GMAIL = {
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "smtp_security": "ssl",
}
CACHE_SECONDS = 60


class ConnectorError(ValueError):
    pass


@dataclass
class Mailbox:
    label: str
    address: str
    password: str
    preset: Literal["gmail", "imap"] = "gmail"
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: SmtpSecurity = "ssl"
    smtp_username: str | None = None  # defaults to the address
    smtp_password: str | None = None  # defaults to the password
    scopes: tuple[str, ...] = ("unsorted",)

    def resolved(self) -> Mailbox:
        if self.preset == "gmail":
            return Mailbox(
                **{**self.__dict__, **GMAIL, "smtp_username": None, "smtp_password": None}
            )
        if not self.imap_host or not self.smtp_host:
            raise ConnectorError("IMAP and SMTP servers are required for this provider")
        return self


# --- connection checks (replaced in tests) ----------------------------------------------------


def check_imap(host: str, port: int, user: str, password: str) -> None:
    from imapclient import IMAPClient

    try:
        client = IMAPClient(host, port=port, ssl=True, timeout=20)
        try:
            client.login(user, password)
        finally:
            with contextlib.suppress(Exception):
                client.logout()
    except Exception as e:
        raise ConnectorError(f"IMAP login to {host} failed: {e}") from e


def check_smtp(host: str, port: int, security: SmtpSecurity, user: str, password: str) -> None:
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=20, context=ssl.create_default_context()
            )
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls(context=ssl.create_default_context())
        try:
            server.login(user, password)
        finally:
            with contextlib.suppress(Exception):
                server.quit()
    except Exception as e:
        raise ConnectorError(f"SMTP login to {host} failed: {e}") from e


# --- mailboxes --------------------------------------------------------------------------------


def _check(m: Mailbox) -> None:
    check_imap(m.imap_host, m.imap_port, m.address, m.password)
    check_smtp(
        m.smtp_host,
        m.smtp_port,
        m.smtp_security,
        m.smtp_username or m.address,
        m.smtp_password or m.password,
    )


def add_mailbox(conn: Conn, mailbox: Mailbox, valid_scopes: tuple[str, ...], now: datetime) -> int:
    m = mailbox.resolved()
    if "@" not in m.address:
        raise ConnectorError("the address needs an @")
    bad = [s for s in m.scopes if s not in (*valid_scopes, "unsorted")]
    if bad:
        raise ConnectorError(f"unknown scope(s) {bad}")
    if conn.execute(
        "SELECT 1 FROM connector_accounts WHERE kind = 'imap' AND state = 'active'"
        " AND settings->>'address' = %s",
        (m.address.lower(),),
    ).fetchone():
        raise ConnectorError(f"{m.address} is already connected")
    _check(m)
    settings = {
        "address": m.address.lower(),
        "preset": m.preset,
        "imap_host": m.imap_host,
        "imap_port": m.imap_port,
        "smtp_host": m.smtp_host,
        "smtp_port": m.smtp_port,
        "smtp_security": m.smtp_security,
        "smtp_username": m.smtp_username,
    }
    secret = {"password": m.password, "smtp_password": m.smtp_password}
    row = conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret, default_scopes,"
        " checked_at) VALUES ('imap', %s, %s, %s, %s, %s) RETURNING id",
        (m.label or m.address, Jsonb(settings), secrets.seal(secret), list(m.scopes), now),
    ).fetchone()
    assert row is not None
    _invalidate()
    return int(row["id"])


def update_mailbox(
    conn: Conn,
    account_id: int,
    now: datetime,
    label: str | None = None,
    scopes: list[str] | None = None,
    password: str | None = None,
    valid_scopes: tuple[str, ...] = (),
) -> None:
    row = conn.execute(
        "SELECT * FROM connector_accounts WHERE id = %s AND kind = 'imap'", (account_id,)
    ).fetchone()
    if row is None:
        raise ConnectorError(f"no mailbox {account_id}")
    if scopes is not None:
        bad = [s for s in scopes if s not in (*valid_scopes, "unsorted")]
        if bad or not scopes:
            raise ConnectorError(f"unknown scope(s) {bad}")
        conn.execute(
            "UPDATE connector_accounts SET default_scopes = %s WHERE id = %s", (scopes, account_id)
        )
    if label:
        conn.execute("UPDATE connector_accounts SET label = %s WHERE id = %s", (label, account_id))
    if password:
        s = row["settings"]
        old = secrets.unseal(row["secret"])
        m = Mailbox(
            label=row["label"],
            address=s["address"],
            password=password,
            preset=s["preset"],
            imap_host=s["imap_host"],
            imap_port=s["imap_port"],
            smtp_host=s["smtp_host"],
            smtp_port=s["smtp_port"],
            smtp_security=s["smtp_security"],
            smtp_username=s.get("smtp_username"),
            smtp_password=old.get("smtp_password"),
        )
        _check(m)
        conn.execute(
            "UPDATE connector_accounts SET secret = %s, checked_at = %s WHERE id = %s",
            (secrets.seal({**old, "password": password}), now, account_id),
        )
    _invalidate()


def list_mailboxes(conn: Conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, label, settings, default_scopes, state, created_at, checked_at,"
        " secret IS NOT NULL AS password_set FROM connector_accounts WHERE kind = 'imap'"
        " ORDER BY id"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "source_id": f"mail-{r['id']}",
            "label": r["label"],
            "address": r["settings"].get("address"),
            "preset": r["settings"].get("preset"),
            "imap_host": r["settings"].get("imap_host"),
            "smtp_host": r["settings"].get("smtp_host"),
            "scopes": list(r["default_scopes"]),
            "state": r["state"],
            "password_set": r["password_set"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


def imap_sources(conn: Conn) -> list[ImapSource]:
    """Active web-connected mailboxes as ImapSources (credentials decrypted in memory)."""
    out = []
    for r in conn.execute(
        "SELECT * FROM connector_accounts WHERE kind = 'imap' AND state = 'active' ORDER BY id"
    ).fetchall():
        try:
            secret = secrets.unseal(r["secret"])
        except secrets.SecretsError:
            log.exception("cannot use mailbox %s", r["id"])
            continue
        s = r["settings"]
        out.append(
            ImapSource.model_construct(
                id=f"mail-{r['id']}",
                type="imap",
                scopes=list(r["default_scopes"]),
                host=s["imap_host"],
                port=int(s["imap_port"]),
                ssl=True,
                username_env="",
                password_env="",
                folders=None,
                exclude_folders=[],
                poll_seconds=60,
                backfill_days=365,
                backfill_batch=200,
                inline_username=s["address"],
                inline_password=secret["password"],
            )
        )
    return out


_cache: dict[int, tuple[float, Config]] = {}


def _invalidate() -> None:
    _cache.clear()


def effective_config(conn: Conn, config: Config) -> Config:
    """Configuration plus web-connected mailboxes (cached for a minute)."""
    hit = _cache.get(id(config))
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        extra = imap_sources(conn)
    except Exception:
        log.exception("cannot load connected accounts")
        extra = []
    merged = config.model_copy(update={"sources": [*config.sources, *extra]})
    _cache[id(config)] = (time.monotonic(), merged)
    return merged


def disconnect_mailbox(
    conn: Conn, account_id: int, remove_from_search: bool = False, delete_archive: bool = False
) -> dict[str, int]:
    """Stops syncing. Data stays searchable unless removed from search (items hidden); the
    archived originals are deleted only on an explicit second confirmation."""
    row = conn.execute(
        "UPDATE connector_accounts SET state = 'disconnected' WHERE id = %s AND kind = 'imap'"
        " RETURNING id",
        (account_id,),
    ).fetchone()
    if row is None:
        raise ConnectorError(f"no mailbox {account_id}")
    source_id = f"mail-{account_id}"
    hidden = deleted = 0
    if delete_archive:
        deleted = len(
            conn.execute(
                "DELETE FROM raw_records WHERE source_id = %s RETURNING 1", (source_id,)
            ).fetchall()
        )
        conn.execute("DELETE FROM messages WHERE source_id = %s", (source_id,))
        hidden = len(
            conn.execute(
                "DELETE FROM items WHERE source_id = %s RETURNING 1", (source_id,)
            ).fetchall()
        )
    elif remove_from_search:
        hidden = len(
            conn.execute(
                "UPDATE items SET hidden = true WHERE source_id = %s AND NOT hidden RETURNING 1",
                (source_id,),
            ).fetchall()
        )
    _invalidate()
    return {"hidden_items": hidden, "deleted_records": deleted}
