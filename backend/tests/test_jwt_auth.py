import time
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from core.jwt_auth import InvalidTokenError, SupabaseJWTVerifier, TokenExpiredError

TEST_SECRET = "super-secret-test-jwt-key-32-bytes-long!"


def test_hs256_valid_token():
    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co", secret=TEST_SECRET)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-uuid-1234", "aud": "authenticated", "exp": now + 3600, "role": "authenticated"},
        TEST_SECRET,
        algorithm="HS256",
    )
    payload = verifier.verify(token)
    assert payload["sub"] == "user-uuid-1234"
    assert payload["aud"] == "authenticated"


def test_hs256_expired_token():
    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co", secret=TEST_SECRET)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-uuid-1234", "aud": "authenticated", "exp": now - 10, "role": "authenticated"},
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenExpiredError):
        verifier.verify(token)


def test_hs256_forged_signature():
    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co", secret=TEST_SECRET)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-uuid-1234", "aud": "authenticated", "exp": now + 3600, "role": "authenticated"},
        "wrong-secret-key",
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_hs256_wrong_audience():
    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co", secret=TEST_SECRET)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-uuid-1234", "aud": "anon", "exp": now + 3600, "role": "anon"},
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_hs256_missing_sub():
    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co", secret=TEST_SECRET)
    now = int(time.time())
    token = jwt.encode(
        {"aud": "authenticated", "exp": now + 3600, "role": "authenticated"},
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_malformed_token_rejected_immediately():
    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co", secret=TEST_SECRET)
    with pytest.raises(InvalidTokenError):
        verifier.verify("not-a-real-jwt")
    with pytest.raises(InvalidTokenError):
        verifier.verify("header.payload")


def test_es256_asymmetric_validation():
    # Generate an EC P-256 key pair
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co")
    # Mock PyJWKClient to return public key
    mock_jwk_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key
    verifier._jwks_client = mock_jwk_client

    now = int(time.time())
    headers = {"kid": "test-key-id", "alg": "ES256"}
    token = jwt.encode(
        {"sub": "asymmetric-user-5678", "aud": "authenticated", "exp": now + 3600, "role": "authenticated"},
        private_key,
        algorithm="ES256",
        headers=headers,
    )

    payload = verifier.verify(token)
    assert payload["sub"] == "asymmetric-user-5678"
    mock_jwk_client.get_signing_key_from_jwt.assert_called_once_with(token)


def test_es256_forged_asymmetric_signature():
    private_key1 = ec.generate_private_key(ec.SECP256R1())
    private_key2 = ec.generate_private_key(ec.SECP256R1())
    public_key2 = private_key2.public_key()

    verifier = SupabaseJWTVerifier(supabase_url="https://test.supabase.co")
    mock_jwk_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key2
    mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key
    verifier._jwks_client = mock_jwk_client

    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-uuid", "aud": "authenticated", "exp": now + 3600},
        private_key1,  # Signed with key 1, but verified with key 2
        algorithm="ES256",
        headers={"kid": "test-key-id"},
    )

    with pytest.raises(InvalidTokenError):
        verifier.verify(token)
