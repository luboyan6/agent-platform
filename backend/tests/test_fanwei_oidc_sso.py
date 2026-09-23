"""Offline contract tests for the Fanwei E10 OIDC adapter.

These tests intentionally use synthetic issuer, subject, tokens, and profile
values. They exercise the trust boundary without needing an OA deployment or
any real client credential.
"""

from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Request
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCError, OIDCIdentity, OIDCMetadata, OIDCService, OIDCValidationError
from app.gateway.auth.oidc_adapters import FanweiProfileError, derive_shadow_email, normalize_fanwei_profile
from app.gateway.auth.oidc_state import OIDCStatePayload, _verify_state_signed
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from app.gateway.routers import auth as auth_router
from deerflow.config.auth_config import OIDCProviderConfig

_ISSUER = "https://oa.example.test/oidc"
_SHADOW_SECRET = "test-only-shadow-email-secret-value-32b"


def _fanwei_config(**overrides: object) -> OIDCProviderConfig:
    values: dict[str, object] = {
        "display_name": "Fanwei OA",
        "adapter": "fanwei_e10",
        "issuer": _ISSUER,
        "discovery_url": "https://oa.example.test/.well-known/openid-configuration",
        "client_id": "fanwei-test-client",
        "client_secret": "test-only-client-secret",
        "redirect_uri": "https://agent.example.test/api/v1/auth/callback/fanwei",
        "scopes": ["openid", "mobile", "profile"],
        "token_endpoint_auth_method": "client_secret_post",
        "userinfo_endpoint": "https://oa.example.test/profile",
        "shadow_email_secret": _SHADOW_SECRET,
        "require_verified_email": False,
        "nonce_enabled": True,
    }
    values.update(overrides)
    return OIDCProviderConfig(**values)


def _fanwei_identity(**overrides: object) -> OIDCIdentity:
    values: dict[str, object] = {
        "provider": "fanwei",
        "issuer": _ISSUER,
        "subject": "stable-oa-subject",
        "email": None,
        "email_verified": False,
        "name": "Synthetic User",
        "claims": {"iss": _ISSUER, "sub": "stable-oa-subject"},
        "mobile": "+8613800138000",
        "job_number": "E-100",
    }
    values.update(overrides)
    return OIDCIdentity(**values)


def test_standard_oidc_defaults_remain_compatible():
    config = OIDCProviderConfig(
        display_name="Existing provider",
        issuer="https://issuer.example.test",
        client_id="existing-client",
    )

    assert config.adapter == "standard"
    assert config.metadata_mode == "discovery"
    assert config.userinfo_token_transport == "bearer_header"
    assert config.require_verified_email is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_secret": None},
        {"token_endpoint_auth_method": "none"},
        {"nonce_enabled": False},
        {"shadow_email_secret": "too-short"},
        {"require_verified_email": True},
        {"allowed_email_domains": ["example.test"]},
        {"admin_emails": ["admin@example.test"]},
    ],
)
def test_fanwei_config_rejects_incompatible_security_settings(overrides: dict[str, object]):
    with pytest.raises(ValidationError):
        _fanwei_config(**overrides)


def test_static_metadata_requires_all_fanwei_endpoints():
    with pytest.raises(ValidationError):
        _fanwei_config(
            metadata_mode="static",
            authorization_endpoint="https://oa.example.test/authorize",
            token_endpoint="https://oa.example.test/token",
            jwks_uri="https://oa.example.test/jwks",
            userinfo_endpoint=None,
        )

    config = _fanwei_config(
        metadata_mode="static",
        authorization_endpoint="https://oa.example.test/authorize",
        token_endpoint="https://oa.example.test/token",
        jwks_uri="https://oa.example.test/jwks",
    )
    assert config.metadata_mode == "static"


def test_shadow_email_is_stable_private_and_valid():
    email = derive_shadow_email(_SHADOW_SECRET, _ISSUER, "stable-oa-subject")

    assert email == derive_shadow_email(_SHADOW_SECRET, _ISSUER, "stable-oa-subject")
    assert email != derive_shadow_email(_SHADOW_SECRET, _ISSUER, "other-subject")
    assert _ISSUER not in email
    assert "stable-oa-subject" not in email
    assert email.endswith("@sso.example")
    assert TypeAdapter(EmailStr).validate_python(email) == email


def test_fanwei_profile_uses_verified_subject_and_nested_attributes_only():
    supplemental = normalize_fanwei_profile(
        {
            "status": 200,
            "code": 0,
            "msg": "SUCCESS",
            "id": "oa-account-id-that-is-not-a-subject",
            "attributes": {
                "mobile": "+8613800138000",
                "username": "Synthetic User",
                "job_num": "E-100",
            },
        },
        verified_sub="stable-oa-subject",
    )

    assert supplemental.mobile == "+8613800138000"
    assert supplemental.name == "Synthetic User"
    assert supplemental.job_number == "E-100"
    assert supplemental.source_account_id == "oa-account-id-that-is-not-a-subject"


def test_fanwei_profile_rejects_an_explicit_subject_mismatch():
    with pytest.raises(FanweiProfileError, match="subject"):
        normalize_fanwei_profile(
            {
                "status": 200,
                "code": 0,
                "msg": "SUCCESS",
                "sub": "different-subject",
                "attributes": {},
            },
            verified_sub="stable-oa-subject",
        )


def test_fanwei_profile_rejects_failed_business_status_without_exposing_details():
    secret_text = "synthetic-access-token"
    with pytest.raises(FanweiProfileError) as exc_info:
        normalize_fanwei_profile(
            {"status": 403, "code": 1, "msg": secret_text, "attributes": {}},
            verified_sub="stable-oa-subject",
        )
    assert secret_text not in str(exc_info.value)


def test_validly_signed_but_malformed_state_cookie_fails_closed(monkeypatch):
    secret = "synthetic-state-secret-with-32-bytes"
    monkeypatch.setattr("app.gateway.auth.oidc_state.get_auth_config", lambda: SimpleNamespace(jwt_secret=secret))
    signed = jwt.encode({"provider": "fanwei", "state": ["wrong type"]}, secret, algorithm="HS256")
    assert _verify_state_signed(signed) is None


@pytest.mark.asyncio
async def test_callback_rejects_wrong_state_before_token_exchange_and_deletes_cookie(monkeypatch):
    provider = _fanwei_config()
    config = SimpleNamespace(auth=SimpleNamespace(oidc=SimpleNamespace(enabled=True, frontend_base_url=None, providers={"fanwei": provider})))
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: config)
    monkeypatch.setattr(auth_router, "get_state_cookie", lambda request, key: OIDCStatePayload(provider=key, state="expected-state"))
    service = AsyncMock()
    monkeypatch.setattr(auth_router, "_get_oidc_service", lambda: service)
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/auth/callback/fanwei", "headers": [], "scheme": "https"})

    response = await auth_router.oauth_callback(request, "fanwei", code="synthetic-code", state="wrong-state")

    assert response.status_code == 302
    assert "df_oidc_state_fanwei" in response.headers.get("set-cookie", "")
    assert "Max-Age=0" in response.headers.get("set-cookie", "")
    service.authenticate_callback.assert_not_called()


@pytest.mark.asyncio
async def test_fanwei_id_token_requires_kid_before_key_selection(monkeypatch):
    service = OIDCService()
    metadata = OIDCMetadata(
        issuer=_ISSUER,
        authorization_endpoint="https://oa.example.test/authorize",
        token_endpoint="https://oa.example.test/token",
        userinfo_endpoint="https://oa.example.test/profile",
        jwks_uri="https://oa.example.test/jwks",
    )
    monkeypatch.setattr(service, "_load_jwks", AsyncMock(return_value={"keys": []}))
    monkeypatch.setattr("app.gateway.auth.oidc.jwt.get_unverified_header", lambda token: {"alg": "RS256"})
    try:
        with pytest.raises(OIDCValidationError, match="signing key ID"):
            await service.validate_id_token(metadata, "client", "synthetic-id-token", require_kid=True)
    finally:
        await service.close()


@pytest.fixture(scope="module")
def rsa_signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = "synthetic-rsa-key"
    return private_key, jwk


@pytest.mark.asyncio
async def test_fanwei_accepts_valid_rs256_id_token(monkeypatch, rsa_signing_material):
    private_key, jwk = rsa_signing_material
    service = OIDCService()
    metadata = OIDCMetadata(_ISSUER, "https://oa.example.test/authorize", "https://oa.example.test/token", "https://oa.example.test/profile", "https://oa.example.test/jwks")
    claims = {"iss": _ISSUER, "sub": "stable-oa-subject", "aud": "synthetic-client", "exp": int(time.time()) + 300, "iat": int(time.time()), "nonce": "synthetic-nonce"}
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": jwk["kid"]})
    monkeypatch.setattr(service, "_load_jwks", AsyncMock(return_value={"keys": [jwk]}))
    try:
        verified = await service.validate_id_token(metadata, "synthetic-client", token, nonce="synthetic-nonce", require_kid=True)
    finally:
        await service.close()
    assert verified["sub"] == "stable-oa-subject"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_field", ["issuer", "audience", "nonce", "expired", "future_iat", "missing_iat", "wrong_signature", "unknown_kid"])
async def test_fanwei_rejects_invalid_rs256_id_token(monkeypatch, rsa_signing_material, invalid_field):
    private_key, jwk = rsa_signing_material
    service = OIDCService()
    metadata = OIDCMetadata(_ISSUER, "https://oa.example.test/authorize", "https://oa.example.test/token", "https://oa.example.test/profile", "https://oa.example.test/jwks")
    now = int(time.time())
    claims = {"iss": _ISSUER, "sub": "stable-oa-subject", "aud": "synthetic-client", "exp": now + 300, "iat": now, "nonce": "synthetic-nonce"}
    if invalid_field == "issuer":
        claims["iss"] = "https://other.example.test"
    elif invalid_field == "audience":
        claims["aud"] = "other-client"
    elif invalid_field == "nonce":
        claims["nonce"] = "other-nonce"
    elif invalid_field == "expired":
        claims["exp"] = now - 1
    elif invalid_field == "future_iat":
        claims["iat"] = now + 3600
    elif invalid_field == "missing_iat":
        del claims["iat"]
    header_kid = "unknown-kid" if invalid_field == "unknown_kid" else jwk["kid"]
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048) if invalid_field == "wrong_signature" else private_key
    token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": header_kid})
    monkeypatch.setattr(service, "_load_jwks", AsyncMock(return_value={"keys": [jwk]}))
    try:
        with pytest.raises(OIDCValidationError):
            await service.validate_id_token(metadata, "synthetic-client", token, nonce="synthetic-nonce", require_kid=True)
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", ["none", "HS256"])
async def test_fanwei_rejects_none_and_hmac_id_tokens(monkeypatch, algorithm):
    service = OIDCService()
    metadata = OIDCMetadata(_ISSUER, "https://oa.example.test/authorize", "https://oa.example.test/token", "https://oa.example.test/profile", "https://oa.example.test/jwks")
    claims = {"iss": _ISSUER, "sub": "stable-oa-subject", "aud": "synthetic-client", "exp": int(time.time()) + 300, "iat": int(time.time()), "nonce": "synthetic-nonce"}
    token = jwt.encode(claims, "" if algorithm == "none" else "synthetic-hmac-secret-with-32-bytes", algorithm=algorithm, headers={"kid": "synthetic-key"})
    monkeypatch.setattr(service, "_load_jwks", AsyncMock(return_value={"keys": []}))
    try:
        with pytest.raises(OIDCValidationError, match="unsupported algorithm"):
            await service.validate_id_token(metadata, "synthetic-client", token, nonce="synthetic-nonce", require_kid=True)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_fanwei_token_business_envelope_and_nested_profile_are_normalized(monkeypatch):
    service = OIDCService()
    metadata = OIDCMetadata(_ISSUER, "https://oa.example.test/authorize", "https://oa.example.test/token", "https://oa.example.test/profile", "https://oa.example.test/jwks")
    monkeypatch.setattr(service, "exchange_code", AsyncMock(return_value={"status": 200, "code": 0, "msg": "SUCCESS", "id_token": "synthetic-id-token", "access_token": "synthetic-access-token", "expire": 300}))
    monkeypatch.setattr(service, "validate_id_token", AsyncMock(return_value={"iss": _ISSUER, "sub": "stable-oa-subject"}))
    monkeypatch.setattr(service, "fetch_userinfo", AsyncMock(return_value={"status": 200, "code": 0, "msg": "SUCCESS", "id": "other-profile-id", "attributes": {"mobile": "+8613800138000", "username": "Synthetic User", "job_num": "E-100"}}))
    try:
        identity = await service.authenticate_callback(
            provider_id="fanwei",
            metadata=metadata,
            client_id="synthetic-client",
            client_secret="synthetic-client-secret",
            code="synthetic-code",
            redirect_uri="https://agent.example.test/callback",
            nonce="synthetic-nonce",
            adapter="fanwei_e10",
        )
    finally:
        await service.close()
    assert identity.issuer == _ISSUER
    assert identity.subject == "stable-oa-subject"
    assert identity.email is None
    assert identity.mobile == "+8613800138000"
    assert identity.job_number == "E-100"


@pytest.mark.asyncio
async def test_fanwei_failed_token_business_envelope_stops_before_id_token_validation(monkeypatch):
    service = OIDCService()
    metadata = OIDCMetadata(_ISSUER, "https://oa.example.test/authorize", "https://oa.example.test/token", "https://oa.example.test/profile", "https://oa.example.test/jwks")
    monkeypatch.setattr(service, "exchange_code", AsyncMock(return_value={"status": 403, "code": 1, "msg": "synthetic-private-provider-body", "id_token": "synthetic-id-token"}))
    validate = AsyncMock()
    monkeypatch.setattr(service, "validate_id_token", validate)
    try:
        with pytest.raises(OIDCError) as exc_info:
            await service.authenticate_callback(
                provider_id="fanwei",
                metadata=metadata,
                client_id="synthetic-client",
                client_secret="synthetic-client-secret",
                code="synthetic-code",
                redirect_uri="https://agent.example.test/callback",
                nonce="synthetic-nonce",
                adapter="fanwei_e10",
            )
    finally:
        await service.close()
    assert "synthetic-private-provider-body" not in str(exc_info.value)
    validate.assert_not_called()


@pytest.mark.asyncio
async def test_discovery_url_is_independent_but_expected_issuer_stays_strict(monkeypatch):
    service = OIDCService()
    requested_urls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {
                "issuer": _ISSUER,
                "authorization_endpoint": "https://oa.example.test/authorize",
                "token_endpoint": "https://oa.example.test/token",
                "userinfo_endpoint": "https://oa.example.test/profile",
                "jwks_uri": "https://oa.example.test/jwks",
            }

    async def fake_get(url: str, **kwargs: object) -> Response:
        requested_urls.append(url)
        return Response()

    monkeypatch.setattr(service._http, "get", fake_get)
    try:
        metadata = await service.discover(
            _ISSUER,
            discovery_url="https://metadata.example.test/oa-discovery",
            strict_issuer=True,
        )
    finally:
        await service.close()

    assert requested_urls == ["https://metadata.example.test/oa-discovery"]
    assert metadata.issuer == _ISSUER


@pytest.mark.asyncio
async def test_static_metadata_never_issues_a_discovery_request(monkeypatch):
    service = OIDCService()

    async def unexpected_get(*args: object, **kwargs: object) -> None:
        raise AssertionError("static metadata must not fetch discovery")

    monkeypatch.setattr(service._http, "get", unexpected_get)
    try:
        metadata = await service.discover(
            _ISSUER,
            metadata_mode="static",
            overrides={
                "authorization_endpoint": "https://oa.example.test/authorize",
                "token_endpoint": "https://oa.example.test/token",
                "userinfo_endpoint": "https://oa.example.test/profile",
                "jwks_uri": "https://oa.example.test/jwks",
            },
        )
    finally:
        await service.close()

    assert metadata.issuer == _ISSUER
    assert metadata.authorization_endpoint == "https://oa.example.test/authorize"


@pytest.mark.asyncio
async def test_query_profile_transport_never_logs_the_access_token(monkeypatch, caplog):
    service = OIDCService()
    access_token = "synthetic-access-token-that-must-not-be-logged"
    seen_params: dict[str, str] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"status": 200, "code": 0, "msg": "SUCCESS", "attributes": {}}

    async def fake_get(url: str, **kwargs: object) -> Response:
        assert url == "https://oa.example.test/profile"
        seen_params.update(kwargs["params"])
        return Response()

    monkeypatch.setattr(service._http, "get", fake_get)
    metadata = await service.discover(
        _ISSUER,
        metadata_mode="static",
        overrides={
            "authorization_endpoint": "https://oa.example.test/authorize",
            "token_endpoint": "https://oa.example.test/token",
            "userinfo_endpoint": "https://oa.example.test/profile",
            "jwks_uri": "https://oa.example.test/jwks",
        },
    )
    try:
        with caplog.at_level(logging.WARNING):
            profile = await service.fetch_userinfo(
                metadata,
                access_token,
                "stable-oa-subject",
                provider_id="fanwei",
                adapter="fanwei_e10",
                transport="query",
            )
    finally:
        await service.close()

    assert profile["status"] == 200
    assert seen_params == {"access_token": access_token}
    assert access_token not in caplog.text


@pytest.mark.asyncio
async def test_httpx_access_log_redacts_query_profile_token(caplog):
    service = OIDCService()
    token = "synthetic-query-token-keep-private"
    metadata = OIDCMetadata(
        issuer=_ISSUER,
        authorization_endpoint="https://oa.example.test/authorize",
        token_endpoint="https://oa.example.test/token",
        userinfo_endpoint="https://oa.example.test/profile",
        jwks_uri="https://oa.example.test/jwks",
    )

    async def reply(request: httpx.Request) -> httpx.Response:
        assert request.url.params["access_token"] == token
        return httpx.Response(200, json={"status": 200, "code": 0, "msg": "SUCCESS", "attributes": {}})

    await service.close()
    service._http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    try:
        with caplog.at_level(logging.INFO, logger="httpx"):
            await service.fetch_userinfo(metadata, token, "stable-oa-subject", provider_id="fanwei", adapter="fanwei_e10", transport="query")
    finally:
        await service.close()
    assert token not in caplog.text
    assert "[REDACTED]" in caplog.text


@pytest.mark.asyncio
async def test_token_exchange_error_never_echoes_provider_response_body(monkeypatch):
    service = OIDCService()
    response_body = "access_token=synthetic-token&client_secret=synthetic-secret"
    response = httpx.Response(400, content=response_body, request=httpx.Request("POST", "https://oa.example.test/token"))

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return response

    monkeypatch.setattr(service._http, "post", fake_post)
    try:
        with pytest.raises(OIDCError) as exc_info:
            await service.exchange_code(
                metadata=await service.discover(
                    _ISSUER,
                    metadata_mode="static",
                    overrides={
                        "authorization_endpoint": "https://oa.example.test/authorize",
                        "token_endpoint": "https://oa.example.test/token",
                        "userinfo_endpoint": "https://oa.example.test/profile",
                        "jwks_uri": "https://oa.example.test/jwks",
                    },
                ),
                client_id="fanwei-test-client",
                client_secret="synthetic-secret",
                code="synthetic-code",
                redirect_uri="https://agent.example.test/api/v1/auth/callback/fanwei",
            )
    finally:
        await service.close()

    assert response_body not in str(exc_info.value)
    assert "synthetic-token" not in str(exc_info.value)
    assert "synthetic-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_fanwei_jit_uses_issuer_subject_and_never_mobile_or_email_linking():
    config = _fanwei_config()
    identity = _fanwei_identity()
    local_provider = AsyncMock()
    local_provider.get_user_by_oidc.return_value = None
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    created_user = User(email=derive_shadow_email(_SHADOW_SECRET, _ISSUER, identity.subject), password_hash=None, oauth_provider="fanwei", oauth_issuer=_ISSUER, oauth_id=identity.subject)
    local_provider.create_oauth_user.return_value = created_user

    result = await get_or_provision_oidc_user("fanwei", config, identity, local_provider)

    assert result == {"user": created_user, "created": True}
    local_provider.create_oauth_user.assert_awaited_once_with(
        email=derive_shadow_email(_SHADOW_SECRET, _ISSUER, identity.subject),
        oauth_provider="fanwei",
        oauth_issuer=_ISSUER,
        oauth_id=identity.subject,
        system_role="user",
    )


@pytest.mark.asyncio
async def test_fanwei_reuses_same_issuer_subject_after_mobile_changes():
    existing = User(email="oidc-v1-existing@sso.example", password_hash=None, oauth_provider="fanwei", oauth_issuer=_ISSUER, oauth_id="stable-oa-subject")
    local_provider = AsyncMock()
    local_provider.get_user_by_oidc.return_value = existing

    result = await get_or_provision_oidc_user(
        "fanwei",
        _fanwei_config(),
        _fanwei_identity(mobile="+8613900138000"),
        local_provider,
    )

    assert result == {"user": existing, "created": False}
    local_provider.get_user_by_oauth.assert_not_called()
    local_provider.get_user_by_email.assert_not_called()


@pytest.mark.asyncio
async def test_fanwei_retargeted_provider_key_with_different_issuer_is_a_conflict():
    existing = User(email="legacy@sso.example", password_hash=None, oauth_provider="fanwei", oauth_issuer="https://old-oa.example.test/oidc", oauth_id="stable-oa-subject")
    local_provider = AsyncMock()
    local_provider.get_user_by_oidc.return_value = None
    local_provider.get_user_by_oauth.return_value = existing

    with pytest.raises(HTTPException) as exc_info:
        await get_or_provision_oidc_user("fanwei", _fanwei_config(), _fanwei_identity(), local_provider)

    assert exc_info.value.status_code == 409
    local_provider.create_oauth_user.assert_not_called()


@pytest.mark.asyncio
async def test_fanwei_concurrent_first_login_only_reuses_the_same_verified_identity():
    identity = _fanwei_identity()
    winner = User(email=derive_shadow_email(_SHADOW_SECRET, _ISSUER, identity.subject), password_hash=None, oauth_provider="fanwei", oauth_issuer=_ISSUER, oauth_id=identity.subject)
    local_provider = AsyncMock()
    local_provider.get_user_by_oidc.side_effect = [None, winner]
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = None
    local_provider.create_oauth_user.side_effect = ValueError("OAuth identity already exists")

    result = await get_or_provision_oidc_user("fanwei", _fanwei_config(), identity, local_provider)

    assert result == {"user": winner, "created": False}
    assert local_provider.get_user_by_oidc.await_count == 2


@pytest.mark.asyncio
async def test_fanwei_concurrent_create_seen_at_shadow_email_precheck_reuses_winner():
    identity = _fanwei_identity()
    winner = User(email=derive_shadow_email(_SHADOW_SECRET, _ISSUER, identity.subject), oauth_provider="fanwei", oauth_issuer=_ISSUER, oauth_id=identity.subject)
    local_provider = AsyncMock()
    local_provider.get_user_by_oidc.side_effect = [None, winner]
    local_provider.get_user_by_oauth.return_value = None
    local_provider.get_user_by_email.return_value = winner

    result = await get_or_provision_oidc_user("fanwei", _fanwei_config(), identity, local_provider)

    assert result == {"user": winner, "created": False}
    local_provider.create_oauth_user.assert_not_called()
