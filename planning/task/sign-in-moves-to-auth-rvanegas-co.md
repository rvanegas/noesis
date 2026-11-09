# Sign-in moves to auth.rvanegas.co

Decided 2026-11-08 (rvanegas-site
`planning/task/one-sign-in-for-every-project-at-auth-rvanegas-co.md`, which
is the design): noesis's OAuth server becomes a
service of its own, then gains SSO and passkeys there.

noesis's part is Phase 1. The provider in `oauth.py`, `/oauth/login`,
`mail.py`, the identity half of `accounts.py` (the `accounts` and
`reservations` tables, `sends`, `create_account` and user-name derivation),
`names.py` with the `/names` routes, and the operator scripts for them
(`add_client.py`, `client_names.py`, `reserve_names.py`, `link_accounts.py`,
the account half of `rename_user.py`) move to `~/src/dianoia-auth`, removed here
completely. noesis keeps billing (plan, allowance raises, spend), speaker
names, its minted `users.toml` tokens and `confined_token`.

noesis becomes a resource server: `mcp_server.py` takes `AuthSettings` with
`resource_server_url` and a JWT `TokenVerifier` against auth's JWKS;
`server.caller`/`anyone`/`filer` check scopes (`noesis:api`,
`noesis:import`) where `API_CLIENTS` and `may_import` were; an application
that keeps libraries sends a `client_credentials` JWT instead of HTTP Basic
(`members.keeper_for_basic`); `/me` keeps only noesis's fields; `web/` signs
in at auth as an ordinary public client. **What breaks:** every client
re-pointed at once, by the cut-over the design orders; `oauth.json` and the
identity tables are carried to auth by the migration script, then dropped.

**Built 2026-11-08, not deployed:** noesis's branch `auth-resource-server`
(`bearer.py`; `scripts/migrate_to_auth.py`, run after auth's
`migrate_from_noesis.py` and before this noesis serves), and auth itself in
`~/src/dianoia-auth`. Left: the cut-over, which needs auth's hostname, mail and
secrets on `commons`, noesis's own client at auth (`NOESIS_AUTH_CLIENT_ID`,
`NOESIS_AUTH_CLIENT_SECRET`, `--credentials thefloor:members`), and The Floor
able to check noesis's token when asked who belongs.
