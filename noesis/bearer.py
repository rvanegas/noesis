"""The bearer tokens noesis takes, now that sign-in is auth's (2026-11-08).

noesis is a resource server: people sign in at auth (`auth.rvanegas.co`,
`~/src/dianoia-auth`), which issues every OAuth token, and noesis checks them. Three
kinds of token reach it:

- **auth's access tokens**: EdDSA JWTs, checked against auth's published keys
  (`/.well-known/jwks.json`, kept a few minutes, asked again for a key it does
  not know) by issuer, expiry and audience (auth, or noesis). Their scopes say
  what they reach: `noesis:read` the MCP tools, `noesis:import` filing
  conversations and the speaker names, `noesis:api` the file and run API;
  `noesis:keep` is an application's own token (The Floor keeping libraries,
  members.py), whose `sub` is its client id. A disabled account's tokens
  last out their quarter hour: auth refuses refresh at once.
- **Minted noesis tokens** (users.toml, scripts/add_token.py): the CLI's and
  the nightly service's, sent as they are, reaching everything.
- **Library-confined tokens**: noesis's own, an hour, for /mcp and one of an
  application's libraries alone (`confined_token`), which The Floor hands
  Anthropic's servers; kept as hashes in $NOESIS_DATA_DIR/confined.json.

noesis also holds a client of its own at auth (NOESIS_AUTH_CLIENT_ID and
NOESIS_AUTH_CLIENT_SECRET), whose token (`own_token`) it presents when it asks
an application who belongs to a library.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
import urllib.request

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from noesis import service

READ = "noesis:read"
IMPORT = "noesis:import"
API = "noesis:api"
KEEP = "noesis:keep"
# A token confined to one library: `library:<owner>/<name>` (confined_token).
LIBRARY_SCOPE = "library:"
# What a minted token is called where a client id is asked for.
MINTED = "noesis-token"

ACCESS_TTL = 60 * 60
JWKS_TTL = 5 * 60
# However often an unknown key is shown, auth is asked again at most this often.
JWKS_RETRY = 30

_jwks: dict = {"keys": {}, "fetched": 0.0}
_own: dict = {}


def auth_url() -> str:
    return os.environ.get("NOESIS_AUTH_URL", "https://auth.rvanegas.co").rstrip("/")


def _sha(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


def _fetch_keys() -> dict:
    with urllib.request.urlopen(f"{auth_url()}/.well-known/jwks.json", timeout=10) as response:
        found = json.loads(response.read())
    return {k["kid"]: jwt.PyJWK.from_dict(k).key for k in found.get("keys", []) if k.get("kid")}


def _key(kid: str):
    now = time.monotonic()
    stale = now - _jwks["fetched"] > JWKS_TTL
    if (stale or kid not in _jwks["keys"]) and now - _jwks.get("tried", -JWKS_RETRY) >= JWKS_RETRY:
        _jwks["tried"] = now
        try:
            _jwks["keys"], _jwks["fetched"] = _fetch_keys(), now
        except (OSError, ValueError):
            pass  # auth unreachable: the keys already known still verify
    return _jwks["keys"].get(kid)


def _claims(token: str) -> dict | None:
    """An auth access token's claims, if it is one and good for noesis."""
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        return None
    key = _key(kid) if kid else None
    if key is None:
        return None
    from noesis.mcp_server import public_url
    try:
        return jwt.decode(token, key, algorithms=["EdDSA"], issuer=auth_url(),
                          audience=[auth_url(), public_url(), f"{public_url()}/mcp"])
    except jwt.PyJWTError:
        return None


def _confined_path():
    return service.data_dir() / "confined.json"


def _load_confined() -> dict:
    try:
        return json.loads(_confined_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def confined_token(owner: str, library_id: str) -> tuple[str, int]:
    """An access token of an application's own, for /mcp alone and one of its
    libraries alone (`LIBRARY_SCOPE`): what it hands Anthropic's servers when
    Claude consults that library. No refresh: it asks again."""
    now = time.time()
    data = {k: v for k, v in _load_confined().items() if v["expires_at"] > now}
    token = secrets.token_urlsafe(32)
    data[_sha(token)] = {"owner": owner, "library": library_id, "expires_at": now + ACCESS_TTL}
    path = _confined_path()
    tmp = path.with_name(".confined.json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return token, ACCESS_TTL


def access_token(token: str) -> AccessToken | None:
    """Whatever the bearer is: a minted token, a confined one, or auth's."""
    user = service.user_for_token(token)
    if user is not None:
        return AccessToken(token=token, client_id=MINTED, scopes=[READ, IMPORT, API], subject=user)
    entry = _load_confined().get(_sha(token))
    if entry is not None:
        if entry["expires_at"] < time.time():
            return None
        return AccessToken(token=token, client_id=entry["owner"], subject=entry["owner"],
                           scopes=[READ, LIBRARY_SCOPE + entry["library"]], expires_at=int(entry["expires_at"]))
    claims = _claims(token)
    if claims is None:
        return None
    return AccessToken(token=token, client_id=claims.get("client_id", ""), subject=claims.get("sub"),
                       scopes=(claims.get("scope") or "").split(), expires_at=claims.get("exp"),
                       resource=claims.get("aud") if isinstance(claims.get("aud"), str) else None)


class Verifier(TokenVerifier):
    """The MCP SDK's way to ask about a token: /mcp's."""

    async def verify_token(self, token: str) -> AccessToken | None:
        return access_token(token)


def own_token(scope: str) -> str:
    """noesis's own token from auth, by client_credentials, kept until shortly before it expires."""
    hit = _own.get(scope)
    if hit and hit[1] > time.time() + 60:
        return hit[0]
    client_id = os.environ.get("NOESIS_AUTH_CLIENT_ID", "")
    secret = os.environ.get("NOESIS_AUTH_CLIENT_SECRET", "")
    if not client_id or not secret:
        raise OSError("noesis has no client at auth (NOESIS_AUTH_CLIENT_ID, NOESIS_AUTH_CLIENT_SECRET)")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": scope,
                                   "client_id": client_id, "client_secret": secret}).encode()
    with urllib.request.urlopen(f"{auth_url()}/token", data=body, timeout=10) as response:
        found = json.loads(response.read())
    _own[scope] = (found["access_token"], time.time() + found["expires_in"])
    return found["access_token"]
