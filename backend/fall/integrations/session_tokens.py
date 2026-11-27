"""Gera tokens opacos e o resumo persistível de sessão."""

import hashlib
import secrets
from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error


class OpaqueSessionTokens:
    def issue(self) -> str:
        return secrets.token_urlsafe(32)

    def digest(self, token: str) -> bytes | None:
        if len(token) != 43:
            return None
        try:
            raw_token = b64decode(token + "=", altchars=b"-_", validate=True)
        except (Base64Error, ValueError):
            return None
        if urlsafe_b64encode(raw_token).rstrip(b"=").decode("ascii") != token:
            return None
        return hashlib.sha256(token.encode("ascii")).digest()
