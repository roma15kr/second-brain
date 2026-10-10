"""IMAP mailbox connector: per-folder UID cursor, read-only (BODY.PEEK keeps mail unread)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from kb.archive import RawRecord
from kb.config import ImapSource
from kb.connectors.base import get_state, set_state, store
from kb.db import Conn

log = logging.getLogger(__name__)

FETCH_BATCH = 50
BODY = b"BODY[]"


class ImapClientLike(Protocol):
    """The subset of imapclient.IMAPClient used here (lets tests pass a fake)."""

    def select_folder(self, folder: str, readonly: bool = False) -> dict[bytes, Any]: ...
    def search(self, criteria: Any = "ALL") -> list[int]: ...
    def fetch(self, messages: Iterable[int], data: list[str]) -> dict[int, dict[bytes, Any]]: ...


def open_client(source: ImapSource) -> Any:
    from imapclient import IMAPClient

    client = IMAPClient(source.host, port=source.port, ssl=source.ssl, timeout=60)
    client.login(source.username(), source.password())
    return client


def sync_folder(
    conn: Conn,
    client: ImapClientLike,
    source: ImapSource,
    folder: str,
    today: date | None = None,
) -> int:
    """Fetch new messages from one folder; returns how many new records were archived."""
    info = client.select_folder(folder, readonly=True)
    uidvalidity = int(info[b"UIDVALIDITY"])
    state = get_state(conn, source.id, f"folder:{folder}")
    if state is None or state.get("uidvalidity") != uidvalidity:
        since = (today or datetime.now(UTC).date()) - timedelta(days=source.backfill_days)
        uids = client.search(["SINCE", since])
        last_uid = 0
    else:
        last_uid = int(state["last_uid"])
        uids = [u for u in client.search(["UID", f"{last_uid + 1}:*"]) if u > last_uid]

    stored = 0
    for batch in _chunks(sorted(uids), FETCH_BATCH):
        fetched = client.fetch(batch, ["BODY.PEEK[]", "INTERNALDATE", "FLAGS"])
        for uid in batch:
            data = fetched.get(uid)
            if data is None:
                continue
            internal = data.get(b"INTERNALDATE")
            occurred = _aware(internal) if isinstance(internal, datetime) else None
            record = RawRecord(
                source_id=source.id,
                external_id=f"{folder}:{uidvalidity}:{uid}",
                kind="email",
                occurred_at=occurred,
                payload={"folder": folder, "uid": uid, "uidvalidity": uidvalidity},
                blob=bytes(data[BODY]),
            )
            if store(conn, record):
                stored += 1
        last_uid = max(last_uid, *batch)
        set_state(
            conn, source.id, f"folder:{folder}", {"uidvalidity": uidvalidity, "last_uid": last_uid}
        )
    if state is None or state.get("uidvalidity") != uidvalidity:
        set_state(
            conn, source.id, f"folder:{folder}", {"uidvalidity": uidvalidity, "last_uid": last_uid}
        )
    return stored


def sync(conn: Conn, client: ImapClientLike, source: ImapSource) -> int:
    total = 0
    for folder in source.folders:
        n = sync_folder(conn, client, source, folder)
        log.info("imap %s %s: %d new", source.id, folder, n)
        total += n
    return total


def _chunks(items: list[int], size: int) -> Iterable[list[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
