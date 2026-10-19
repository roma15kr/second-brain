"""IMAP mailbox connector, read-only (BODY.PEEK keeps mail unread).

Folders are discovered each cycle unless configured. Gmail (X-GM-EXT-1) is read through its
`\\All` folder with Gmail thread ids and labels; other servers through every folder except
junk/trash/drafts. Each folder keeps two cursors: a live cursor for new mail and a backfill
cursor that walks the backfill window in chunks, so new mail never waits for the backfill.
"""

from __future__ import annotations

import logging
import re
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
GMAIL_FETCH = ["X-GM-THRID", "X-GM-MSGID", "X-GM-LABELS"]
SKIP_FLAGS = {b"\\Junk", b"\\Trash", b"\\Drafts", b"\\Noselect", b"\\NonExistent"}
SKIP_NAMES = re.compile(
    r"(?i)^(spam|junk( e-?mail)?|bulk mail|trash|bin|deleted( items| messages)?|drafts?|"
    r"корзина|кошик|спам|чернетки|черновики|удал[её]нные|видалені)$"
)


class ImapClientLike(Protocol):
    """The subset of imapclient.IMAPClient used here (lets tests pass a fake)."""

    def select_folder(self, folder: str, readonly: bool = False) -> dict[bytes, Any]: ...
    def search(self, criteria: Any = "ALL") -> list[int]: ...
    def fetch(self, messages: Iterable[int], data: list[str]) -> dict[int, dict[bytes, Any]]: ...
    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes | None, str]]: ...
    def has_capability(self, capability: str) -> bool: ...


def open_client(source: ImapSource) -> Any:
    from imapclient import IMAPClient

    client = IMAPClient(source.host, port=source.port, ssl=source.ssl, timeout=60)
    client.login(source.username(), source.password())
    return client


def is_gmail(client: ImapClientLike) -> bool:
    return bool(client.has_capability("X-GM-EXT-1"))


def discover_folders(client: ImapClientLike, source: ImapSource) -> list[str]:
    """Folders to read: configured ones, else Gmail's All Mail, else all real folders."""
    if source.folders:
        return list(source.folders)
    listing = client.list_folders()
    if is_gmail(client):
        return [name for flags, _, name in listing if b"\\All" in flags]
    excluded = {f.lower() for f in source.exclude_folders}
    names = []
    for flags, delim, name in listing:
        if set(flags) & SKIP_FLAGS or b"\\All" in flags:
            continue
        sep = delim.decode() if isinstance(delim, bytes) else (delim or "/")
        leaf = name.split(sep)[-1] if sep else name
        if SKIP_NAMES.match(leaf.strip()) or name.lower() in excluded:
            continue
        names.append(name)
    return names


def _labels(raw: Any) -> list[str]:
    from imapclient import imap_utf7

    out = []
    for label in raw or ():
        text = imap_utf7.decode(label) if isinstance(label, bytes) else str(label)
        out.append(text.lstrip("\\"))
    return out


def _new_state(uidvalidity: int, uidnext: int, since: date) -> dict[str, Any]:
    top = max(uidnext - 1, 0)
    return {
        "uidvalidity": uidvalidity,
        "last_uid": top,  # live cursor: everything above is new mail
        "bf_upto": top,  # backfill covers UIDs up to here
        "bf_pos": 0,  # backfill done up to here
        "since": since.isoformat(),
    }


def _store_batch(
    conn: Conn,
    client: ImapClientLike,
    source: ImapSource,
    folder: str,
    uidvalidity: int,
    uids: list[int],
    gmail: bool,
) -> int:
    stored = 0
    items = ["BODY.PEEK[]", "INTERNALDATE", "FLAGS", *(GMAIL_FETCH if gmail else [])]
    for batch in _chunks(sorted(uids), FETCH_BATCH):
        fetched = client.fetch(batch, items)
        for uid in batch:
            data = fetched.get(uid)
            if data is None:
                continue
            internal = data.get(b"INTERNALDATE")
            payload: dict[str, Any] = {"folder": folder, "uid": uid, "uidvalidity": uidvalidity}
            if gmail:
                payload["gm_thrid"] = str(data.get(b"X-GM-THRID") or "") or None
                payload["gm_msgid"] = str(data.get(b"X-GM-MSGID") or "") or None
                payload["gm_labels"] = _labels(data.get(b"X-GM-LABELS"))
            record = RawRecord(
                source_id=source.id,
                external_id=f"{folder}:{uidvalidity}:{uid}",
                kind="email",
                occurred_at=_aware(internal) if isinstance(internal, datetime) else None,
                payload=payload,
                blob=bytes(data[BODY]),
            )
            if store(conn, record):
                stored += 1
    return stored


def sync_folder(
    conn: Conn,
    client: ImapClientLike,
    source: ImapSource,
    folder: str,
    today: date | None = None,
    gmail: bool = False,
) -> int:
    """New mail first, then one backfill chunk. Returns how many new records were archived."""
    info = client.select_folder(folder, readonly=True)
    uidvalidity = int(info[b"UIDVALIDITY"])
    key = f"folder:{folder}"
    state = get_state(conn, source.id, key)
    if state is None or state.get("uidvalidity") != uidvalidity or "bf_upto" not in state:
        uidnext = int(info.get(b"UIDNEXT") or (max(client.search("ALL") or [0]) + 1))
        since = (today or datetime.now(UTC).date()) - timedelta(days=source.backfill_days)
        state = _new_state(uidvalidity, uidnext, since)
        set_state(conn, source.id, key, state)

    # what the server says comes next, kept for status (cursor vs server, see folder_cursors)
    state["server_next"] = int(info.get(b"UIDNEXT") or 0) or None
    set_state(conn, source.id, key, state)

    stored = 0
    # 1. live: anything above the live cursor (servers return the top UID for "N:*" even when
    #    nothing is newer, hence the filter)
    last = int(state["last_uid"])
    new = [u for u in client.search(["UID", f"{last + 1}:*"]) if u > last]
    if new:
        stored += _store_batch(conn, client, source, folder, uidvalidity, new, gmail)
        state["last_uid"] = max(new)
        set_state(conn, source.id, key, state)

    # 2. backfill: the next chunk of the window below the backfill upper bound
    pos, upto = int(state["bf_pos"]), int(state["bf_upto"])
    if pos < upto:
        since_d = date.fromisoformat(state["since"])
        window = sorted(
            u
            for u in client.search(["SINCE", since_d, "UID", f"{pos + 1}:{upto}"])
            if pos < u <= upto
        )
        chunk = window[: source.backfill_batch]
        if chunk:
            stored += _store_batch(conn, client, source, folder, uidvalidity, chunk, gmail)
        state["bf_pos"] = chunk[-1] if len(window) > len(chunk) else upto
        set_state(conn, source.id, key, state)
    return stored


def folder_cursors(conn: Conn, source_id: str) -> list[dict[str, Any]]:
    """Per folder: the live cursor and the server's next UID (status shows when mail is stuck)."""
    rows = conn.execute(
        "SELECT key, value FROM sync_state WHERE source_id = %s AND key LIKE 'folder:%%'"
        " ORDER BY key",
        (source_id,),
    ).fetchall()
    return [
        {
            "folder": r["key"].removeprefix("folder:"),
            "uidvalidity": r["value"].get("uidvalidity"),
            "cursor": r["value"].get("last_uid"),
            "server_next": r["value"].get("server_next"),
        }
        for r in rows
    ]


def backfill_done(conn: Conn, source_id: str, folder: str) -> bool:
    state = get_state(conn, source_id, f"folder:{folder}") or {}
    return bool(state) and int(state.get("bf_pos", 0)) >= int(state.get("bf_upto", 0))


def sync(conn: Conn, client: ImapClientLike, source: ImapSource) -> tuple[int, bool]:
    """Sync all folders once. Returns (new records, backfill still in progress)."""
    gmail = is_gmail(client)
    total = 0
    pending = False
    for folder in discover_folders(client, source):
        n = sync_folder(conn, client, source, folder, gmail=gmail)
        if n or not backfill_done(conn, source.id, folder):
            log.info(
                "imap %s %s: %d new%s",
                source.id,
                folder,
                n,
                "" if backfill_done(conn, source.id, folder) else " (backfill in progress)",
            )
        total += n
        pending = pending or not backfill_done(conn, source.id, folder)
    return total, pending


def _chunks(items: list[int], size: int) -> Iterable[list[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
