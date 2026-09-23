"""Provider-specific OIDC response normalization at the trust boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any


class FanweiProfileError(ValueError):
    """A Fanwei profile failed validation; messages contain no provider data."""


@dataclass(frozen=True)
class SupplementalClaims:
    mobile: str | None = None
    name: str | None = None
    job_number: str | None = None
    source_account_id: str | None = None


def derive_shadow_email(secret: str, issuer: str, subject: str) -> str:
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("A dedicated shadow email secret of at least 32 bytes is required")
    digest = hmac.new(secret.encode("utf-8"), issuer.encode("utf-8") + b"\x00" + subject.encode("utf-8"), hashlib.sha256).digest()
    return "oidc-v1-" + base64.b32encode(digest).decode("ascii").rstrip("=").lower() + "@sso.example"


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_fanwei_profile(raw: dict[str, Any], verified_sub: str) -> SupplementalClaims:
    if raw.get("status") != 200 or str(raw.get("code")) != "0" or raw.get("msg") != "SUCCESS":
        raise FanweiProfileError("Fanwei profile returned an unsuccessful business status")
    attributes = raw.get("attributes", {})
    if not isinstance(attributes, dict):
        raise FanweiProfileError("Fanwei profile attributes must be an object")
    subject = raw.get("sub")
    if subject is not None and (not isinstance(subject, str) or not hmac.compare_digest(subject, verified_sub)):
        raise FanweiProfileError("Fanwei profile subject differs from verified ID token subject")
    mobile = _optional_text(attributes.get("mobile"))
    if mobile is not None:
        mobile = re.sub(r"[\s-]", "", mobile)
        if not re.fullmatch(r"\+?[1-9]\d{5,14}", mobile):
            mobile = None
    return SupplementalClaims(
        mobile=mobile,
        name=_optional_text(attributes.get("username")),
        job_number=_optional_text(attributes.get("job_num")),
        source_account_id=_optional_text(raw.get("id")),
    )
