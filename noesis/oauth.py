"""noesis's own OAuth authorization server (SERVER.md, Phases 5b and 6).

noesis is the identity for everyone who uses it, and every other app reaches a
person's libraries through a grant from here, never a shared identity
(rvanegas-site's PROJECTS.md, Shared rules): claude.ai's connector, noesis's web
client, and in time The Floor and Roxana. claude.ai registers itself (dynamic
client registration) and sends the person to noesis's /oauth/login, where they
give their email address and then the code mailed to it; the first sign-in
makes their account (accounts.py: sign-up is open, spending is capped). The
client gets OAuth tokens for that person: an access token for an hour, a
refresh token for 90 days, rotated on every use.

The MCP SDK serves the protocol (metadata, /register, /authorize, /token,
/revoke, PKCE); this is its provider: storage and the sign-in.

- **Redirects are limited** to claude.ai's and claude.com's callbacks and to
  localhost (Claude Code): registration is open to anyone, and the sign-in
  must not send a code where its asker says.
- **A code** is six digits, kept as a hash with the pending sign-in it was
  sent for, good for ten minutes and five tries; a new one costs a mail, which
  accounts.allow_send limits.
- **OAuth tokens follow the account:** each records it, and stops working once
  the account is disabled (scripts/accounts.py).
- **Stored** in $NOESIS_DATA_DIR/oauth.json (mode 600), hashes only, so a deploy
  does not sign anybody out; codes and pending sign-ins live minutes, in memory.

`/mcp` also takes a minted noesis token as a bearer token directly (Claude Code,
the CLI), through `load_access_token`.

- **noesis's own web client** (`noesis/web/`, at /web/) is a built-in client,
  `noesis-web`, not a registered one: a public client (PKCE, no secret) whose
  only redirect is /web/ on this server. Registration cannot claim that
  redirect, since `allowed_redirect` does not name this host. Its tokens are
  the only OAuth tokens the file and run API takes (`API_CLIENTS`); claude.ai's
  reach /mcp alone.
- **An application that only signs people in** (Roxana: a browser app with
  no server of its own) is a public client registered by the operator
  (`scripts/add_client.py --public`), marked identity-only in oauth.json. Its
  tokens answer /me, so it learns who signed in, and nothing else: not /mcp,
  not the file and run API. dianoia accepts them from Roxana's callers by
  asking /me, which names the client a token was issued to. Its redirects'
  origins are the browser origins /me answers (`browser_origins`).
- **An application that files conversations** (The Floor: a room's text,
  sent from its *Record* tab) is a confidential client the operator has
  marked as one (`scripts/client_imports.py`). It may ask for the `import`
  scope, which the sign-in page names, and a token carrying it reaches
  `POST …/import` and `PUT /me/names` besides /mcp and /me — nothing else of
  the file and run API. Only the operator's mark lets a client have it:
  registration is open, and what a client says of itself there is not
  consulted, so claude.ai's connector can never be given it.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from noesis import service

ACCESS_TTL = 60 * 60
REFRESH_TTL = 90 * 24 * 60 * 60
CODE_TTL = 5 * 60
SIGN_IN_TTL = 10 * 60
SIGN_IN_ATTEMPTS = 5
CODE_DIGITS = 6

ALLOWED_CALLBACKS = {
    ("https", "claude.ai", "/api/mcp/auth_callback"),
    ("https", "claude.com", "/api/mcp/auth_callback"),
}


WEB_CLIENT_ID = "noesis-web"

# Who may call the file and run API besides a minted noesis token ("noesis-token",
# as load_access_token names it): only noesis's own web client. A connector's
# token stays on /mcp, which writes nothing.
API_CLIENTS = frozenset({"noesis-token", WEB_CLIENT_ID})

# What an application the operator marked (`imports`) may ask for: to file
# conversations into the person's libraries, and say whose voice is theirs.
IMPORT_SCOPE = "import"


def web_client() -> OAuthClientInformationFull:
    from noesis.mcp_server import public_url
    return OAuthClientInformationFull(
        client_id=WEB_CLIENT_ID,
        client_name="noesis on the web",
        redirect_uris=[f"{public_url()}/web/"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )


def _origin(uri: str) -> str:
    u = urlparse(uri)
    return f"{u.scheme}://{u.netloc}"


def allowed_redirect(uri: str) -> bool:
    u = urlparse(uri)
    if (u.scheme, u.hostname, u.path) in ALLOWED_CALLBACKS:
        return True
    return u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class SignIn:
    client: OAuthClientInformationFull
    params: AuthorizationParams
    expires_at: float
    attempts: int = 0
    email: str = ""
    code_sha: str = ""


class NoesisOAuthProvider:
    def __init__(self) -> None:
        self.sign_ins: dict[str, SignIn] = {}
        self.codes: dict[str, AuthorizationCode] = {}

    # --- storage -----------------------------------------------------------

    def _path(self) -> Path:
        return service.data_dir() / "oauth.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"clients": {}, "access": {}, "refresh": {}}

    def _save(self, data: dict) -> None:
        now = time.time()
        for kind in ("access", "refresh"):
            data[kind] = {k: v for k, v in data[kind].items() if v["expires_at"] > now}
        path = self._path()
        tmp = path.with_name(".oauth.json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)

    # --- clients -----------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if client_id == WEB_CLIENT_ID:
            return web_client()
        raw = self._load()["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    def identity_only(self, client_id: str) -> bool:
        """A client whose tokens say who signed in, and reach nothing else."""
        raw = self._load()["clients"].get(client_id)
        return bool(raw and raw.get("identity_only"))

    def imports(self, client_id: str) -> bool:
        """A client the operator marked as one that files conversations (IMPORT_SCOPE)."""
        raw = self._load()["clients"].get(client_id)
        return bool(raw and raw.get("imports"))

    def may_import(self, token: AccessToken) -> bool:
        """A token that was granted the import scope, by a client still marked for it."""
        return IMPORT_SCOPE in (token.scopes or []) and self.imports(token.client_id)

    def browser_origins(self) -> set[str]:
        """The origins of identity-only clients' redirects: the browser apps that read /me."""
        return {_origin(uri) for raw in self._load()["clients"].values() if raw.get("identity_only")
                for uri in raw.get("redirect_uris") or []}

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        bad = [str(u) for u in (client_info.redirect_uris or []) if not allowed_redirect(str(u))]
        if bad:
            raise RegistrationError(error="invalid_redirect_uri",
                                    error_description=f"not a redirect this server sends to: {', '.join(bad)}")
        data = self._load()
        data["clients"][client_info.client_id] = client_info.model_dump(mode="json")
        self._save(data)

    # --- sign-in -----------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        now = time.time()
        self.sign_ins = {k: v for k, v in self.sign_ins.items() if v.expires_at > now}
        request_id = secrets.token_urlsafe(24)
        self.sign_ins[request_id] = SignIn(client, params, now + SIGN_IN_TTL)
        from noesis.mcp_server import public_url
        return f"{public_url()}/oauth/login?request={request_id}"

    def pending(self, request_id: str) -> SignIn | None:
        sign_in = self.sign_ins.get(request_id)
        if sign_in is None or sign_in.expires_at < time.time() or sign_in.attempts >= SIGN_IN_ATTEMPTS:
            return None
        return sign_in

    def send_code(self, request_id: str, email: str, ip: str) -> str | None:
        """Mails a code for this sign-in; why not, if it was not sent."""
        from noesis import accounts, mail
        sign_in = self.pending(request_id)
        if sign_in is None:
            return "This sign-in has expired; start again from the app."
        address = accounts.normalize_email(email)
        if address is None:
            return "That is not an email address."
        if not accounts.allow_send(address, ip):
            return "Too many codes were asked for; try again in an hour."
        code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
        try:
            mail.send_code(address, code, sign_in.client.client_name or "An application")
        except mail.MailUnavailable:
            return "The code could not be sent; try again later."
        sign_in.email, sign_in.code_sha, sign_in.attempts = address, _sha(code), 0
        sign_in.expires_at = time.time() + SIGN_IN_TTL
        return None

    def verify_code(self, request_id: str, code: str) -> str | None:
        """The redirect back to the client with an OAuth code, if the code is the one sent."""
        from noesis import accounts
        sign_in = self.pending(request_id)
        if sign_in is None or not sign_in.code_sha:
            return None
        sign_in.attempts += 1
        if not secrets.compare_digest(_sha(code.strip()), sign_in.code_sha):
            return None
        found = accounts.account_for_email(sign_in.email) or accounts.create_account(sign_in.email)
        if found.disabled:
            return None
        del self.sign_ins[request_id]
        oauth_code = secrets.token_urlsafe(32)
        params = sign_in.params
        # The import scope only where the operator marked the client, whatever it asked.
        scopes = [s for s in params.scopes or []
                  if s != IMPORT_SCOPE or self.imports(sign_in.client.client_id)]
        self.codes[oauth_code] = AuthorizationCode(
            code=oauth_code, scopes=scopes, expires_at=time.time() + CODE_TTL,
            client_id=sign_in.client.client_id, code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource, subject=found.user,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=oauth_code, state=params.state)

    def restart(self, request_id: str) -> None:
        """Back to asking for an address: the code sent is forgotten."""
        sign_in = self.pending(request_id)
        if sign_in is not None:
            sign_in.email = sign_in.code_sha = ""

    def refuse(self, request_id: str) -> str | None:
        """The redirect back with access_denied, when the person declines."""
        sign_in = self.sign_ins.pop(request_id, None)
        if sign_in is None:
            return None
        return construct_redirect_uri(str(sign_in.params.redirect_uri),
                                      error="access_denied", state=sign_in.params.state)

    # --- tokens ------------------------------------------------------------

    async def load_authorization_code(self, client, authorization_code: str) -> AuthorizationCode | None:
        code = self.codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        return code

    def _issue(self, data: dict, client_id: str, user: str, scopes: list[str],
               resource: str | None) -> OAuthToken:
        now = int(time.time())
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        common = {"client_id": client_id, "user": user, "scopes": scopes, "resource": resource}
        data["access"][_sha(access)] = {**common, "expires_at": now + ACCESS_TTL, "refresh": _sha(refresh)}
        data["refresh"][_sha(refresh)] = {**common, "expires_at": now + REFRESH_TTL}
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, refresh_token=refresh,
                          scope=" ".join(scopes) or None)

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        self.codes.pop(authorization_code.code, None)
        data = self._load()
        token = self._issue(data, client.client_id, authorization_code.subject or "",
                            authorization_code.scopes, authorization_code.resource)
        self._save(data)
        return token

    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        entry = self._load()["refresh"].get(_sha(refresh_token))
        if (entry is None or entry["client_id"] != client.client_id
                or entry["expires_at"] < time.time() or not self._still_signed_in(entry)):
            return None
        return RefreshToken(token=refresh_token, client_id=entry["client_id"], scopes=entry["scopes"],
                            expires_at=entry["expires_at"], resource=entry["resource"], subject=entry["user"])

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        data = self._load()
        entry = data["refresh"].pop(_sha(refresh_token.token))
        data["access"] = {k: v for k, v in data["access"].items() if v.get("refresh") != _sha(refresh_token.token)}
        token = self._issue(data, client.client_id, entry["user"], scopes or entry["scopes"],
                            entry["resource"])
        self._save(data)
        return token

    async def load_access_token(self, token: str) -> AccessToken | None:
        """A token for /mcp and the API: an identity-only client's reaches neither."""
        found = await self.load_any_access_token(token)
        if found is not None and self.identity_only(found.client_id):
            return None
        return found

    async def load_any_access_token(self, token: str) -> AccessToken | None:
        """Any client's token, for what says only who signed in (/me)."""
        entry = self._load()["access"].get(_sha(token))
        if entry is not None:
            if entry["expires_at"] < time.time() or not self._still_signed_in(entry):
                return None
            return AccessToken(token=token, client_id=entry["client_id"], scopes=entry["scopes"],
                               expires_at=entry["expires_at"], resource=entry["resource"], subject=entry["user"])
        # A minted noesis token, sent as it is (Claude Code, the CLI).
        user = service.user_for_token(token)
        if user is not None:
            return AccessToken(token=token, client_id="noesis-token", scopes=[], subject=user)
        return None

    async def revoke_token(self, token) -> None:
        data = self._load()
        digest = _sha(token.token)
        if digest in data["access"]:
            refresh = data["access"].pop(digest).get("refresh")
            data["refresh"].pop(refresh, None)
        elif digest in data["refresh"]:
            data["refresh"].pop(digest)
            data["access"] = {k: v for k, v in data["access"].items() if v.get("refresh") != digest}
        self._save(data)

    @staticmethod
    def _still_signed_in(entry: dict) -> bool:
        from noesis import accounts
        return accounts.is_active(entry["user"])


provider = NoesisOAuthProvider()
