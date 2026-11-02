#!/usr/bin/env python3
"""Mark a registered application as one that files conversations, or unmark it.

An operator task (oauth.py, *An application that files conversations*). A
client so marked may ask for the `import` scope; a token carrying it reaches
`POST …/import` and `PUT /me/names` besides /mcp and /me. The mark is the
operator's alone: what a client says of itself at registration is not
consulted. Unmarking stops every such token at once, without revoking the
reading the grant also gives; the secret is untouched, so this, unlike
add_client.py, disconnects nobody.

    docker compose run --rm -T noesis python scripts/client_imports.py thefloor
    docker compose run --rm -T noesis python scripts/client_imports.py thefloor --off
"""

from __future__ import annotations

import argparse

from noesis.oauth import IMPORT_SCOPE, provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client_id")
    parser.add_argument("--off", action="store_true", help="unmark it")
    args = parser.parse_args(argv)
    data = provider._load()
    raw = data["clients"].get(args.client_id)
    if raw is None:
        raise SystemExit(f"✗ no registered client {args.client_id!r}")
    if raw.get("identity_only"):
        raise SystemExit(f"✗ {args.client_id!r} only signs people in")
    if raw.get("token_endpoint_auth_method") == "none":
        raise SystemExit(f"✗ {args.client_id!r} has no secret")
    if args.off:
        raw.pop("imports", None)
        raw["scope"] = None
    else:
        # The SDK's /authorize takes a scope only where the client names it.
        raw["imports"], raw["scope"] = True, IMPORT_SCOPE
    provider._save(data)
    print(f"{args.client_id}: {'files conversations' if not args.off else 'reads only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
