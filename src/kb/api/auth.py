"""Owner sign-in for the web OS: passkeys (WebAuthn), setup codes and sessions (design D2).

There are no passwords. The first passkey needs a one-time setup code created on the server
(`kb web setup-code`); later passkeys can only be added from a signed-in session. Sessions are
random tokens in an HttpOnly cookie; the database keeps only their sha256.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from kb.db import Conn

SESSION_COOKIE = "kb_session"
CHALLENGE_COOKIE = "kb_challenge"
SESSION_DAYS = 30
SETUP_CODE_TTL = timedelta(hours=1)
CHALLENGE_TTL = timedelta(minutes=5)
_SLIDE_AFTER = timedelta(hours=1)  # refresh a session's expiry at most hourly


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RelyingParty:
    """The web OS origin (KB_WEB_ORIGIN), e.g. https://os.example.com."""

    origin: str

    @property
    def rp_id(self) -> str:
        return urlparse(self.origin).hostname or ""

    @property
    def secure_cookies(self) -> bool:
        return self.origin.startswith("https://")


def _hash(value: str | bytes) -> bytes:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).digest()


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


# --- setup codes ----------------------------------------------------------------------------


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def new_setup_code(conn: Conn, now: datetime) -> str:
    raw = base64.b32encode(secrets.token_bytes(5)).decode()  # 8 characters
    conn.execute(
        "INSERT INTO setup_codes (code_hash, expires_at) VALUES (%s, %s)",
        (_hash(raw), now + SETUP_CODE_TTL),
    )
    return f"{raw[:4]}-{raw[4:]}"


def _valid_setup_code(conn: Conn, code: str | None, now: datetime) -> bytes | None:
    if not code:
        return None
    code_hash = _hash(_normalize_code(code))
    row = conn.execute(
        "SELECT 1 FROM setup_codes WHERE code_hash = %s AND used_at IS NULL AND expires_at > %s",
        (code_hash, now),
    ).fetchone()
    return code_hash if row else None


def has_passkeys(conn: Conn, rp_id: str) -> bool:
    """Whether a passkey exists for this domain (passkeys of an earlier domain cannot sign in)."""
    row = conn.execute("SELECT 1 FROM webauthn_credentials WHERE rp_id = %s LIMIT 1", (rp_id,))
    return row.fetchone() is not None


# --- sessions -------------------------------------------------------------------------------


def create_session(conn: Conn, device: str, now: datetime, needs_passkey: bool = False) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO web_sessions (token_hash, device, created_at, last_seen_at, expires_at,"
        " needs_passkey) VALUES (%s, %s, %s, %s, %s, %s)",
        (_hash(token), device[:200], now, now, now + timedelta(days=SESSION_DAYS), needs_passkey),
    )
    return token


def session_for(conn: Conn, token: str | None, now: datetime) -> dict[str, Any] | None:
    """The live session for a cookie value (sliding 30-day expiry), or None."""
    if not token:
        return None
    row = conn.execute(
        "SELECT token_hash, device, last_seen_at, needs_passkey FROM web_sessions"
        " WHERE token_hash = %s AND expires_at > %s",
        (_hash(token), now),
    ).fetchone()
    if row is None:
        return None
    if now - row["last_seen_at"] > _SLIDE_AFTER:
        conn.execute(
            "UPDATE web_sessions SET last_seen_at = %s, expires_at = %s WHERE token_hash = %s",
            (now, now + timedelta(days=SESSION_DAYS), row["token_hash"]),
        )
    return dict(row)


def end_session(conn: Conn, token: str) -> None:
    conn.execute("DELETE FROM web_sessions WHERE token_hash = %s", (_hash(token),))


# --- WebAuthn ceremonies --------------------------------------------------------------------


def _store_challenge(
    conn: Conn, kind: str, challenge: bytes, now: datetime, setup_code_hash: bytes | None = None
) -> str:
    cid = secrets.token_urlsafe(16)
    conn.execute("DELETE FROM webauthn_challenges WHERE expires_at < %s", (now,))
    conn.execute(
        "INSERT INTO webauthn_challenges (id, kind, challenge, setup_code_hash, expires_at)"
        " VALUES (%s, %s, %s, %s, %s)",
        (cid, kind, challenge, setup_code_hash, now + CHALLENGE_TTL),
    )
    return cid


def _take_challenge(conn: Conn, cid: str | None, kind: str, now: datetime) -> dict[str, Any]:
    row = (
        conn.execute(
            "DELETE FROM webauthn_challenges WHERE id = %s RETURNING kind, challenge,"
            " setup_code_hash, expires_at",
            (cid,),
        ).fetchone()
        if cid
        else None
    )
    if row is None or row["kind"] != kind or row["expires_at"] <= now:
        raise AuthError(400, "The sign-in attempt expired; start again.")
    return dict(row)


def begin_registration(
    conn: Conn, rp: RelyingParty, setup_code: str | None, signed_in: bool, now: datetime
) -> tuple[str, str]:
    """Returns (challenge id, options JSON for navigator.credentials.create)."""
    code_hash = None
    if has_passkeys(conn, rp.rp_id):
        if not signed_in:
            raise AuthError(403, "Sign in with an existing passkey to add another one.")
    else:
        code_hash = _valid_setup_code(conn, setup_code, now)
        if code_hash is None:
            raise AuthError(403, "A valid setup code is required for the first passkey.")
    existing = [
        PublicKeyCredentialDescriptor(id=bytes(r["id"]))
        for r in conn.execute("SELECT id FROM webauthn_credentials WHERE rp_id = %s", (rp.rp_id,))
    ]
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name="Second brain",
        user_name="owner",
        user_id=b"second-brain-owner",
        user_display_name="Owner",
        exclude_credentials=existing,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    cid = _store_challenge(conn, "register", options.challenge, now, code_hash)
    return cid, options_to_json(options)


def finish_registration(
    conn: Conn,
    rp: RelyingParty,
    challenge_id: str | None,
    credential: dict[str, Any],
    device: str,
    signed_in: bool,
    now: datetime,
) -> str | None:
    """Stores the new passkey. Returns a new session token on first enrollment, else None."""
    pending = _take_challenge(conn, challenge_id, "register", now)
    code_hash = pending["setup_code_hash"]
    if code_hash is not None:
        still_valid = conn.execute(
            "SELECT 1 FROM setup_codes WHERE code_hash = %s AND used_at IS NULL"
            " AND expires_at > %s",
            (code_hash, now),
        ).fetchone()
        if not still_valid or has_passkeys(conn, rp.rp_id):
            raise AuthError(403, "The setup code was already used or expired.")
    elif not signed_in:
        raise AuthError(403, "Sign in with an existing passkey to add another one.")
    try:
        verified = verify_registration_response(
            credential=json.dumps(credential),
            expected_challenge=bytes(pending["challenge"]),
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
        )
    except Exception as e:  # the library raises several exception types for bad responses
        raise AuthError(400, f"The passkey could not be verified: {e}") from e
    conn.execute(
        "INSERT INTO webauthn_credentials (id, public_key, sign_count, transports, device, rp_id)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (
            verified.credential_id,
            verified.credential_public_key,
            verified.sign_count,
            list(credential.get("response", {}).get("transports") or []),
            device[:200],
            rp.rp_id,
        ),
    )
    if code_hash is not None:
        conn.execute("UPDATE setup_codes SET used_at = %s WHERE code_hash = %s", (now, code_hash))
        return create_session(conn, device, now)
    return None


def begin_login(conn: Conn, rp: RelyingParty, now: datetime) -> tuple[str, str]:
    options = generate_authentication_options(
        rp_id=rp.rp_id, user_verification=UserVerificationRequirement.PREFERRED
    )
    return _store_challenge(conn, "login", options.challenge, now), options_to_json(options)


def finish_login(
    conn: Conn,
    rp: RelyingParty,
    challenge_id: str | None,
    credential: dict[str, Any],
    device: str,
    now: datetime,
) -> str:
    pending = _take_challenge(conn, challenge_id, "login", now)
    try:
        cred_id = _b64url_decode(str(credential.get("rawId") or credential.get("id") or ""))
    except ValueError as e:
        raise AuthError(400, "Malformed passkey response.") from e
    stored = conn.execute(
        "SELECT public_key, sign_count FROM webauthn_credentials WHERE id = %s AND rp_id = %s",
        (cred_id, rp.rp_id),
    ).fetchone()
    if stored is None:
        raise AuthError(401, "This passkey is not registered here.")
    try:
        verified = verify_authentication_response(
            credential=json.dumps(credential),
            expected_challenge=bytes(pending["challenge"]),
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
        )
    except Exception as e:
        raise AuthError(401, f"The passkey could not be verified: {e}") from e
    conn.execute(
        "UPDATE webauthn_credentials SET sign_count = %s, last_used_at = %s WHERE id = %s",
        (verified.new_sign_count, now, cred_id),
    )
    return create_session(conn, device, now)


# --- recovery codes -------------------------------------------------------------------------

RECOVERY_CODES = 10
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _scrypt(code: str, salt: bytes) -> bytes:
    return hashlib.scrypt(_normalize_code(code).encode(), salt=salt, **_SCRYPT)


def new_recovery_codes(conn: Conn) -> list[str]:
    """Replaces all recovery codes with 10 new single-use ones; returns them (shown once)."""
    conn.execute("DELETE FROM recovery_codes")
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = base64.b32encode(secrets.token_bytes(10)).decode().lower()  # 16 characters
        code = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
        salt = secrets.token_bytes(16)
        conn.execute(
            "INSERT INTO recovery_codes (code_hash) VALUES (%s)", (salt + _scrypt(code, salt),)
        )
        codes.append(code)
    return codes


def remaining_recovery_codes(conn: Conn) -> int:
    row = conn.execute("SELECT count(*) AS n FROM recovery_codes WHERE used_at IS NULL").fetchone()
    return int(row["n"]) if row else 0


def recover(conn: Conn, code: str, device: str, now: datetime) -> str:
    """Signs in with a recovery code (single use); the session must then add a passkey."""
    for r in conn.execute(
        "SELECT id, code_hash FROM recovery_codes WHERE used_at IS NULL"
    ).fetchall():
        stored = bytes(r["code_hash"])
        if secrets.compare_digest(stored[16:], _scrypt(code, stored[:16])):
            conn.execute("UPDATE recovery_codes SET used_at = %s WHERE id = %s", (now, r["id"]))
            return create_session(conn, device, now, needs_passkey=True)
    raise AuthError(401, "That recovery code is not valid or was already used.")


# --- sessions (signed-in devices) -----------------------------------------------------------


def session_id(token_hash: bytes) -> str:
    return bytes(token_hash).hex()[:16]


def list_sessions(conn: Conn, current_token: str | None, now: datetime) -> list[dict[str, Any]]:
    current = _hash(current_token).hex()[:16] if current_token else None
    rows = conn.execute(
        "SELECT token_hash, device, created_at, last_seen_at, needs_passkey FROM web_sessions"
        " WHERE expires_at > %s ORDER BY last_seen_at DESC",
        (now,),
    ).fetchall()
    return [
        {
            "id": session_id(r["token_hash"]),
            "device": r["device"],
            "created_at": r["created_at"].isoformat(),
            "last_seen_at": r["last_seen_at"].isoformat(),
            "current": session_id(r["token_hash"]) == current,
            "recovery": r["needs_passkey"],
        }
        for r in rows
    ]


def revoke_session(conn: Conn, sid: str) -> int:
    rows = conn.execute(
        "DELETE FROM web_sessions WHERE encode(token_hash, 'hex') LIKE %s || '%%' RETURNING 1",
        (sid,),
    ).fetchall()
    return len(rows)


def revoke_other_sessions(conn: Conn, current_token: str) -> int:
    rows = conn.execute(
        "DELETE FROM web_sessions WHERE token_hash <> %s RETURNING 1", (_hash(current_token),)
    ).fetchall()
    return len(rows)


def passkey_added(conn: Conn, current_token: str) -> None:
    """A recovery session that registered a passkey becomes a normal session."""
    conn.execute(
        "UPDATE web_sessions SET needs_passkey = false WHERE token_hash = %s",
        (_hash(current_token),),
    )


def list_passkeys(conn: Conn, rp_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, device, created_at, last_used_at FROM webauthn_credentials WHERE rp_id = %s"
        " ORDER BY created_at",
        (rp_id,),
    ).fetchall()
    return [
        {
            "id": bytes(r["id"]).hex()[:16],
            "device": r["device"],
            "created_at": r["created_at"].isoformat(),
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
        }
        for r in rows
    ]
