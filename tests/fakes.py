"""Fake IMAP server for connector tests."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from email.message import EmailMessage
from typing import Any


def make_email(
    subject: str,
    body: str,
    sender: str = "Oleh <oleh@quokka.example>",
    to: str = "me@example.com",
    message_id: str | None = None,
    date: str = "Mon, 14 Sep 2026 10:00:00 +0300",
    html: str | None = None,
    attachment: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = message_id or f"<{abs(hash((subject, body)))}@example>"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename=attachment)
    return msg.as_bytes()


class FakeImap:
    """In-memory IMAP server: one or more folders, optional Gmail extensions."""

    def __init__(self, uidvalidity: int = 1, gmail: bool = False) -> None:
        self.uidvalidity = uidvalidity
        self.gmail = gmail
        self.folders: dict[str, dict[int, tuple[bytes, datetime, dict[bytes, Any]]]] = {"INBOX": {}}
        self.flags: dict[str, tuple[bytes, ...]] = {"INBOX": ()}
        self.selected = "INBOX"
        self.messages = self.folders["INBOX"]
        self.fetch_calls: list[list[str]] = []
        self.readonly_selects: list[bool] = []
        self.search_calls: list[Any] = []

    def add_folder(self, name: str, flags: tuple[bytes, ...] = ()) -> None:
        self.folders.setdefault(name, {})
        self.flags[name] = flags

    def add(
        self, uid: int, raw: bytes, when: datetime, folder: str = "INBOX", **extra: Any
    ) -> None:
        self.add_folder(folder, self.flags.get(folder, ()))
        self.folders[folder][uid] = (raw, when, {k.encode(): v for k, v in extra.items()})

    def has_capability(self, capability: str) -> bool:
        return self.gmail and capability == "X-GM-EXT-1"

    def list_folders(self) -> list[tuple[tuple[bytes, ...], bytes | None, str]]:
        return [(self.flags.get(n, ()), b"/", n) for n in self.folders]

    def select_folder(self, folder: str, readonly: bool = False) -> dict[bytes, Any]:
        self.readonly_selects.append(readonly)
        self.selected = folder
        self.messages = self.folders[folder]
        return {b"UIDVALIDITY": self.uidvalidity, b"UIDNEXT": max(self.messages, default=0) + 1}

    def search(self, criteria: Any = "ALL") -> list[int]:
        self.search_calls.append(criteria)
        msgs = self.messages
        if criteria == "ALL":
            return sorted(msgs)
        crit = list(criteria)
        uids = sorted(msgs)
        while crit:
            key = crit.pop(0)
            if key == "SINCE":
                since = crit.pop(0)
                uids = [u for u in uids if msgs[u][1].date() >= since]
            elif key == "UID":
                lo, hi = crit.pop(0).split(":")
                top = max(msgs, default=0)
                hi_n = top if hi == "*" else int(hi)
                found = [u for u in uids if int(lo) <= u <= hi_n]
                # Real servers return the highest UID for "N:*" even when nothing is newer.
                uids = found or ([top] if hi == "*" and msgs and top in uids else [])
            else:
                raise AssertionError(criteria)
        return uids

    def fetch(self, messages: Iterable[int], data: list[str]) -> dict[int, dict[bytes, Any]]:
        self.fetch_calls.append(list(data))
        out: dict[int, dict[bytes, Any]] = {}
        for u in messages:
            if u not in self.messages:
                continue
            raw, when, extra = self.messages[u]
            row: dict[bytes, Any] = {b"BODY[]": raw, b"INTERNALDATE": when}
            for item in data:
                if item.startswith("X-GM-") and item.encode() in extra:
                    row[item.encode()] = extra[item.encode()]
            out[u] = row
        return out


async def call(server: Any, name: str, args: dict[str, Any]) -> Any:
    """Call an MCP tool in-process and return the (non-elicitation) CallToolResult."""
    from mcp.types import CallToolResult

    result = await server.call_tool(name, args)
    assert isinstance(result, CallToolResult)
    return result
