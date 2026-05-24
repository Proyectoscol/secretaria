"""
services/microsoft/crypto.py — AES-256-GCM encrypt/decrypt for Microsoft tokens.

MUST produce output byte-for-byte compatible with frontend/lib/crypto.ts.
Wire format (base64-encoded):
  bytes[0:12]  — 96-bit IV (random, unique per encrypt call)
  bytes[12:28] — 128-bit GCM authentication tag
  bytes[28:]   — ciphertext

Key: 32 bytes, base64-encoded in MICROSOFT_TOKEN_ENCRYPTION_KEY env var.
Generate with: openssl rand -base64 32
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_IV_LENGTH  = 12   # 96 bits — GCM recommended
_TAG_LENGTH = 16   # 128 bits


def _get_key() -> bytes:
    raw = os.environ.get("MICROSOFT_TOKEN_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError("MICROSOFT_TOKEN_ENCRYPTION_KEY is not set")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError(
            f"MICROSOFT_TOKEN_ENCRYPTION_KEY must decode to 32 bytes, got {len(key)}"
        )
    return key


def encrypt(plaintext: str) -> str:
    """
    Encrypt `plaintext` using AES-256-GCM.
    Returns base64(iv + tag + ciphertext) — same format as TypeScript encryptToken().
    """
    key = _get_key()
    iv  = os.urandom(_IV_LENGTH)

    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext + tag appended
    ct_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    # ct_with_tag layout: ciphertext[:-16] + tag[-16:]
    ciphertext = ct_with_tag[:-_TAG_LENGTH]
    tag        = ct_with_tag[-_TAG_LENGTH:]

    payload = iv + tag + ciphertext
    return base64.b64encode(payload).decode("ascii")


def decrypt(ciphertext_b64: str) -> str:
    """
    Decrypt a value produced by encrypt() or frontend encryptToken().
    Returns the original plaintext string.
    """
    key  = _get_key()
    data = base64.b64decode(ciphertext_b64)

    iv         = data[:_IV_LENGTH]
    tag        = data[_IV_LENGTH : _IV_LENGTH + _TAG_LENGTH]
    ciphertext = data[_IV_LENGTH + _TAG_LENGTH :]

    aesgcm = AESGCM(key)
    # AESGCM.decrypt expects ciphertext + tag concatenated
    plaintext_bytes = aesgcm.decrypt(iv, ciphertext + tag, None)
    return plaintext_bytes.decode("utf-8")
