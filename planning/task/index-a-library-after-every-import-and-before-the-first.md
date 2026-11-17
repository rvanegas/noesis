# Index a library after every import, and before the first

Rodrigo, on a call with Erta, 2026-11-16. A library is indexed only by
`ts nightly-index`, so documents just imported look as though they cannot be
reached at all, and a new library asked about before then says it cannot find
the library. The reason for night-time was caution: an index running while
something else writes the library might go wrong. **Add the safeguards that
make it safe to run at any time, then run it after every import** — and once
when a library is made, with nothing in it, so that a question asked of an
empty library finds one. `server.py`'s one run per library (`_locks`) is the
place to start; check what else writes outside it.
