"""Share-code generation and link-password hashing.

Passwords used to be stored in plain text. They are now salted scrypt hashes:
a leaked database or backup no longer reveals them. scrypt is CPU and memory
bound by design, so callers run it in a worker thread (``asyncio.to_thread``)
to keep the event loop free.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string

CODE_ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = 15

# 2**14 / 8 / 1 is the interactive-login recommendation: ~16 MiB, tens of ms.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_PREFIX = "scrypt"


def new_share_code(length: int = CODE_LENGTH) -> str:
    """Unguessable link code (``secrets``, not ``random``: codes are capabilities)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return "$".join(
        (_PREFIX, str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P), _b64(salt), _b64(digest))
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        prefix, n, r, p, salt, digest = encoded.split("$")
        if prefix != _PREFIX:
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, base64.b64decode(digest))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
