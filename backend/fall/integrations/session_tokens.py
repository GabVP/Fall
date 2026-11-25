"""Gera tokens opacos e o resumo persistível de sessão."""

import hashlib
import secrets


class OpaqueSessionTokens:
    def issue(self) -> str:
        return secrets.token_urlsafe(32)

    def digest(self, token: str) -> bytes | None:
        return hashlib.sha256(token.encode("ascii")).digest()
