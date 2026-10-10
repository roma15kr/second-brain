"""Remove hard secrets from text before it is indexed, returned by tools or sent to an AI service.

Only hard secrets are redacted (passwords, payment cards, IBANs, one-time codes, API keys and
tokens, private keys). Names, phones, prices, dates and order numbers stay: they are what the
owner searches for. The archive keeps the original text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Redaction:
    kind: str
    start: int
    end: int


def placeholder(kind: str) -> str:
    return f"[REDACTED:{kind}]"


# --- checksums ---------------------------------------------------------------------------


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def looks_like_card(digits: str) -> bool:
    """Card brands by length + prefix (Visa, Mastercard, Maestro, Mir, Amex, UnionPay, Discover)."""
    n = len(digits)
    if n == 16 and digits[0] in "2456":
        return luhn_ok(digits)
    if n == 15 and digits[:2] in ("34", "37"):
        return luhn_ok(digits)
    if n == 19 and digits[0] in "456":
        return luhn_ok(digits)
    return False


def iban_ok(value: str) -> bool:
    v = value.replace(" ", "").upper()
    if not 15 <= len(v) <= 34:
        return False
    rearranged = v[4:] + v[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


# --- patterns ----------------------------------------------------------------------------

_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
_TOKENS = [
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),  # Telegram bot token
]
_BEARER = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)")
_KEY_CONTEXT = re.compile(
    r"(?i)\b(?:api[ _-]?key|secret(?:[ _-]?key)?|access[ _-]?key|auth[ _-]?token|token)"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9._~+/=-]{16,})"
)
_URL_CREDS = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/]+)@")
_PASSWORD = re.compile(
    r"(?i)(?:\b|^)(?:password|passwd|pwd|pass|passcode|пароль|пароля|паролю|парол|пасс|пасворд)"
    r"\b[^\n:=]{0,30}?\s*[:=]\s*(\S+)"
)
_OTP = re.compile(
    r"(?i)(?:\b|^)(code|codes|otp|pin|passcode|verification|one[- ]time|код|коду|кода|пін|пин|"
    r"підтвердження|подтверждения|верифікації|верификации)\b([^\d\n]{0,40}?)(\d{4,8})\b"
)
_GOOGLE_CODE = re.compile(r"\bG-\d{6}\b")
# "037402 is your verification code", "5521 — ваш код"
_OTP_BEFORE = re.compile(
    r"(?i)\b(\d{4,8})\s+(?:is\s+(?:your|the)\b|[\u2014\u2013-]|(?:это|це|ваш|your)\b)[^\n\d]{0,30}?"
    r"\b(?:code|codes|otp|pin|код|коду|кода)\b"
)
# Alphanumeric one-time codes: "Enter this code on the login page. GE5JA2"
_OTP_ALNUM = re.compile(
    r"(?i:\b(?:code|otp|passcode|verification|код|коду|кода)\b)[^\n]{0,80}?"
    r"\b((?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{5,8})\b"
)
# Password value without ":"/"=": the first secret-looking token shortly after the keyword.
_PASSWORD_LOOSE = re.compile(
    r"(?i:(?:\b|^)(?:password|passwd|pwd|passcode|пароль|пароля|паролем|пасс)\b)"
    r"[^\n]{0,60}?(?<!\S)"
    r"((?=\S*[A-Za-z\u0400-\u04ff])(?=\S*[\d!@#$%^&*_+=?~])\S{6,}|\d{6,})(?!\S)"
)
_OTP_NOT = re.compile(
    r"(?i)(єдрпоу|едрпоу|edrpou|іпн|инн|товар|артикул|sku|zip|індекс|индекс|поштов|почтов|"
    r"promo|промо|купон|coupon|discount|знижк|скидк|area|країн|стран|region|order|замовлення|"
    r"заказ)"
)
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){14,18}\d(?![\d-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")


def find(text: str) -> list[Redaction]:
    """All secret spans in `text`, non-overlapping, in order."""
    found: list[Redaction] = []

    def add(kind: str, start: int, end: int) -> None:
        found.append(Redaction(kind, start, end))

    for m in _PEM.finditer(text):
        add("private_key", m.start(), m.end())
    for rx in _TOKENS:
        for m in rx.finditer(text):
            add("token", m.start(), m.end())
    for rx in (_BEARER, _KEY_CONTEXT):
        for m in rx.finditer(text):
            add("token", m.start(1), m.end(1))
    for m in _URL_CREDS.finditer(text):
        add("password", m.start(1), m.end(1))
    for m in _PASSWORD.finditer(text):
        add("password", m.start(1), m.end(1))
    for m in _OTP.finditer(text):
        window = text[max(0, m.start() - 20) : m.start(3)]
        if not _OTP_NOT.search(window):
            add("otp", m.start(3), m.end(3))
    for m in _GOOGLE_CODE.finditer(text):
        add("otp", m.start(), m.end())
    for m in _OTP_BEFORE.finditer(text):
        add("otp", m.start(1), m.end(1))
    for m in _OTP_ALNUM.finditer(text):
        if not _OTP_NOT.search(text[max(0, m.start() - 20) : m.start(1)]):
            add("otp", m.start(1), m.end(1))
    for m in _PASSWORD_LOOSE.finditer(text):
        add("password", m.start(1), m.end(1))
    for m in _CARD.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if looks_like_card(digits):
            add("card", m.start(), m.end())
    for m in _IBAN.finditer(text):
        if iban_ok(m.group()):
            add("iban", m.start(), m.end())

    # Keep the earliest / longest span when detectors overlap.
    found.sort(key=lambda r: (r.start, -(r.end - r.start)))
    result: list[Redaction] = []
    for r in found:
        if result and r.start < result[-1].end:
            continue
        result.append(r)
    return result


def redact(text: str) -> tuple[str, list[Redaction]]:
    """Return text with each secret replaced by `[REDACTED:<kind>]`, and the spans found."""
    spans = find(text)
    if not spans:
        return text, []
    out: list[str] = []
    pos = 0
    for r in spans:
        out.append(text[pos : r.start])
        out.append(placeholder(r.kind))
        pos = r.end
    out.append(text[pos:])
    return "".join(out), spans


def redact_text(text: str | None) -> str:
    return redact(text)[0] if text else (text or "")
