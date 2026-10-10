"""Parse RFC 822 messages into the fields an item needs."""

from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser


@dataclass
class ParsedEmail:
    message_id: str | None
    subject: str
    sender: str
    recipients: list[str]
    date: datetime | None
    body: str
    attachments: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)

    @property
    def participants(self) -> list[str]:
        seen: list[str] = []
        for p in [self.sender, *self.recipients]:
            if p and p not in seen:
                seen.append(p)
        return seen


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(p.parts)).strip()


def _addresses(values: list[str]) -> list[str]:
    return [addr.lower() for _, addr in getaddresses(values) if addr]


def parse(raw: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    plain: list[str] = []
    html: list[str] = []
    attachments: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            attachments.append(filename or "(unnamed)")
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError):
            payload = part.get_payload(decode=True)
            content = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
        (plain if ctype == "text/plain" else html).append(str(content))
    body = "\n".join(plain).strip() or html_to_text("\n".join(html))

    date = None
    if msg["Date"]:
        try:
            date = parsedate_to_datetime(str(msg["Date"]))
        except (TypeError, ValueError):
            date = None
    senders = _addresses([str(msg["From"] or "")])
    recipients = _addresses([str(msg[h]) for h in ("To", "Cc") if msg[h]])
    refs = str(msg["References"] or "").split()
    return ParsedEmail(
        message_id=str(msg["Message-ID"]).strip() if msg["Message-ID"] else None,
        subject=str(msg["Subject"] or "").strip(),
        sender=senders[0] if senders else "",
        recipients=recipients,
        date=date,
        body=body,
        attachments=attachments,
        in_reply_to=str(msg["In-Reply-To"]).strip() if msg["In-Reply-To"] else None,
        references=refs,
    )
