# Manual tests for noesis import

Noted 2026-10-27 (`decision/archive/SERVER.md`, Phase 4). The tests use fixtures written from the
formats as documented, not real files.

Run `noesis import` on a real claude.ai data export (Settings → Privacy →
Export data; the zip, then `--only` one conversation) and on a real saveai.net
Claude export. Check turns, the branch kept for edited messages, attachments,
and that each imported chat passes `noesis check`; then `noesis reply` to one
imported chat. If either format differs from `tests/fixtures/`, re-record the
fixture from the real file and adjust `cmd_import.py`.
