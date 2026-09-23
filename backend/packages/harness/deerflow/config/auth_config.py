"""OIDC / SSO authentication configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OIDCProviderConfig(BaseModel):
    """Configuration for a single OIDC identity provider (Keycloak, Google, Azure AD, etc.)."""

    model_config = ConfigDict(hide_input_in_errors=True)

    display_name: str = Field(description="Human-readable name shown on the login button")
    issuer: str = Field(description="OIDC issuer URL (e.g. https://keycloak.example.com/realms/deerflow)")
    client_id: str = Field(description="OAuth2 client ID assigned by the provider")
    client_secret: str | None = Field(default=None, repr=False, description="OAuth2 client secret ($ENV_VAR references supported)")
    redirect_uri: str | None = Field(default=None, description="Callback URL the provider will redirect to after auth")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="OIDC scopes to request (must include openid)",
    )
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] = Field(
        default="client_secret_post",
        description="How the client authenticates at the token endpoint",
    )

    # ── Provider compatibility ───────────────────────────────────────
    adapter: Literal["standard", "fanwei_e10"] = Field(
        default="standard",
        description="Provider protocol adapter; standard preserves normal OIDC claim semantics",
    )
    metadata_mode: Literal["discovery", "static"] = Field(
        default="discovery",
        description="Resolve endpoint metadata from discovery or from explicit static endpoint values",
    )
    discovery_url: str | None = Field(
        default=None,
        description="Explicit discovery document URL; defaults to issuer + /.well-known/openid-configuration",
    )
    userinfo_token_transport: Literal["bearer_header", "post_form", "query"] = Field(
        default="bearer_header",
        description="How the access token is sent to a provider's profile endpoint",
    )
    end_session_endpoint: str | None = Field(
        default=None,
        description="Optional provider logout endpoint; DeerFlow only clears its own session by default",
    )
    shadow_email_secret: str | None = Field(
        default=None,
        repr=False,
        description="Dedicated stable HMAC secret for non-email SSO users; supports $ENV_VAR references",
    )

    # ── User provisioning ─────────────────────────────────────────────
    auto_create_users: bool = Field(
        default=True,
        description="Automatically create a DeerFlow user on first SSO login",
    )
    require_verified_email: bool = Field(
        default=True,
        description="Reject authentication if the provider does not report the email as verified",
    )
    allowed_email_domains: list[str] = Field(
        default_factory=list,
        description="If non-empty, only allow users whose email domain is in this list (e.g. ['example.com'])",
    )
    admin_emails: list[str] = Field(
        default_factory=list,
        description="Users with these email addresses are automatically granted the admin role on first login",
    )

    # ── PKCE / nonce ──────────────────────────────────────────────────
    pkce_enabled: bool = Field(default=True, description="Enable PKCE (S256) for the authorization code flow")
    nonce_enabled: bool = Field(default=True, description="Include and validate the nonce claim in ID tokens")

    # ── Endpoint overrides (for providers with non-standard discovery) ─
    authorization_endpoint: str | None = Field(default=None)
    token_endpoint: str | None = Field(default=None)
    userinfo_endpoint: str | None = Field(default=None)
    jwks_uri: str | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_security_invariants(self) -> OIDCProviderConfig:
        if "openid" not in self.scopes:
            raise ValueError("OIDC scopes must include 'openid'")

        if self.metadata_mode == "static":
            required_endpoints = {
                "authorization_endpoint": self.authorization_endpoint,
                "token_endpoint": self.token_endpoint,
                "userinfo_endpoint": self.userinfo_endpoint,
                "jwks_uri": self.jwks_uri,
            }
            missing = [name for name, value in required_endpoints.items() if not value]
            if missing:
                raise ValueError(f"static OIDC metadata requires: {', '.join(missing)}")

        if self.adapter != "fanwei_e10":
            return self

        if not self.client_secret:
            raise ValueError("fanwei_e10 requires a confidential client_secret")
        if self.token_endpoint_auth_method != "client_secret_post":
            raise ValueError("fanwei_e10 requires token_endpoint_auth_method=client_secret_post")
        if not self.nonce_enabled:
            raise ValueError("fanwei_e10 requires nonce_enabled=true")
        if not self.shadow_email_secret or len(self.shadow_email_secret.encode("utf-8")) < 32:
            raise ValueError("fanwei_e10 requires a dedicated shadow_email_secret of at least 32 bytes")
        if self.require_verified_email:
            raise ValueError("fanwei_e10 requires require_verified_email=false")
        if self.allowed_email_domains:
            raise ValueError("fanwei_e10 does not support allowed_email_domains")
        if self.admin_emails:
            raise ValueError("fanwei_e10 does not support admin_emails")
        return self


class OIDCAuthConfig(BaseModel):
    """Top-level OIDC authentication configuration."""

    enabled: bool = Field(default=False, description="Enable OIDC SSO authentication")
    frontend_base_url: str | None = Field(
        default=None,
        description="Base URL of the frontend (used for callback redirects when behind a reverse proxy)",
    )
    providers: dict[str, OIDCProviderConfig] = Field(
        default_factory=dict,
        description="Map of provider IDs to their configuration (e.g. keycloak, google, azure)",
    )


class LocalAuthConfig(BaseModel):
    """Configuration for the built-in email/password authentication provider."""

    allow_registration: bool = Field(
        default=True,
        description=(
            "Allow visitors to self-register a local account via POST /api/v1/auth/register. "
            "Set to false when accounts are provisioned exclusively through SSO — the OIDC "
            "provisioning policy (allowed_email_domains, require_verified_email, auto_create_users) "
            "does not apply to local registration."
        ),
    )
    max_login_attempts: int = Field(
        default=5,
        ge=2,
        description=(
            "Failed login attempts allowed from one client IP before it is locked out of "
            "POST /api/v1/auth/login/local. Defaults preserve the historical hardcoded policy. "
            "Raise it when many users share an egress IP (corporate proxy / NAT); lower it for "
            "a stricter posture. Minimum 2: one failed attempt must never lock an IP, or a "
            "single typo would block everyone behind a shared egress — the strictest legal "
            "value locks after the second failure. The counter is per-Gateway-worker "
            "(in-process), so effective attempts in multi-worker deployments scale with "
            "worker count."
        ),
    )
    lockout_seconds: float = Field(
        default=300.0,
        gt=0,
        allow_inf_nan=False,
        description=("Seconds an IP stays locked out after reaching auth.local.max_login_attempts. Defaults preserve the historical hardcoded policy (5 minutes)."),
    )


class AuthAppConfig(BaseModel):
    """Authentication configuration section for the DeerFlow app config."""

    oidc: OIDCAuthConfig = Field(default_factory=OIDCAuthConfig, description="OIDC SSO authentication settings")
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig, description="Built-in email/password authentication settings")
