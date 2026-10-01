import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core import auth
from app.main import app

from auth_test_utils import mint_test_token


client = TestClient(app, raise_server_exceptions=False)


def test_missing_token_returns_401():
    response = client.get("/charges")
    assert response.status_code == 401


def test_invalid_expired_and_wrong_audience_tokens_return_401():
    invalid = client.get("/charges", headers={"Authorization": "Bearer not-a-jwt"})
    expired = client.get(
        "/charges",
        headers={"Authorization": f"Bearer {mint_test_token(expires_at=1)}"},
    )
    wrong_audience = client.get(
        "/charges",
        headers={"Authorization": "Bearer " + mint_test_token(audience="not-authenticated")},
    )
    assert invalid.status_code == 401
    assert expired.status_code == 401
    assert wrong_audience.status_code == 401


def test_user_metadata_org_id_is_not_authorized():
    token = mint_test_token(org_id=None, user_metadata_org_id="org_demo_alpha")
    response = client.get("/charges", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_header_and_query_tenant_are_ignored_when_trusted_path_is_disabled():
    request = auth.Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (b"authorization", ("Bearer " + mint_test_token("org_demo_alpha")).encode()),
                (b"x-org-id", b"org_demo_bravo"),
            ],
            "query_string": b"org_id=org_demo_bravo",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    context = auth.get_tenant_context(request)
    assert context.org_id == "org_demo_alpha"


def test_trusted_header_path_requires_service_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "trusted_tenant_header_enabled", True)
    monkeypatch.setattr(auth.settings, "trusted_service_token", "service-secret")
    request = auth.Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-org-id", b"org_demo_bravo")],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    try:
        auth.get_tenant_context(request)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
    else:
        raise AssertionError("Missing service token must be rejected")

    request = auth.Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-org-id", b"org_demo_bravo"), (b"x-service-token", b"wrong")],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    try:
        auth.get_tenant_context(request)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
    else:
        raise AssertionError("Wrong service token must be rejected")


def test_missing_jwt_secret_or_issuer_fails_closed(monkeypatch):
    token = mint_test_token("org_demo_alpha")
    monkeypatch.setattr(auth.settings, "supabase_jwt_secret", None)
    with pytest.raises(Exception) as secret_error:
        auth._verify_hs256(token)
    assert secret_error.value.status_code == 503

    monkeypatch.setattr(auth.settings, "supabase_jwt_secret", "test-jwt-secret")
    monkeypatch.setattr(auth.settings, "supabase_jwt_issuer", None)
    monkeypatch.setattr(auth.settings, "supabase_url", None)
    with pytest.raises(Exception) as issuer_error:
        auth._verify_hs256(token)
    assert issuer_error.value.status_code == 503


def test_invalid_org_id_is_rejected():
    token = mint_test_token(org_id="org/demo")
    response = client.get("/charges", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_api_documentation_is_disabled_by_default():
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_cors_preflight_does_not_require_authentication():
    response = client.options(
        "/charges",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
