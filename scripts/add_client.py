#!/usr/bin/env python3
"""Register an application as an OAuth client of noesis, with its one redirect.

An operator task (SERVER.md, Phase 6). Self-registration is open only to
claude.ai's callbacks and to localhost (oauth.allowed_redirect); an
application whose server is its own, The Floor first, is registered here
instead, as a confidential client whose only redirect is its own callback.
Its client id and secret are printed once, as `KEY=value` lines, for the
application's own configuration; oauth.json keeps them as it keeps a
self-registered client's. Its tokens reach /mcp and /me, not the file and run
API (oauth.API_CLIENTS).

    docker compose run --rm -T noesis python scripts/add_client.py thefloor \\
        --name "The Floor" --redirect https://thefloor.rvanegas.co/noesis/callback

Registering the same id again replaces it, with a new secret: the old one
stops working, and grants already made stay.
"""

from __future__ import annotations

import argparse
import re
import secrets
import time
from urllib.parse import urlparse

from mcp.shared.auth import OAuthClientInformationFull

from noesis.oauth import WEB_CLIENT_ID, provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client_id", help="lowercase letters, digits and -")
    parser.add_argument("--name", required=True, help="what the sign-in page calls it")
    parser.add_argument("--redirect", required=True, help="its one callback, https")
    parser.add_argument("--prefix", default="NOESIS", help="the printed lines' prefix: <PREFIX>_CLIENT_ID")
    args = parser.parse_args(argv)
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", args.client_id) or args.client_id == WEB_CLIENT_ID:
        raise SystemExit(f"✗ not a client id: {args.client_id!r}")
    redirect = urlparse(args.redirect)
    if redirect.scheme != "https" or not redirect.hostname:
        raise SystemExit(f"✗ the redirect must be an https URL: {args.redirect!r}")
    secret = secrets.token_urlsafe(32)
    client = OAuthClientInformationFull(
        client_id=args.client_id,
        client_secret=secret,
        client_id_issued_at=int(time.time()),
        client_name=args.name,
        redirect_uris=[args.redirect],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )
    data = provider._load()
    data["clients"][args.client_id] = client.model_dump(mode="json")
    provider._save(data)
    print(f"{args.prefix}_CLIENT_ID={args.client_id}")
    print(f"{args.prefix}_CLIENT_SECRET={secret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
