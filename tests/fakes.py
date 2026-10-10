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
    def __init__(self, uidvalidity: int = 1) -> None:
        self.uidvalidity = uidvalidity
        self.messages: dict[int, tuple[bytes, datetime]] = {}
        self.fetch_calls: list[list[str]] = []
        self.readonly_selects: list[bool] = []

    def add(self, uid: int, raw: bytes, when: datetime) -> None:
        self.messages[uid] = (raw, when)

    def select_folder(self, folder: str, readonly: bool = False) -> dict[bytes, Any]:
        self.readonly_selects.append(readonly)
        return {b"UIDVALIDITY": self.uidvalidity}

    def search(self, criteria: Any = "ALL") -> list[int]:
        if criteria[0] == "SINCE":
            since = criteria[1]
            return [u for u, (_, when) in self.messages.items() if when.date() >= since]
        if criteria[0] == "UID":
            start = int(criteria[1].split(":")[0])
            uids = [u for u in self.messages if u >= start]
            # Real servers return the highest UID for "N:*" even when nothing is newer.
            return uids or ([max(self.messages)] if self.messages else [])
        raise AssertionError(criteria)

    def fetch(self, messages: Iterable[int], data: list[str]) -> dict[int, dict[bytes, Any]]:
        self.fetch_calls.append(list(data))
        return {
            u: {b"BODY[]": self.messages[u][0], b"INTERNALDATE": self.messages[u][1]}
            for u in messages
            if u in self.messages
        }


async def call(server: Any, name: str, args: dict[str, Any]) -> Any:
    """Call an MCP tool in-process and return the (non-elicitation) CallToolResult."""
    from mcp.types import CallToolResult

    result = await server.call_tool(name, args)
    assert isinstance(result, CallToolResult)
    return result
