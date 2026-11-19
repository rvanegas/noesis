# Index a library after every import, and before the first

Rodrigo, on a call with Erta, 2026-11-16. A library is indexed only by
`ts nightly-index`, so documents just imported look as though they cannot be
reached at all, and a new library asked about before then says it cannot find
the library. Night-time was caution: an index running while something else
writes the library might go wrong. Since 2026-11-18, revised after reading the
code: **index after every change that would change the index** (an import, a
replace, a delete, a run that rewrites a chat, an edit of `KEYS.md`; not a new
file of a role the index leaves out), with these safeguards first:

- **Readers, not writers, are what daytime indexing endangers.** API writes
  already get 409 during a run (`_writable`); MCP reads take no lock, and
  `index` writes its state with plain `write_text`, which a reader can catch
  half-written and the loaders read as empty ("No documents found."). Write
  every index file atomically, as `PUT` does.
- **Close `PUT`'s race**: it checks the lock, then awaits the body, so a run
  can start between the two. A write holds the lock while it writes.
- **An index must not refuse imports.** The Floor treats 409 as `busy` and
  does not retry, and segments arrive in bursts. The index runs in the
  background once the change's lock is let go, changes meanwhile folded into
  one more, and a run or write that finds it waits for it rather than 409.
  Its failure (402, a slug clash) fails nothing else; the nightly index stays
  to catch it.
- **Indexing an empty library changes nothing**: the MCP tools find a library
  by its directory, and say "No documents found." indexed or not. Instead
  `list_documents` says a library is empty when it is, and lists chats and
  documents not yet indexed, by name and title, which `read_file` already
  reads.
