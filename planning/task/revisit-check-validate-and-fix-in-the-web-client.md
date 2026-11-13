# Revisit check, validate and fix in the web client

Noted 2026-11-13.

A file's view offers three buttons, Check, Validate and Fix
(`noesis/web/index.html`; shown by `app.js`, Check on a `.chat.md` alone,
Validate alone on `KEYS.md`), running the CLI's commands of those names; Fix
previews, then applies with `--yes`. Revisit the three actions and their
buttons together: what each one is for to someone in the web client, whether
the CLI's distinction between them is worth exposing there, where they appear,
and what they are called.
