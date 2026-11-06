# validate asks the server

Noted 2026-10-27, after `decision/archive/SERVER.md`.

`validate` still reads the Mac's local `.noesis/` index state to resolve
Related titles, which no longer updates. Then delete the Mac's `.noesis/`
(`sync.json` moves elsewhere or stays alone).
