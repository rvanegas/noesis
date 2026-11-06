# Carry moves through sync

Noted 2026-10-27, after `decision/archive/SERVER.md`.

A move (`noesis fix` into the year directory) syncs as delete + create, and
the server summarizes the file again. Detect moves by hash, or add a move
endpoint that calls `library.move_documents`.
