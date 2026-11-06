# An API for clients other than the CLI

Noted 2026-10-27, after `decision/archive/SERVER.md`.

`decision/archive/SERVER.md`, Phase 2, *Later*: structured endpoints (create a session, list
documents, reply with a JSON result) by having `cmd_*` return results and
stream through `on_delta`, which retires the `/run` subprocess. Wait for a
client that needs it (The Floor).
