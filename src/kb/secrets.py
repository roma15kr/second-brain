"""Credentials entered in the web OS, encrypted at rest (design D11).

AES-GCM with a key from KB_SECRET_KEY (set only in Coolify). The key may be 32 bytes in base64
or any long passphrase (hashed to 32 bytes). Losing the key means re-entering credentials;
database backups only ever contain ciphertext.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets as _random
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"


class SecretsError(RuntimeError):
    pass


def _key() -> bytes:
    raw = os.environ.get("KB_SECRET_KEY", "")
    if len(raw) < 16:
        raise SecretsError("KB_SECRET_KEY is not set (needed to store credentials)")
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except ValueError:
        pass
    return hashlib.sha256(raw.encode()).digest()


def seal(value: dict[str, Any]) -> bytes:
    nonce = _random.token_bytes(12)
    data = json.dumps(value).encode()
    return VERSION + nonce + AESGCM(_key()).encrypt(nonce, data, VERSION)


def unseal(blob: bytes) -> dict[str, Any]:
    blob = bytes(blob)
    if blob[:1] != VERSION:
        raise SecretsError("unknown secret format")
    try:
        data = AESGCM(_key()).decrypt(blob[1:13], blob[13:], VERSION)
    except Exception as e:  # wrong key or tampered ciphertext
        raise SecretsError("cannot decrypt stored credentials (KB_SECRET_KEY changed?)") from e
    return dict(json.loads(data))
