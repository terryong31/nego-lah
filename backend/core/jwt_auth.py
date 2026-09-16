"""
Local cryptographic Supabase JWT verification.

Verifies Supabase JWT access tokens locally without making synchronous
network calls to `GET /auth/v1/user`.
- Asymmetric keys (ES256 / RS256): verified against Supabase's JWKS endpoint
  with key caching (10-minute TTL matching Supabase Edge).
- Symmetric keys (HS256): verified against SUPABASE_JWT_SECRET if configured.
- Validates expiration (exp) and audience (aud == "authenticated").
- Extracts `sub` as `user_id`.
- Rejects forged, expired, or tampered tokens in microseconds on CPU.
"""

import os
from typing import Any

import jwt

from env import SUPABASE_URL


class TokenExpiredError(Exception):
    """Raised when token signature is valid but expired."""


class InvalidTokenError(Exception):
    """Raised when token signature, format, or claims are invalid."""


class SupabaseJWTVerifier:
    def __init__(self, supabase_url: str | None = None, secret: str | None = None):
        self.supabase_url = (supabase_url or SUPABASE_URL or "").rstrip("/")
        self.secret = secret or os.getenv("SUPABASE_JWT_SECRET")

        self._jwks_client: jwt.PyJWKClient | None = None
        if self.supabase_url:
            jwks_url = f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
            self._jwks_client = jwt.PyJWKClient(
                jwks_url,
                cache_jwk_set=True,
                lifespan=600,  # 10 minutes
            )

    def verify(self, token: str) -> dict[str, Any]:
        """
        Verify JWT token locally and return decoded claims.
        Raises TokenExpiredError or InvalidTokenError on failure.
        """
        if not token or not isinstance(token, str):
            raise InvalidTokenError("Token must be a non-empty string")

        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidTokenError("Malformed JWT token")

        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:
            raise InvalidTokenError(f"Cannot parse JWT header: {e}") from e

        alg = unverified_header.get("alg")
        if not alg:
            raise InvalidTokenError("Missing 'alg' in token header")

        try:
            if alg in ("ES256", "RS256"):
                if not self._jwks_client:
                    raise InvalidTokenError("No JWKS client configured for asymmetric validation")
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                key = signing_key.key
                algorithms = [alg]
            elif alg == "HS256":
                if not self.secret:
                    raise InvalidTokenError("HS256 token received but SUPABASE_JWT_SECRET not configured")
                key = self.secret
                algorithms = ["HS256"]
            else:
                raise InvalidTokenError(f"Unsupported algorithm '{alg}'")

            payload = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience="authenticated",
                options={"verify_aud": True, "verify_exp": True},
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Token expired") from e
        except jwt.PyJWTError as e:
            raise InvalidTokenError(f"Invalid token: {e}") from e
        except Exception as e:
            raise InvalidTokenError(f"Token verification failed: {e}") from e

        if not payload.get("sub"):
            raise InvalidTokenError("Missing subject (sub) in token claims")

        return payload


# Singleton instance
jwt_verifier = SupabaseJWTVerifier()
