"""Authentication and tenant resolution for Supabase JWTs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.config import settings


ORG_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class TenantContext:
    """Verified identity and tenant extracted from a Supabase access token."""

    user_id: str
    org_id: str


def _unauthorized(detail: str = "Authentication required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_segment(segment: str) -> dict[str, Any]:
    try:
        padded = segment + "=" * (-len(segment) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise _unauthorized("Malformed access token.") from exc
    if not isinstance(value, dict):
        raise _unauthorized("Malformed access token.")
    return value


def _numeric_claim(payload: dict[str, Any], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _unauthorized("Invalid access token.")
    return float(value)


def _validated_org_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    org_id = value.strip()
    return org_id if ORG_ID_PATTERN.fullmatch(org_id) else None


def _verify_hs256(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise _unauthorized("Malformed access token.")

    header = _decode_segment(parts[0])
    if header.get("alg") != "HS256":
        raise _unauthorized("Unsupported access-token algorithm.")

    secret = settings.supabase_jwt_secret
    if not secret or not settings.jwt_issuer:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT verification is not configured.",
        )

    try:
        supplied_signature = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
    except (ValueError, binascii.Error) as exc:
        raise _unauthorized("Malformed access token.") from exc

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise _unauthorized("Invalid access token.")

    payload = _decode_segment(parts[1])
    if _numeric_claim(payload, "exp") <= time.time():
        raise _unauthorized("Access token has expired.")

    audience = payload.get("aud")
    valid_audience = audience == settings.supabase_jwt_audience or (
        isinstance(audience, list) and settings.supabase_jwt_audience in audience
    )
    if not valid_audience or payload.get("iss") != settings.jwt_issuer:
        raise _unauthorized("Invalid access token claims.")

    if not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
        raise _unauthorized("Invalid access token claims.")
    return payload


def _trusted_service_context(request: Request) -> TenantContext | None:
    if not settings.trusted_tenant_header_enabled:
        return None

    service_token = request.headers.get("x-service-token")
    configured_token = settings.trusted_service_token
    if not service_token or not configured_token or not hmac.compare_digest(service_token, configured_token):
        raise _unauthorized("Trusted service authentication required.")

    org_id = request.headers.get("x-org-id")
    org_id = _validated_org_id(org_id)
    if not org_id:
        raise _unauthorized("Trusted service request is missing a tenant.")
    return TenantContext(user_id="trusted-service", org_id=org_id)


def get_tenant_context(request: Request) -> TenantContext:
    """Authenticate a request and return its verified tenant context."""
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise _unauthorized("Malformed authorization header.")
        payload = _verify_hs256(token.strip())
        app_metadata = payload.get("app_metadata")
        org_id = app_metadata.get("org_id") if isinstance(app_metadata, dict) else None
        org_id = _validated_org_id(org_id)
        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated user is not assigned to an organization.",
            )
        return TenantContext(user_id=payload["sub"].strip(), org_id=org_id)

    service_context = _trusted_service_context(request)
    if service_context is not None:
        return service_context
    raise _unauthorized()
