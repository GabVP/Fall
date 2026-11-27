"""Expõe aos endpoints somente o proprietário da sessão validada."""

from fastapi import Request

from fall.application.ownership import OwnerScope


def authenticated_owner(request: Request) -> OwnerScope:
    return OwnerScope(request.state.user_id)
