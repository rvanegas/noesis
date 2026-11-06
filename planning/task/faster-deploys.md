# Faster deploys

Noted 2026-10-27, after `decision/archive/SERVER.md`.

Install dependencies in their own Dockerfile layer before copying
`noesis/`, so a code change does not reinstall them.
