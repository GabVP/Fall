"""Casos síncronos da composição dos endpoints de acesso."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from fall.api import access
from fall.api.main import create_app
from fall.config import Environment, Settings


def test_current_user_exposes_only_authenticated_owner():
    user_id = uuid4()
    request = SimpleNamespace(state=SimpleNamespace(user_id=user_id, session_token="secret"))
    assert access.current_user(request).model_dump(mode="json") == {"user_id": str(user_id)}


@pytest.mark.parametrize("revoked", [True, False])
def test_logout_revokes_presented_token_and_disposes_engine(monkeypatch, revoked):
    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = Engine()
    request = SimpleNamespace(
        state=SimpleNamespace(session_token="token-sentinel"),
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(environment="test"))),
    )
    calls = []
    monkeypatch.setattr(access, "load_database_url", lambda environment: "database-url")
    monkeypatch.setattr(access, "create_database_engine", lambda url: engine)
    monkeypatch.setattr(access, "revoke_session", lambda token, **kwargs: calls.append(token) or revoked)

    if revoked:
        response = access.logout(request)
        assert response.status_code == 204
        assert response.body == b""
    else:
        with pytest.raises(HTTPException) as error:
            access.logout(request)
        assert error.value.status_code == 401
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}
    assert calls == ["token-sentinel"]
    assert engine.disposed


def test_openapi_describes_protected_access_endpoints():
    schema = create_app(Settings(Environment.TEST)).openapi()
    me = schema["paths"]["/v1/me"]["get"]
    logout = schema["paths"]["/v1/sessions/current"]["delete"]
    assert me["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CurrentUser"
    }
    assert set(schema["components"]["schemas"]["CurrentUser"]["properties"]) == {"user_id"}
    assert "204" in logout["responses"]
    assert schema["security"] == [{"BearerAuth": []}]
