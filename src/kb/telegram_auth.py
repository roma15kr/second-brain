"""Interactive Telegram login: by code (showing where Telegram sent it) or by QR code."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

Prompt = Callable[[str], str]
Say = Callable[[str], None]

QR_TIMEOUT_SECONDS = 60
QR_ATTEMPTS = 5


def describe_sent_code(sent: Any) -> str:
    """Human description of where Telegram delivered the login code (auth.SentCode)."""
    code_type = getattr(sent, "type", None)
    name = type(code_type).__name__.removeprefix("SentCodeType")
    length = getattr(code_type, "length", None)
    digits = f" ({length} digits)" if length else ""
    where = {
        "App": "as a message in the Telegram app, chat 'Telegram', on your logged-in devices",
        "Sms": "by SMS",
        "SmsWord": "by SMS (a word)",
        "SmsPhrase": "by SMS (a phrase)",
        "FirebaseSms": "by SMS via Google/Apple services (may not arrive for API logins)",
        "Call": "by a phone call that reads the code",
        "FlashCall": "as a missed call: the code is the calling number",
        "MissedCall": "as a missed call: the code is the last digits of the calling number",
        "FragmentSms": f"via Fragment: {getattr(code_type, 'url', '')}",
        "EmailCode": f"to your login email {getattr(code_type, 'email_pattern', '')}",
        "SetUpEmailRequired": "nowhere yet: Telegram requires a login email to be set up first",
    }.get(name, f"by an unknown method ({name})")
    text = f"Telegram sent the code {where}{digits}."
    next_type = getattr(sent, "next_type", None)
    if next_type is not None:
        alt = type(next_type).__name__.removeprefix("CodeType")
        timeout = getattr(sent, "timeout", None)
        wait = f" after {timeout}s" if timeout else ""
        text += f" Press Enter without a code to resend it by {alt}{wait}."
    return text


async def login_with_code(client: Any, ask: Prompt, ask_secret: Prompt, say: Say) -> Any:
    from telethon.errors import SessionPasswordNeededError
    from telethon.tl.functions.auth import ResendCodeRequest

    phone = ask("Phone number (international format, e.g. +380...): ").strip()
    sent = await client.send_code_request(phone)
    say(describe_sent_code(sent))
    while True:
        code = ask("Code (or Enter to resend another way): ").strip()
        if code:
            break
        sent = await client(ResendCodeRequest(phone, sent.phone_code_hash))
        say(describe_sent_code(sent))
    try:
        return await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
    except SessionPasswordNeededError:
        return await client.sign_in(password=ask_secret("Two-step verification password: "))


def render_qr(url: str) -> str:
    import io

    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    out = io.StringIO()
    qr.print_ascii(out=out, invert=True)
    return out.getvalue()


async def login_with_qr(client: Any, ask_secret: Prompt, say: Say) -> Any:
    from telethon.errors import SessionPasswordNeededError

    qr = await client.qr_login()
    for attempt in range(QR_ATTEMPTS):
        say(render_qr(qr.url))
        say(
            "Scan in Telegram: Settings → Devices → Link Desktop Device "
            f"(code valid ~{QR_TIMEOUT_SECONDS}s, attempt {attempt + 1}/{QR_ATTEMPTS})"
        )
        try:
            return await qr.wait(timeout=QR_TIMEOUT_SECONDS)
        except TimeoutError:
            await qr.recreate()
        except asyncio.TimeoutError:  # noqa: UP041 - telethon may raise the asyncio alias
            await qr.recreate()
        except SessionPasswordNeededError:
            return await client.sign_in(password=ask_secret("Two-step verification password: "))
    raise TimeoutError("QR code was not scanned; run the command again")


# --- login from the web OS (connectors spec: QR login on the page) -------------------------

WEB_POLL_SECONDS = 3.0
PASSWORD_WAIT_SECONDS = 300


async def web_login(conn: Any, client: Any, poll: float = WEB_POLL_SECONDS) -> Any:
    """Waits for a login request from the web OS and completes it by QR (and the two-step
    password when the account has one). Returns the logged-in user."""
    from telethon.errors import SessionPasswordNeededError

    from kb import secrets

    def update(rid: int, **fields: Any) -> None:
        sets = ", ".join(f"{k} = %s" for k in fields)
        conn.execute(
            f"UPDATE telegram_login SET {sets}, updated_at = now() WHERE id = %s",
            (*fields.values(), rid),
        )

    while True:
        req = conn.execute(
            "SELECT id FROM telegram_login WHERE status = 'pending' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if req is None:
            await asyncio.sleep(poll)
            continue
        rid = req["id"]
        qr = await client.qr_login()
        update(rid, status="qr", qr_url=qr.url)
        try:
            return await qr.wait(timeout=QR_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 - telethon may raise the alias
            update(rid, status="expired", qr_url=None)
            continue
        except SessionPasswordNeededError:
            update(rid, status="password_needed", qr_url=None)
        waited = 0.0
        while waited < PASSWORD_WAIT_SECONDS:
            row = conn.execute("SELECT secret FROM telegram_login WHERE id = %s", (rid,)).fetchone()
            if row and row["secret"]:
                password = secrets.unseal(row["secret"])["password"]
                update(rid, secret=None)
                try:
                    user = await client.sign_in(password=password)
                except Exception as e:
                    update(rid, status="failed", error=f"two-step password rejected: {e}")
                    break
                update(rid, status="done")
                return user
            await asyncio.sleep(poll)
            waited += poll
        else:
            update(rid, status="expired", secret=None)
