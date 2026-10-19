"""Email executors for approved suggestions (assistant-actions spec; design D17).

"Save to Drafts" appends the reply to the mailbox's Drafts folder with the \\Draft flag and the
thread's In-Reply-To/References, so the mail client shows it in the same conversation; nothing is
sent. The Message-ID carries the suggestion id, so a retry after a crash finds the saved draft
instead of saving a second one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from kb.config import Config, ImapSource
from kb.db import Conn

log = logging.getLogger(__name__)

GMAIL_IMAP = "imap.gmail.com"
SENT_FOLDER_NAMES = (
    "Sent",
    "Sent Items",
    "Sent Messages",
    "INBOX.Sent",
    "Надіслані",
    "Отправленные",
)
DRAFT_FOLDER_NAMES = ("[Gmail]/Drafts", "Drafts", "INBOX.Drafts", "Чернетки", "Черновики")


class MailError(RuntimeError):
    pass


@dataclass
class Mailbox:
    source_id: str
    address: str
    imap: ImapSource
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"
    smtp_username: str = ""
    smtp_password: str = ""

    @property
    def gmail(self) -> bool:
        return self.imap.host == GMAIL_IMAP


def mailbox(conn: Conn, config: Config, source_id: str) -> Mailbox:
    """The mailbox an email arrived in, with the credentials needed to write to it."""
    from kb import secrets
    from kb.connectors import accounts

    for s in accounts.effective_config(conn, config).sources:
        if s.id != source_id or not isinstance(s, ImapSource):
            continue
        address = s.username()
        box = Mailbox(source_id, address, s)
        if source_id.removeprefix("mail-").isdigit():  # connected in the web OS: SMTP stored
            row = conn.execute(
                "SELECT settings, secret FROM connector_accounts WHERE id = %s",
                (int(source_id.removeprefix("mail-")),),
            ).fetchone()
            if row is not None:
                st, secret = row["settings"], secrets.unseal(row["secret"])
                box.smtp_host = st.get("smtp_host") or ""
                box.smtp_port = int(st.get("smtp_port") or 465)
                box.smtp_security = st.get("smtp_security") or "ssl"
                box.smtp_username = st.get("smtp_username") or address
                box.smtp_password = secret.get("smtp_password") or s.password()
        elif box.gmail:  # configured Gmail: the same app password works for SMTP
            box.smtp_host, box.smtp_username, box.smtp_password = (
                "smtp.gmail.com",
                address,
                s.password(),
            )
        return box
    raise MailError(f"mailbox {source_id} is not connected")


def thread_headers(conn: Conn, item_id: int) -> dict[str, Any]:
    """Who to answer and how to thread a reply to an email thread item."""
    item = conn.execute(
        "SELECT source_id, source_item_key, kind, title FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    if item is None or item["kind"] != "email_thread":
        raise MailError(f"item {item_id} is not an email thread")
    rows = conn.execute(
        "SELECT message_key, refs, author, participants, subject, metadata FROM messages"
        " WHERE source_id = %s AND unit_key = %s AND kind = 'email' AND NOT hidden"
        " ORDER BY sent_at",
        (item["source_id"], item["source_item_key"]),
    ).fetchall()
    rows = [r for r in rows if not _is_draft(r["metadata"])]
    if not rows:
        raise MailError(f"thread {item_id} has no messages")
    last = rows[-1]
    return {
        "source_id": item["source_id"],
        "subject": last["subject"] or item["title"] or "",
        "in_reply_to": last["message_key"],
        "references": [*(r for r in last["refs"] if r), last["message_key"]],
        "last_author": last["author"],
        "participants": list(last["participants"]),
    }


def _is_draft(metadata: dict[str, Any]) -> bool:
    return any(lab.lstrip("\\") == "Draft" for lab in metadata.get("labels") or [])


def reply_subject(subject: str) -> str:
    return subject if subject.lower().startswith(("re:", "re[")) else f"Re: {subject}".strip()


def message_id(sid: int, address: str) -> str:
    domain = address.rsplit("@", 1)[-1] or "kb.local"
    return f"<kb-suggestion-{sid}@{domain}>"


def build_reply(
    conn: Conn, sid: int, payload: dict[str, Any], box: Mailbox, now: datetime
) -> EmailMessage:
    """The reply as an RFC 5322 message: to the thread's last other author unless the draft
    names recipients, threaded under the last message."""
    t = thread_headers(conn, int(payload["item_id"]))
    me = box.address.lower()
    to = payload.get("to") or [
        t["last_author"]
        if t["last_author"] and t["last_author"].lower() != me
        else next((p for p in t["participants"] if p.lower() != me), "")
    ]
    to = [a for a in to if a]
    if not to:
        raise MailError("no recipient for this reply")
    msg = EmailMessage()
    msg["From"] = box.address
    msg["To"] = ", ".join(to)
    if payload.get("cc"):
        msg["Cc"] = ", ".join(payload["cc"])
    msg["Subject"] = payload.get("subject") or reply_subject(t["subject"])
    msg["Date"] = format_datetime(now)
    msg["Message-ID"] = message_id(sid, box.address)
    msg["In-Reply-To"] = t["in_reply_to"]
    msg["References"] = " ".join(dict.fromkeys(t["references"]))
    msg.set_content(payload.get("body") or "")
    return msg


def special_folder(client: Any, flag: bytes, names: tuple[str, ...], what: str) -> str:
    seen = []
    for flags, _, name in client.list_folders():
        if flag in flags:
            return str(name)
        seen.append(str(name))
    for candidate in names:
        if candidate in seen:
            return candidate
    raise MailError(f"no {what} folder in this mailbox")


def mailbox_for_address(conn: Conn, config: Config, address: str) -> str:
    """The mailbox last used with this address, else the first connected one."""
    from kb.connectors import accounts

    row = conn.execute(
        "SELECT source_id FROM messages WHERE kind = 'email' AND EXISTS ("
        " SELECT 1 FROM unnest(participants) p WHERE lower(p) LIKE '%%' || lower(%s) || '%%')"
        " ORDER BY sent_at DESC LIMIT 1",
        (address,),
    ).fetchone()
    if row is not None:
        return str(row["source_id"])
    for s in accounts.effective_config(conn, config).sources:
        if isinstance(s, ImapSource):
            return s.id
    raise MailError("no mailbox is connected")


def build_new(sid: int, payload: dict[str, Any], box: Mailbox, now: datetime) -> EmailMessage:
    to = [a for a in payload.get("to") or [] if a]
    if not to:
        raise MailError("a new email needs a recipient")
    msg = EmailMessage()
    msg["From"] = box.address
    msg["To"] = ", ".join(to)
    if payload.get("cc"):
        msg["Cc"] = ", ".join(payload["cc"])
    msg["Subject"] = payload.get("subject") or ""
    msg["Date"] = format_datetime(now)
    msg["Message-ID"] = message_id(sid, box.address)
    msg.set_content(payload.get("body") or "")
    return msg


def compose(
    conn: Conn, config: Config, sid: int, kind: str, payload: dict[str, Any], now: datetime
) -> tuple[Mailbox, EmailMessage]:
    """The mailbox and message for an email suggestion: a reply in its thread, or a new email."""
    if kind == "email":
        source = payload.get("source_id") or mailbox_for_address(
            conn, config, (payload.get("to") or [""])[0]
        )
        box = mailbox(conn, config, source)
        return box, build_new(sid, payload, box, now)
    thread = thread_headers(conn, int(payload["item_id"]))
    box = mailbox(conn, config, thread["source_id"])
    return box, build_reply(conn, sid, payload, box, now)


def drafts_folder(client: Any) -> str:
    return special_folder(client, b"\\Drafts", DRAFT_FOLDER_NAMES, "Drafts")


def copy_to_sent(client: Any, msg: EmailMessage, now: datetime) -> None:
    """Gmail files sent mail itself; other servers need the copy appended to Sent."""
    folder = special_folder(client, b"\\Sent", SENT_FOLDER_NAMES, "Sent")
    client.append(folder, msg.as_bytes(), flags=[b"\\Seen"], msg_time=now)


def open_smtp(box: Mailbox) -> Any:
    import smtplib
    import ssl

    if not box.smtp_host:
        raise MailError(f"sending is not set up for {box.address} (no SMTP server)")
    context = ssl.create_default_context()
    if box.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            box.smtp_host, box.smtp_port, timeout=30, context=context
        )
    else:
        server = smtplib.SMTP(box.smtp_host, box.smtp_port, timeout=30)
        server.starttls(context=context)
    server.login(box.smtp_username or box.address, box.smtp_password)
    return server


def save_draft(client: Any, msg: EmailMessage, now: datetime) -> str:
    """Appends the message to Drafts once (looked up by Message-ID first)."""
    folder = drafts_folder(client)
    client.select_folder(folder)
    mid = str(msg["Message-ID"])
    if client.search(["HEADER", "Message-ID", mid]):
        return mid
    client.append(folder, msg.as_bytes(), flags=[b"\\Draft"], msg_time=now)
    return mid


def open_imap(box: Mailbox) -> Any:
    from kb.connectors import imap

    return imap.open_client(box.imap)
