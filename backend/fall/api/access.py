"""Login HTTP e formatos públicos de acesso."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from fall.application.sessions import create_session
from fall.integrations.clock import SystemClock
from fall.integrations.passwords import Argon2PasswordHasher
from fall.integrations.session_tokens import OpaqueSessionTokens
from fall.persistence.access import PostgresSessionRepository, PostgresUserRepository
from fall.persistence.database import create_database_engine, load_database_url


router = APIRouter()


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


@router.post("/v1/sessions", response_model=SessionGrant)
def login(credentials: SessionCredentials, request: Request, response: Response) -> SessionGrant:
    engine = create_database_engine(load_database_url(request.app.state.settings.environment))
    try:
        issued = create_session(
            credentials.login,
            credentials.password.get_secret_value(),
            users=PostgresUserRepository(engine),
            sessions=PostgresSessionRepository(engine),
            hasher=Argon2PasswordHasher(),
            tokens=OpaqueSessionTokens(),
            clock=SystemClock(),
        )
    finally:
        engine.dispose()
    if issued is None:
        raise HTTPException(status_code=401)
    response.headers["Cache-Control"] = "no-store"
    return SessionGrant(
        access_token=issued.access_token, absolute_expires_at=issued.absolute_expires_at
    )
