"""OIDC (OpenID Connect) authentication service.

Provides provider-agnostic OIDC operations: discovery, authorization URL
generation, token exchange, ID token validation, and userinfo retrieval.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWK

from app.gateway.auth.oidc_adapters import FanweiProfileError, normalize_fanwei_profile

logger = logging.getLogger(__name__)


class _OIDCTokenQueryLogFilter(logging.Filter):
    """Redact the opt-in query transport token from HTTP client access logs."""

    _token_parameter = re.compile(r"([?&]access_token=)[^&\s\"']+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        redacted = self._token_parameter.sub(r"\1[REDACTED]", rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True


_token_query_log_filter = _OIDCTokenQueryLogFilter()
for _http_logger_name in ("httpx", "httpcore.proxy", "httpcore.socks", "httpcore.http11", "httpcore.connection", "httpcore.http2"):
    logging.getLogger(_http_logger_name).addFilter(_token_query_log_filter)

# ── Data types ────────────────────────────────────────────────────────────

OIDC_DISCOVERY_PATH = "/.well-known/openid-configuration"
METADATA_CACHE_TTL = 300  # 5 minutes
JWKS_CACHE_TTL = 300


@dataclass(frozen=True)
class OIDCMetadata:
    """Resolved OIDC provider metadata after discovery."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None
    jwks_uri: str


@dataclass(frozen=True)
class OIDCIdentity:
    """Normalized identity extracted from an OIDC provider response."""

    provider: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    claims: dict[str, Any]
    issuer: str = ""
    mobile: str | None = None
    job_number: str | None = None


class OIDCError(Exception):
    """Base error for OIDC operations. Message is safe for API responses."""


class OIDCProviderError(OIDCError):
    """The OIDC provider returned an error (e.g. access_denied)."""


class OIDCValidationError(OIDCError):
    """ID token validation failed."""


class OIDCUserInfoMismatch(OIDCError):
    """UserInfo sub does not match ID token sub."""


# ── Service ────────────────────────────────────────────────────────────────


class OIDCService:
    """OIDC authentication service.

    Uses in-process caching for provider metadata and JWKS. The cache is
    keyed by the provider's ``issuer`` — different providers get separate
    entries. TTLs are configurable via constructor arguments.
    """

    def __init__(
        self,
        metadata_cache_ttl: float = METADATA_CACHE_TTL,
        jwks_cache_ttl: float = JWKS_CACHE_TTL,
    ) -> None:
        self._metadata_cache: dict[tuple[str, str, bool], tuple[float, dict[str, Any]]] = {}
        self._jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._metadata_ttl = metadata_cache_ttl
        self._jwks_ttl = jwks_cache_ttl
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ── Discovery ──────────────────────────────────────────────────────────

    async def discover(
        self,
        issuer: str,
        overrides: dict[str, str | None] | None = None,
        *,
        discovery_url: str | None = None,
        metadata_mode: str = "discovery",
        strict_issuer: bool = False,
    ) -> OIDCMetadata:
        """Fetch and cache OIDC discovery metadata from the issuer.

        ``overrides`` may contain endpoint URIs to override discovery values
        (e.g. for providers with non-standard endpoints).
        """
        if metadata_mode == "static":
            if not overrides or any(not overrides.get(key) for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint", "jwks_uri")):
                raise OIDCError("Static OIDC metadata is incomplete")
            return self._metadata_from_dict({"issuer": issuer, **overrides}, None)
        if metadata_mode != "discovery":
            raise OIDCError("Unsupported OIDC metadata mode")
        now = time.time()
        discovery_url = discovery_url or issuer.rstrip("/") + OIDC_DISCOVERY_PATH
        cache_key = (issuer, discovery_url, strict_issuer)
        cached = self._metadata_cache.get(cache_key)
        if cached and now - cached[0] < self._metadata_ttl:
            return self._metadata_from_dict(cached[1], overrides)

        try:
            resp = await self._http.get(discovery_url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"OIDC discovery failed: HTTP {exc.response.status_code}") from None
        except httpx.RequestError:
            raise OIDCError("OIDC discovery request failed") from None
        except (ValueError, TypeError):
            raise OIDCError("OIDC discovery response is not valid JSON") from None

        if not isinstance(data, dict):
            raise OIDCError("OIDC discovery response must be an object")

        discovered_issuer = data.get("issuer")
        if not discovered_issuer:
            raise OIDCError(f"OIDC discovery response from {issuer} is missing the issuer field")

        # RFC 8414 §4: the metadata issuer must equal the configured issuer.
        # Pinning it prevents a tampered/rogue discovery document from steering
        # the accepted `iss` (and thus the ID-token forgery surface) to an
        # attacker-chosen value.
        if discovered_issuer != issuer if strict_issuer else discovered_issuer.rstrip("/") != issuer.rstrip("/"):
            raise OIDCError(f"OIDC discovered issuer '{discovered_issuer}' does not match configured issuer '{issuer}'")

        self._metadata_cache[cache_key] = (now, data)
        return self._metadata_from_dict(data, overrides)

    def _metadata_from_dict(self, data: dict[str, Any], overrides: dict[str, str | None] | None) -> OIDCMetadata:
        """Build OIDCMetadata from a discovery dict, applying endpoint overrides."""
        overrides = overrides or {}
        for field in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not (overrides.get(field) or data.get(field)):
                raise OIDCError(f"OIDC metadata is missing {field}")
        return OIDCMetadata(
            issuer=data["issuer"],
            authorization_endpoint=overrides.get("authorization_endpoint") or data["authorization_endpoint"],
            token_endpoint=overrides.get("token_endpoint") or data["token_endpoint"],
            userinfo_endpoint=overrides.get("userinfo_endpoint") or data.get("userinfo_endpoint"),
            jwks_uri=overrides.get("jwks_uri") or data["jwks_uri"],
        )

    # ── Authorization URL ──────────────────────────────────────────────────

    def build_authorization_url(
        self,
        metadata: OIDCMetadata,
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        state: str,
        nonce: str | None = None,
        code_challenge: str | None = None,
    ) -> str:
        """Build the OIDC authorization URL for the provider.

        Returns a URL the browser should be redirected to.
        """
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        if nonce:
            params["nonce"] = nonce
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        return f"{metadata.authorization_endpoint}?{urlencode(params)}"

    # ── Token exchange ─────────────────────────────────────────────────────

    async def exchange_code(
        self,
        metadata: OIDCMetadata,
        client_id: str,
        client_secret: str | None,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        auth_method: str = "client_secret_post",
    ) -> dict[str, Any]:
        """Exchange the authorization code for tokens at the token endpoint."""
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        headers: dict[str, str] = {"Accept": "application/json"}

        if auth_method == "client_secret_basic" and client_secret:
            import base64

            creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {creds}"
        elif auth_method == "client_secret_post" and client_secret:
            data["client_secret"] = client_secret

        try:
            resp = await self._http.post(metadata.token_endpoint, data=data, headers=headers)
            resp.raise_for_status()
            tokens = resp.json()
            if not isinstance(tokens, dict):
                raise OIDCError("Token response must be an object")
            return tokens
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"Token exchange failed: HTTP {exc.response.status_code}") from None
        except httpx.RequestError:
            raise OIDCError("Token exchange request failed") from None
        except (ValueError, TypeError):
            raise OIDCError("Token response is not valid JSON") from None

    # ── JWKS loading ───────────────────────────────────────────────────────

    async def _load_jwks(self, jwks_uri: str, force_refresh: bool = False) -> dict[str, Any]:
        """Load (and cache) JWKS from the provider.

        Set ``force_refresh=True`` to bypass the cache (e.g. on a kid miss).
        """
        now = time.time()
        cached = self._jwks_cache.get(jwks_uri)
        if not force_refresh and cached and now - cached[0] < self._jwks_ttl:
            return cached[1]

        try:
            resp = await self._http.get(jwks_uri)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"JWKS fetch failed: HTTP {exc.response.status_code}") from None
        except httpx.RequestError:
            raise OIDCError("JWKS fetch request failed") from None
        except (ValueError, TypeError):
            raise OIDCError("JWKS response is not valid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
            raise OIDCError("JWKS response is invalid")

        self._jwks_cache[jwks_uri] = (now, data)
        return data

    async def _resolve_signing_key(
        self,
        jwks_data: dict[str, Any],
        kid: str | None,
        algorithm: str,
        jwks_uri: str,
    ) -> Any | None:
        """Find the signing key matching ``kid`` in the JWKS.

        Returns the key object or ``None`` if no match is found. Catches
        invalid JWK entries (e.g. wrong key type for the algorithm) and
        logs a warning so a single bad entry does not crash validation.
        """
        for jwk_dict in jwks_data.get("keys", []):
            if kid and jwk_dict.get("kid") != kid:
                continue
            try:
                jwk = PyJWK(jwk_dict, algorithm=algorithm)
                return jwk.key
            except jwt.PyJWTError:
                logger.warning("Skipping invalid JWK")
                if not kid:
                    # No kid in token — try next key
                    continue
                # kid was specified and this key is the one — fail fast
                raise OIDCValidationError("JWK for ID token signing key is invalid") from None
        return None

    # ── ID token validation ────────────────────────────────────────────────

    async def validate_id_token(
        self,
        metadata: OIDCMetadata,
        client_id: str,
        id_token: str,
        nonce: str | None = None,
        require_kid: bool = False,
    ) -> dict[str, Any]:
        """Validate the ID token and return its claims.

        Validates: signature (via JWKS), issuer, audience, expiration,
        issued-at, and nonce (if provided).
        """
        jwks_data = await self._load_jwks(metadata.jwks_uri)

        # Resolve the signing key from the JWKS using the token's kid header
        try:
            jwt_header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise OIDCValidationError("ID token header is invalid") from None
        kid = jwt_header.get("kid")
        alg = jwt_header.get("alg", "RS256")
        if require_kid and (not isinstance(kid, str) or not kid):
            raise OIDCValidationError("ID token is missing a signing key ID")

        allowed_algorithms = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
        if alg not in allowed_algorithms:
            raise OIDCValidationError(f"ID token uses unsupported algorithm '{alg}'")

        # Resolve signing key, refetching JWKS once on kid miss for key rotation
        signing_key = await self._resolve_signing_key(jwks_data, kid, alg, metadata.jwks_uri)
        if signing_key is None:
            jwks_data = await self._load_jwks(metadata.jwks_uri, force_refresh=True)
            signing_key = await self._resolve_signing_key(jwks_data, kid, alg, metadata.jwks_uri)
            if signing_key is None:
                raise OIDCValidationError(f"No matching JWK found for kid={kid} after JWKS refresh")

        try:
            claims = jwt.decode(
                id_token,
                key=signing_key,
                algorithms=allowed_algorithms,
                audience=client_id,
                issuer=metadata.issuer,
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                },
            )
        except jwt.ExpiredSignatureError:
            raise OIDCValidationError("ID token has expired")
        except jwt.InvalidIssuerError:
            raise OIDCValidationError("ID token has an invalid issuer")
        except jwt.InvalidAudienceError:
            raise OIDCValidationError("ID token has an invalid audience")
        except jwt.PyJWTError:
            raise OIDCValidationError("ID token validation failed") from None

        # Validate nonce if expected
        if nonce is not None:
            token_nonce = claims.get("nonce")
            if not token_nonce:
                raise OIDCValidationError("ID token is missing the nonce claim")
            if not _constant_time_compare(nonce, token_nonce):
                raise OIDCValidationError("ID token nonce does not match")

        return claims

    # ── UserInfo ────────────────────────────────────────────────────────────

    async def fetch_userinfo(
        self,
        metadata: OIDCMetadata,
        access_token: str,
        expected_sub: str,
        *,
        provider_id: str = "",
        adapter: str = "standard",
        transport: str = "bearer_header",
    ) -> dict[str, Any]:
        """Fetch userinfo from the UserInfo endpoint.

        Validates that the ``sub`` claim matches ``expected_sub``
        (from the ID token) to prevent userinfo injection.
        """
        if not metadata.userinfo_endpoint:
            return {}

        try:
            if transport == "bearer_header":
                resp = await self._http.get(metadata.userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"})
            elif transport == "post_form":
                resp = await self._http.post(metadata.userinfo_endpoint, data={"access_token": access_token})
            elif transport == "query":
                logger.warning("OIDC profile uses query token transport for provider %s; redact query strings in access logs", provider_id)
                resp = await self._http.get(metadata.userinfo_endpoint, params={"access_token": access_token})
            else:
                raise OIDCError("Unsupported UserInfo token transport")
            resp.raise_for_status()
            userinfo: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise OIDCError(f"UserInfo fetch failed: HTTP {exc.response.status_code}") from None
        except httpx.RequestError:
            raise OIDCError("UserInfo fetch request failed") from None
        except (ValueError, TypeError):
            raise OIDCError("UserInfo response is not valid JSON") from None
        if not isinstance(userinfo, dict):
            raise OIDCError("UserInfo response must be an object")

        if userinfo.get("sub") and userinfo["sub"] != expected_sub:
            raise OIDCUserInfoMismatch("UserInfo sub does not match ID token sub")

        return userinfo

    # ── Orchestrated callback ──────────────────────────────────────────────

    async def authenticate_callback(
        self,
        provider_id: str,
        metadata: OIDCMetadata,
        client_id: str,
        client_secret: str | None,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        nonce: str | None = None,
        auth_method: str = "client_secret_post",
        adapter: str = "standard",
        userinfo_token_transport: str = "bearer_header",
    ) -> OIDCIdentity:
        """Orchestrate the full OIDC callback: token exchange, ID token validation, userinfo.

        Returns a normalized ``OIDCIdentity``.
        """
        token_response = await self.exchange_code(
            metadata=metadata,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            auth_method=auth_method,
        )

        if adapter == "fanwei_e10" and any(key in token_response for key in ("status", "code", "msg")):
            if token_response.get("status") != 200 or str(token_response.get("code")) != "0" or token_response.get("msg") != "SUCCESS":
                raise OIDCError("Fanwei token response returned an unsuccessful business status")
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OIDCError("Token response is missing id_token")

        access_token = token_response.get("access_token", "")
        if access_token is not None and not isinstance(access_token, str):
            raise OIDCError("Token response has an invalid access_token")

        claims = await self.validate_id_token(
            metadata=metadata,
            client_id=client_id,
            id_token=id_token,
            nonce=nonce,
            require_kid=adapter == "fanwei_e10",
        )

        # Fetch userinfo for email/name if not present in ID token
        userinfo: dict[str, Any] = {}
        if adapter == "fanwei_e10" and (not metadata.userinfo_endpoint or not access_token):
            raise OIDCError("Fanwei profile endpoint and access token are required")
        if metadata.userinfo_endpoint and access_token:
            try:
                userinfo = await self.fetch_userinfo(
                    metadata=metadata,
                    access_token=access_token,
                    expected_sub=claims["sub"],
                    provider_id=provider_id,
                    adapter=adapter,
                    transport=userinfo_token_transport,
                )
            except OIDCError:
                if adapter == "fanwei_e10":
                    raise
                logger.warning("OIDC userinfo fetch failed; continuing with ID token")

        if adapter == "fanwei_e10":
            try:
                supplemental = normalize_fanwei_profile(userinfo, claims["sub"])
            except FanweiProfileError as exc:
                raise OIDCError(str(exc)) from None
            return OIDCIdentity(
                provider=provider_id,
                issuer=metadata.issuer,
                subject=claims["sub"],
                email=None,
                email_verified=False,
                name=supplemental.name,
                claims=claims,
                mobile=supplemental.mobile,
                job_number=supplemental.job_number,
            )

        # Merge userinfo into claims (userinfo takes precedence for email)
        merged = {**claims, **userinfo}

        email = merged.get("email") or ""
        email_verified = merged.get("email_verified") is True

        return OIDCIdentity(
            provider=provider_id,
            subject=claims["sub"],
            email=email,
            email_verified=email_verified,
            name=merged.get("name"),
            claims=merged,
            issuer=metadata.issuer,
        )


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return secrets.compare_digest(a, b)
