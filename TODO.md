# TODO

- Related and References just show additions

- Progress report

- versioning

- list names before predicates, enforce ranges to split alphabet, limit number of each to keep args small

- repeat if run out of letters

- latex formalization

## After SERVER.md (noted 2026-10-27)

- validate asks the server: it still reads the Mac's local .noesis/ index state to resolve Related titles, which no longer updates; then delete the Mac's .noesis/ (sync.json moves elsewhere or stays alone)

- carry moves through sync: a move (noesis fix into the year directory) syncs as delete + create, and the server summarizes the file again; detect moves by hash, or add a move endpoint that calls library.move_documents

- faster deploys: install dependencies in their own Dockerfile layer before copying noesis/, so a code change does not reinstall them

- broken links in rodvandur/philosophy: 2026-07-09-responsible-models.chat.md (schulte.pdf) and 2026-07-09-theory-of-desire.chat.md link deleted PDFs; 2026-03-26-amelioration-without-redefinition.chat.md links CappelenConceptualEngineering.pdf and concepteng.pdf, gone; 2026-03-24-verbal-disputes.chat.md links 2025-05-19-money-and-marriage-by-authoritative-assertion.txt, which never existed (the .md document?); 2026-06-16-all-together-now.chat.md line 665 holds the system prompt's reference template as a reference

- API for clients other than the CLI (SERVER.md, Phase 2, Later): structured endpoints (create a session, list documents, reply with a JSON result) by having cmd_* return results and stream through on_delta, which retires the /run subprocess; wait for a client that needs it (The Floor)

- POST /libraries/{user}/{library} to create a library, with the first client that needs it

- manual tests for noesis import (SERVER.md, Phase 4; the tests use fixtures written from the formats as documented, not real files): run `noesis import` on a real claude.ai data export (Settings → Privacy → Export data; the zip, then `--only` one conversation) and on a real saveai.net Claude export; check turns, the branch kept for edited messages, attachments, and that each imported chat passes `noesis check`; then `noesis reply` to one imported chat. If either format differs from tests/fixtures/, re-record the fixture from the real file and adjust cmd_import.py

## After Phase 6 (noted 2026-11-01)

- account deletion: a person removes their own account, libraries and grants (open sign-up holds strangers' email addresses); today only the operator disables one

- The Floor as an OAuth client of noesis (its client: `scripts/add_client.py`, 2026-11-01; The Floor's side on its own branch): a "Connect noesis" step, its refresh token per person on The Floor's server, the access token passed to Claude through the API's MCP connector; replaces The Floor's one NOESIS_TOKEN (rvanegas-site, Calls between projects)

- a paid or bring-your-own-key plan, if a free allowance proves too small for anyone but the operator
