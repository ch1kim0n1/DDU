"""Production identity assertion verification for DDU Mirror.

The discovery service never sends verification emails and never owns an OAuth
login screen. It consumes a signed OIDC/service assertion produced by the
identity boundary, verifies it locally, and derives the only identifiers that
workers may scan. In production, unsigned identifier lists are disabled.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Iterable

import jwt

from .guardrails import VerifiedIdentity


class IdentityVerificationError(ValueError):
    """A caller did not provide a valid, verified identity assertion."""


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _values(claims: dict[str, Any], name: str) -> list[str]:
    value = claims.get(name)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        return [str(item) for item in value if str(item).strip()]
    raise IdentityVerificationError(f"identity claim {name!r} must be a string or list")


@dataclass(frozen=True)
class IdentityAssertion:
    issuer: str
    subject: str
    emails: tuple[str, ...]
    handles: tuple[str, ...]
    account_urls: tuple[str, ...]

    @property
    def subject_ref(self) -> str:
        digest = hashlib.sha256(f"{self.issuer}\x00{self.subject}".encode()).hexdigest()
        return f"subject:{digest[:24]}"

    def build_identity(self, session_id: str) -> VerifiedIdentity:
        return VerifiedIdentity.build(
            session_id=session_id,
            emails=self.emails,
            handles=self.handles,
            account_urls=self.account_urls,
            subject_ref=self.subject_ref,
        )


class IdentityVerifier:
    """Verify RS/ES OIDC tokens from JWKS or internal HS256 assertions."""

    def __init__(self) -> None:
        self.issuer = os.environ.get("MIRROR_IDENTITY_ISSUER", "").strip()
        self.audience = os.environ.get("MIRROR_IDENTITY_AUDIENCE", "").strip()
        self.jwks_url = os.environ.get("MIRROR_IDENTITY_JWKS_URL", "").strip()
        self.shared_secret = os.environ.get("MIRROR_IDENTITY_HS256_SECRET", "").strip()
        self.algorithms = [
            item.strip()
            for item in os.environ.get("MIRROR_IDENTITY_ALGORITHMS", "RS256,ES256").split(",")
            if item.strip()
        ]
        self.email_claim = os.environ.get("MIRROR_IDENTITY_EMAIL_CLAIM", "email")
        self.email_verified_claim = os.environ.get(
            "MIRROR_IDENTITY_EMAIL_VERIFIED_CLAIM", "email_verified"
        )
        self.handle_claim = os.environ.get("MIRROR_IDENTITY_HANDLE_CLAIM", "preferred_username")
        self.account_urls_claim = os.environ.get(
            "MIRROR_IDENTITY_ACCOUNT_URLS_CLAIM", "account_urls"
        )
        self._jwks_client = jwt.PyJWKClient(self.jwks_url, cache_keys=True) if self.jwks_url else None

        if self.required and not self.configured:
            raise RuntimeError(
                "MIRROR_IDENTITY_REQUIRED is enabled but neither "
                "MIRROR_IDENTITY_JWKS_URL nor MIRROR_IDENTITY_HS256_SECRET is configured"
            )
        if self.configured and (not self.issuer or not self.audience):
            raise RuntimeError(
                "configured identity verification requires MIRROR_IDENTITY_ISSUER "
                "and MIRROR_IDENTITY_AUDIENCE"
            )

    @property
    def required(self) -> bool:
        env = os.environ.get("MIRROR_ENV", "development").strip().lower()
        return _truthy("MIRROR_IDENTITY_REQUIRED") or env == "production"

    @property
    def configured(self) -> bool:
        return bool(self.jwks_url or self.shared_secret)

    @property
    def mode(self) -> str:
        if self.jwks_url:
            return "oidc-jwks"
        if self.shared_secret:
            return "signed-service-assertion"
        return "development"

    def verify(self, token: str) -> IdentityAssertion:
        if not token:
            raise IdentityVerificationError("a bearer identity assertion is required")
        try:
            if self._jwks_client is not None:
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=self.algorithms,
                    audience=self.audience,
                    issuer=self.issuer,
                    options={"require": ["exp", "iat", "iss", "sub", "aud"]},
                )
            elif self.shared_secret:
                claims = jwt.decode(
                    token,
                    self.shared_secret,
                    algorithms=["HS256"],
                    audience=self.audience,
                    issuer=self.issuer,
                    options={"require": ["exp", "iat", "iss", "sub", "aud"]},
                )
            else:
                raise IdentityVerificationError("identity verifier is not configured")
        except IdentityVerificationError:
            raise
        except jwt.PyJWTError as exc:
            raise IdentityVerificationError("identity assertion verification failed") from exc

        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise IdentityVerificationError("identity assertion has no subject")

        emails = _values(claims, self.email_claim)
        if emails and claims.get(self.email_verified_claim) is not True:
            raise IdentityVerificationError("identity assertion email is not verified")
        handles = _values(claims, self.handle_claim)
        account_urls = _values(claims, self.account_urls_claim)
        if not (emails or handles or account_urls):
            raise IdentityVerificationError(
                "identity assertion contains no verified scannable identifier claims"
            )
        return IdentityAssertion(
            issuer=str(claims["iss"]),
            subject=subject,
            emails=tuple(emails),
            handles=tuple(handles),
            account_urls=tuple(account_urls),
        )

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "configured": self.configured,
            "required": self.required,
            "issuer": self.issuer or None,
            "audience": self.audience or None,
        }


verifier = IdentityVerifier()
