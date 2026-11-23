"""Formatos HTTP de acesso consumidos pelas rotas de sessão."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr


class SessionCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    login: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00]+$")
    password: SecretStr = Field(min_length=1)


class SessionGrant(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["Bearer"] = "Bearer"
    absolute_expires_at: AwareDatetime


class CurrentUser(BaseModel):
    user_id: UUID
