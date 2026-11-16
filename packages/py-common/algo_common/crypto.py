"""AES-256-GCM envelope for secrets at rest (broker credentials, TOTP seeds).

Ciphertext format: ``<key_id>:<base64(nonce || ciphertext || tag)>``.
The associated data binds a ciphertext to its owner (e.g. ``user:<id>``), so a
row copied to another user cannot be decrypted. Old keys can be kept in
``VAULT_PREVIOUS_KEYS`` for rotation; `Vault.rotate()` re-encrypts with the
current key. In production the master key should come from a KMS (AWS KMS in
ap-south-1) and be injected as an env var by the orchestrator.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    pass


class Vault:
    def __init__(self, key_id: str, master_key_b64: str, previous: dict[str, str] | None = None) -> None:
        self.key_id = key_id
        self._keys: dict[str, bytes] = {}
        for kid, b64 in {**(previous or {}), key_id: master_key_b64}.items():
            raw = base64.b64decode(b64)
            if len(raw) != 32:
                raise VaultError(f"vault key {kid!r} must be 32 bytes (got {len(raw)})")
            self._keys[kid] = raw

    @classmethod
    def from_settings(cls) -> Vault:
        from algo_common.settings import get_settings

        s = get_settings()
        prev: dict[str, str] = {}
        if s.vault_previous_keys:
            for pair in s.vault_previous_keys.get_secret_value().split(","):
                if ":" in pair:
                    kid, key = pair.split(":", 1)
                    prev[kid.strip()] = key.strip()
        return cls(s.vault_key_id, s.vault_master_key.get_secret_value(), prev)

    def encrypt(self, plaintext: str | bytes, aad: str = "") -> str:
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self.key_id]).encrypt(nonce, data, aad.encode())
        return f"{self.key_id}:{base64.b64encode(nonce + ct).decode()}"

    def decrypt(self, token: str, aad: str = "") -> str:
        try:
            kid, b64 = token.split(":", 1)
            key = self._keys[kid]
            blob = base64.b64decode(b64)
            return AESGCM(key).decrypt(blob[:12], blob[12:], aad.encode()).decode()
        except KeyError as exc:
            raise VaultError("unknown vault key id") from exc
        except Exception as exc:
            raise VaultError("decryption failed") from exc

    def encrypt_json(self, value: dict[str, Any], aad: str = "") -> str:
        return self.encrypt(json.dumps(value, separators=(",", ":")), aad)

    def decrypt_json(self, token: str, aad: str = "") -> dict[str, Any]:
        return json.loads(self.decrypt(token, aad))  # type: ignore[no-any-return]

    def rotate(self, token: str, aad: str = "") -> str:
        return self.encrypt(self.decrypt(token, aad), aad)

    def needs_rotation(self, token: str) -> bool:
        return not token.startswith(f"{self.key_id}:")


def mask(value: str | None, keep: int = 4) -> str:
    """Return a display-safe version of a secret (``••••abcd``)."""
    if not value:
        return ""
    return "•" * max(0, min(8, len(value) - keep)) + value[-keep:]
