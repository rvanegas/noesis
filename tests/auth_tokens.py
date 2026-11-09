"""auth's access tokens, for tests: signed with a key of the tests' own, published as auth's.

noesis checks tokens against auth's keys (bearer.py); here the keys are this
module's, and `install` points noesis at them instead of fetching auth's.
"""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

AUTH = "https://auth.test"
KEY = Ed25519PrivateKey.generate()
KID = "test-key"
STRANGER = Ed25519PrivateKey.generate()


def install(monkeypatch) -> None:
    from noesis import bearer
    monkeypatch.setenv("NOESIS_AUTH_URL", AUTH)
    monkeypatch.setattr(bearer, "_fetch_keys", lambda: {KID: KEY.public_key()})
    monkeypatch.setattr(bearer, "_jwks", {"keys": {}, "fetched": 0.0})


def token(user, scopes=("noesis:api", "noesis:read"), client="noesis-web", aud=AUTH, ttl=900,
          key=KEY, issuer=AUTH) -> str:
    now = int(time.time())
    return jwt.encode({"iss": issuer, "sub": user, "aud": aud, "client_id": client, "scope": " ".join(scopes),
                       "iat": now, "exp": now + ttl}, key, algorithm="EdDSA", headers={"kid": KID})


def bearer(user, **kwargs) -> dict:
    return {"Authorization": f"Bearer {token(user, **kwargs)}"}
