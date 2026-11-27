"""A proteção HTTP cobre rotas adicionadas e documentação em todos os perfis."""

from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from fall.api.main import create_app
from fall.config import Environment, Settings


@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/new"), ("POST", "/v1/new"), ("HEAD", "/health"),
    ("POST", "/health"), ("GET", "/v1/sessions"),
    ("POST", "/v1/sessions/"), ("GET", "/health/"),
    ("GET", "/v1/missing"), ("GET", "/openapi.json"),
])
def test_protection_is_default_for_methods_and_paths(method, path):
    app = create_app(Settings(Environment.TEST))

    @app.api_route("/v1/new", methods=["GET", "POST"])
    def new_route():
        return {"ok": True}

    with TestClient(app, follow_redirects=False) as client:
        response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    if method != "HEAD":
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
        assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"},
    {"Authorization": "Bearer malformed extra"},
    {"Authorization": "Bearer token-sentinel"},
    [("Authorization", "Bearer first"), ("Authorization", "Bearer second")],
])
def test_invalid_authorization_is_safe(headers):
    app = create_app(Settings(Environment.TEST))
    with TestClient(app) as client:
        response = client.get("/v1/new", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "sentinel" not in response.text


def test_valid_session_reaches_new_route_with_session_owner(monkeypatch):
    owner = uuid4()
    monkeypatch.setattr("fall.api.authentication._authenticate", lambda token, settings: owner)
    app = create_app(Settings(Environment.TEST))

    @app.get("/v1/new")
    def new_route(request: Request):
        return {"owner": str(request.state.user_id)}

    with TestClient(app) as client:
        assert client.get("/v1/new", headers={"Authorization": "bearer test"}).json() == {
            "owner": str(owner)
        }


def test_public_operations_do_not_validate_presented_session(monkeypatch):
    def fail(*args):
        raise AssertionError("A chamada pública não deve validar sessão")

    monkeypatch.setattr("fall.api.authentication._authenticate", fail)
    app = create_app(Settings(Environment.TEST))
    with TestClient(app) as client:
        assert client.get("/health", headers={"Authorization": "Bearer test"}).status_code == 200
        response = client.post("/v1/sessions", json={}, headers={"Authorization": "Bearer test"})
        assert response.status_code == 422


@pytest.mark.parametrize("environment,availability", [
    (Environment.DEVELOPMENT, (200, 200, 200)),
    (Environment.TEST, (200, 200, 404)),
    (Environment.STAGING, (200, 404, 404)),
    (Environment.PRODUCTION, (404, 404, 404)),
])
def test_documentation_is_protected_without_changing_profiles(environment, availability, authenticated_headers):
    app = create_app(Settings(environment))
    with TestClient(app) as client:
        for path, status in zip(("/openapi.json", "/docs", "/redoc"), availability):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=authenticated_headers).status_code == status
        if availability[0] == 200:
            schema = client.get("/openapi.json", headers=authenticated_headers).json()
            assert schema["security"] == [{"BearerAuth": []}]
            assert schema["components"]["securitySchemes"]["BearerAuth"] == {
                "type": "http", "scheme": "bearer"
            }
            assert schema["paths"]["/health"]["get"]["security"] == []
            assert schema["paths"]["/v1/sessions"]["post"]["security"] == []


def test_authentication_infrastructure_failure_is_safe(monkeypatch):
    def fail(*args):
        raise RuntimeError("secret-sentinel")

    monkeypatch.setattr("fall.api.authentication._authenticate", fail)
    app = create_app(Settings(Environment.TEST))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/new", headers={"Authorization": "Bearer token-sentinel"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "sentinel" not in response.text
