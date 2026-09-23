# SSO / OIDC Authentication

## Fanwei E10 OA integration

Fanwei OA is an OIDC OpenID Provider; the Agent Gateway is the relying party.
The OA menu opens `GET /api/v1/auth/oauth/fanwei?next=/workspace` by **top-level
navigation or a new tab**. The Gateway starts Authorization Code Flow and,
after verifying the ID token, issues its own HttpOnly session cookie. The
browser never receives an OA access, refresh, or ID token. Cross-site iframe
embedding is outside this integration's scope.

```mermaid
sequenceDiagram
  participant Browser
  participant Gateway
  participant OA
  participant DB
  Browser->>Gateway: GET /api/v1/auth/oauth/fanwei
  Gateway-->>Browser: state/nonce/PKCE cookie; redirect to OA
  Browser->>OA: authorization code request
  OA-->>Browser: redirect to fixed callback with code and state
  Browser->>Gateway: GET /api/v1/auth/callback/fanwei
  Gateway->>OA: POST token; fetch JWKS and profile
  Gateway->>Gateway: verify signature, issuer, audience, expiry, iat, nonce
  Gateway->>DB: find or create user by (oauth_issuer, oauth_id)
  Gateway-->>Browser: Agent session cookie; redirect to /auth/callback
```

### OA administration and Agent configuration

| OA field | Value to register |
| --- | --- |
| Application type | Confidential OIDC client; `client_secret_post` |
| Redirect URI | Exact public HTTPS `https://<agent-host>/api/v1/auth/callback/fanwei` |
| Scopes | `openid mobile profile` (plus `job_num` only if enabled by OA) |
| Signing | RS256; JWKS must publish a matching `kid` |
| Trusted application | Enable only after confirming OA's authorization-consent policy |
| OA menu URL | `https://<agent-host>/api/v1/auth/oauth/fanwei?next=/workspace` |

Set `auth.local.allow_registration: false` for an SSO-only deployment. This
disables local self-registration but does not disable OA users' first-login JIT
creation. Local phone/SMS registration is not provided. The public callback
and OA menu URL must use the same provider key, `fanwei`.

The `config.example.yaml` Fanwei block lists the environment references:
`FANWEI_OIDC_ISSUER`, `FANWEI_OIDC_DISCOVERY_URL`, `FANWEI_OIDC_CLIENT_ID`,
`FANWEI_OIDC_CLIENT_SECRET`, `FANWEI_SHADOW_EMAIL_SECRET`, and
`FANWEI_OIDC_REDIRECT_URI`. The shadow-email secret is a dedicated, stable
random value of at least 32 bytes. Do not reuse the client secret or JWT key.
Inject all values locally through the deployment environment or Secret Manager;
do not send them to developers. Keep `config.yaml` and secret values out of
source control. If OA discovery returns an internal or incorrect issuer,
repair OA's proxy configuration first. `metadata_mode: static` accepts explicit
authorize, token, profile, and JWKS endpoints, but **never** relaxes ID-token
issuer verification. Use separate `FANWEI_OIDC_AUTHORIZE_URL`,
`FANWEI_OIDC_TOKEN_URL`, `FANWEI_OIDC_PROFILE_URL`, and `FANWEI_OIDC_JWKS_URL`
references for static mode.

The profile token transport defaults to `bearer_header`. Use `post_form` only
after verifying support against the installed OA version. `query` is an
explicit compatibility setting: it places the access token in a request URL,
so proxy, APM, and access logs must redact the entire query string. PKCE S256
remains enabled by default. If that OA version rejects PKCE, disable it only
after an observed capability test; the confidential client, state, and nonce
remain mandatory. Do not assume support for `prompt=none` or iframe login.

### Identity, data ownership, and failure behavior

The verified `(iss, sub)` maps to one internal `users.id`. The nullable
`users.oauth_issuer` column and unique partial `(oauth_issuer, oauth_id)` index
enforce the mapping; existing `(oauth_provider, oauth_id)` rows remain valid.
Phone number, profile `id`, name, and employee number never select an account.
Phone number changes therefore leave conversations, memory, projects, and
files attached to the same internal user ID. First login creates a normal
`user` account with no local password. Its required internal email is
`oidc-v1-<base32(HMAC-SHA256(secret, issuer || NUL || sub))>@sso.example`:
it is not a notification address, login credential, or account-linking key.
Existing password accounts are never auto-linked. OA tokens are not stored.

| Condition | Result |
| --- | --- |
| Discovery issuer or ID-token issuer differs | Fail before provisioning; fix OA/proxy or configured issuer |
| Bad signature, `kid`, audience, expiry, issued-at, or nonce | Fail before provisioning; inspect OA signing configuration and clock |
| Missing `iss`/`sub` or failed profile business status | Fail before provisioning; inspect OA response contract |
| Same provider key points to a different issuer | Conflict; investigate configuration, never merge by phone/email |
| JIT disabled and no mapping exists | Access denied; enable JIT or use an approved migration |
| Concurrent first login | Unique index selects one account; a losing request re-reads only the same issuer/sub |

### Rollout, verification, and rollback

1. Back up the Agent database and deploy the additive `0027_fanwei_oidc_issuer`
   migration with the Gateway. Verify the new nullable column and partial
   unique index on the test PostgreSQL deployment.
2. Configure OA application, callback, trusted-app consent policy, and menu.
   Inject secrets locally, then enable the `fanwei_e10` provider and disable
   local self-registration if this is an SSO-only deployment.
3. Test OA-logged-in and OA-logged-out navigation, first and repeated login,
   concurrent first login, phone change, session expiry, and logout. Agent
   logout clears only its own session; the OA session remains active, so a
   later menu click can sign in again without a password. If global logout is
   required, coordinate it with OA and review its end-session endpoint as a
   separate rollout. Record
   only redacted issuer/endpoint consistency and pass/fail evidence. Test PKCE,
   nonce, profile transport, and JWKS rotation against the real OA version;
   these capabilities are not established by offline mock tests.
4. To roll back application behavior, disable the Fanwei provider and remove
   its OA menu. Preserve the additive issuer column and user rows during
   rollback so SSO data ownership remains recoverable. Rotate the client
   secret in OA and the deployment secret store if exposure is suspected;
   update both sides before re-enabling the provider.

Offline tests use synthetic credentials and never need a real OA client ID or
secret. Real OA integration must be performed by an operator with local secret
injection; do not paste credential or token values into tickets or chat.

DeerFlow supports single sign-on (SSO) via any OpenID Connect (OIDC) 2.0 compliant provider. This includes Keycloak, Google Workspace, Azure AD, Okta, and many others.

## Architecture

The OIDC flow uses the **Authorization Code flow** with PKCE (S256) and nonce validation for defense in depth:

```
Browser                      Gateway                    OIDC Provider
  │                             │                            │
  │  1. Click "Login with X"    │                            │
  │ ─────────────────────────▶  │                            │
  │                             │  2. Build auth URL         │
  │                             │     + state (signed cookie)│
  │                             │     + PKCE code_challenge  │
  │                             │     + nonce                │
  │                             │                            │
  │  3. Redirect to provider    │                            │
  │ ◀────────────────────────── │                            │
  │                             │                            │
  │  ──────────────────────────────────────────────────────▶ │
  │                             │   4. User authenticates    │
  │  ◀────────────────────────────────────────────────────── │
  │        5. Auth code + state │                            │
  │                             │                            │
  │  6. Callback → Gateway      │                            │
  │ ─────────────────────────▶  │                            │
  │                             │  7. Validate state cookie  │
  │                             │  8. Exchange code + PKCE   │
  │                             │     ─────────────────────▶ │
  │                             │     ◀──── tokens ──────────│
  │                             │  9. Validate ID token      │
  │                             │     (JWKS, iss, aud, nonce)│
  │                             │ 10. Fetch userinfo         │
  │                             │     ─────────────────────▶ │
  │                             │     ◀──── user claims ─────│
  │                             │ 11. Provision/link user    │
  │                             │ 12. Set session + CSRF     │
  │                             │     cookies                │
  │ ◀─ redirect to /auth/callback                            │
  │                             │                            │
  │ 13. Frontend detects auth   │                            │
  │     redirects to workspace  │                            │
```

**Key design decisions:**

- **State via signed cookie** — No server-side session store or Redis needed. The OIDC state (provider, nonce, code_verifier, next path) is signed with the JWT secret and stored in an HttpOnly cookie.
- **PKCE + nonce enabled by default** — Even though confidential clients could use `client_secret`, PKCE provides an extra layer of security.
- **No email auto-linking** — a pre-existing local (email/password) account is never auto-linked to an SSO identity. If the IdP-reported email collides with an existing local account, the SSO login is blocked with a 409 so an SSO login can never seize a password account.
- **Existing DeerFlow JWT** — After successful OIDC authentication, DeerFlow creates its own JWT session cookie. The OIDC provider's tokens are never exposed to the browser.

## Configuration

### Step 1: Enable OIDC in `config.yaml`

```yaml
auth:
  oidc:
    enabled: true
    frontend_base_url: http://localhost:3000
    providers:
      keycloak:
        display_name: Keycloak
        issuer: http://localhost:8080/realms/deerflow
        client_id: deerflow
        client_secret: $KEYCLOAK_CLIENT_SECRET
        redirect_uri: http://localhost:8001/api/v1/auth/callback/keycloak
        scopes:
          - openid
          - email
          - profile
```

### Step 2: Set the client secret as an environment variable

```bash
export KEYCLOAK_CLIENT_SECRET="your-client-secret"
```

Or create a `.env` file in the `backend/` directory:

```
KEYCLOAK_CLIENT_SECRET=your-client-secret
```

### Step 3: Restart the backend

```bash
cd backend && make dev
```

## Provider Configuration

### Per-Provider Options

```yaml
providers:
  <provider-id>:
    display_name: "Display Name"    # Shown on the SSO button
    issuer: "https://..."           # OIDC issuer URL (must match the provider's .well-known/openid-configuration)
    client_id: "..."                # OAuth2 client ID
    client_secret: $SECRET          # OAuth2 client secret (supports $ENV_VAR)
    redirect_uri: "..."             # Optional: explicit callback URL
    scopes:                         # Default: ["openid", "email", "profile"]
      - openid
      - email
    token_endpoint_auth_method: "client_secret_post"  # client_secret_post, client_secret_basic, or none

    # User provisioning
    auto_create_users: true         # Auto-create DeerFlow account on first SSO login (default: true)
    require_verified_email: true    # Reject logins without verified email (default: true)
    allowed_email_domains: []       # Restrict to specific domains (default: no restriction)
    admin_emails: []                # Auto-grant admin role to these emails (default: none)

    # Security features (both enabled by default)
    pkce_enabled: true
    nonce_enabled: true

    # Endpoint overrides (optional)
    # Use if the provider has non-standard endpoints.
    # authorization_endpoint: "https://..."
    # token_endpoint: "https://..."
    # userinfo_endpoint: "https://..."
    # jwks_uri: "https://..."
```

### Endpoint Overrides

Some providers don't return all endpoints from their `.well-known/openid-configuration`. You can override specific endpoints:

```yaml
providers:
  my-provider:
    display_name: "My Provider"
    issuer: "https://provider.example.com"
    client_id: "..."
    client_secret: $SECRET
    authorization_endpoint: "https://provider.example.com/oauth2/authorize"
    token_endpoint: "https://provider.example.com/oauth2/token"
    userinfo_endpoint: "https://provider.example.com/oauth2/userinfo"
    jwks_uri: "https://provider.example.com/oauth2/jwks"
```

## Local Keycloak Example

This section walks through setting up a local Keycloak instance with Podman or Docker for development.

### 1. Start Keycloak

```bash
# Using Podman
podman run -d \
  --name keycloak \
  -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:26.1 \
  start-dev

# Using Docker
docker run -d \
  --name keycloak \
  -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:26.1 \
  start-dev
```

### 2. Create a Realm and Client

1. Open the Keycloak admin console: http://localhost:8080
2. Log in with `admin` / `admin`
3. Create a new realm called `deerflow`
4. In the `deerflow` realm, go to **Clients** → **Create client**
5. Configure:
   - **Client ID**: `deerflow`
   - **Client authentication**: On (makes it a confidential client)
   - **Standard flow**: Enabled
   - **Valid redirect URIs**: `http://localhost:8001/api/v1/auth/callback/keycloak`
   - **Valid post logout redirect URIs**: `http://localhost:3000/*`
   - **Web origins**: `http://localhost:8001` (or `+` to allow all redirect URI origins)
6. After creating the client, go to the **Credentials** tab
7. Copy the **Client secret** — this is your `KEYCLOAK_CLIENT_SECRET`

### 3. Create a Test User

1. In the `deerflow` realm, go to **Users** → **Add user**
2. Set **Username**: `testuser`
3. Set **Email**: `testuser@example.com`
4. Set **Email verified**: On
5. Go to the **Credentials** tab
6. Set a password (e.g. `testpass123`)
7. Set **Temporary**: Off

### 4. Configure DeerFlow

Add to `config.yaml`:

```yaml
auth:
  oidc:
    enabled: true
    frontend_base_url: http://localhost:3000
    providers:
      keycloak:
        display_name: Keycloak
        issuer: http://localhost:8080/realms/deerflow
        client_id: deerflow
        client_secret: $KEYCLOAK_CLIENT_SECRET
        redirect_uri: http://localhost:8001/api/v1/auth/callback/keycloak
        scopes:
          - openid
          - email
          - profile
```

Set the secret:

```bash
export KEYCLOAK_CLIENT_SECRET="the-secret-from-step-2"
```

### 5. Restart and Test

```bash
cd backend && make dev
```

1. Open http://localhost:3000
2. On the login page, click **Login with Keycloak**
3. You'll be redirected to Keycloak's login page
4. Log in with `testuser` / `testpass123`
5. After successful authentication, you'll be redirected back to the DeerFlow workspace

## Account Settings for SSO Users

When a user logs in via SSO, the account settings page detects this (via the `oauth_provider` field returned by `/api/v1/auth/me`) and:

- Displays the SSO provider name (e.g. "Keycloak") in the profile section
- Replaces the password change form with an informational message
- Password changes must be done through the SSO provider, not DeerFlow

The backend also rejects password change requests for OAuth users:

```json
{
  "code": "invalid_credentials",
  "message": "OAuth users cannot change password"
}
```

## Public API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/auth/providers` | Returns list of enabled SSO providers (safe metadata only) |
| `GET /api/v1/auth/oauth/{provider}` | Initiates SSO login, redirects to the OIDC provider |
| `GET /api/v1/auth/callback/{provider}` | OIDC callback — exchanges code, creates session, redirects to frontend |

## Frontend Callback Flow

The frontend handles the post-SSO flow at `/auth/callback`:

1. After the backend processes the OIDC callback and sets cookies, it redirects to `{frontend_base_url}/auth/callback?next=...`
2. The callback page calls `GET /api/v1/auth/me`
3. On success: redirects to the workspace (or the original `next` path)
4. On failure: redirects to `/login?error=sso_failed`

## Security Notes

- **State cookies** are HttpOnly, SameSite=Lax, Max-Age=300 seconds, and signed with the JWT secret
- **PKCE** prevents authorization code interception attacks
- **Nonce** prevents ID token replay attacks
- **UserInfo sub check** ensures the UserInfo response matches the ID token subject
- **Reject alg=none** — ID tokens with algorithm "none" are always rejected
- **No email auto-linking** — SSO accounts are always separate from email/password accounts. An email collision with an existing local account blocks the SSO login (409) rather than merging the two.
- **Verified email requirement** — SSO users must have verified emails by default
