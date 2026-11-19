# A library is indexed after every change that changes its index

2026-11-18, from Rodrigo's call with Erta on 2026-11-16: until then only
`ts nightly-index` indexed a library, so a document just imported could not
be found by `lookup_term` or `list_documents` until the next night. Now any
write or run that touches a chat, a document or `KEYS.md`
(`library.changes_index`) is followed by an index in the background
(`server._index`). Changes made while that index waits for the lock are
folded into one more index. A new file the index leaves out, such as a
source, does not start one.

Night-time had been caution about an index running while something else
writes the library. The code showed that writers were already safe, since
API writes got 409 during a run. The readers were not: the MCP tools read
the index without a lock, and `index` wrote its state non-atomically, so a
reader could find it half-written and read it as empty. Index files are now
written whole or not at all (`library._write`). `PUT` used to check the lock
and then await the body, so a run could start between the two; every write
now holds the lock while it writes (`_writing`).

**A run or write waits for the background index rather than getting 409**
(`_claim`). The Floor treats 409 as `busy` and does not retry, and its
segments arrive in bursts, so an index holding the lock after one import
would have refused the next. A run still refuses another run.

**A new library is not indexed when it is made**, though the task first
asked for that. The MCP tools find a library by its directory, and an
indexed empty library answered exactly as an unindexed one did. Instead
`list_documents` says when a library has no chats or documents, and lists
the chats and documents the index does not yet hold, marked *not yet
indexed*, since `read_file` reads them already.

What the background index is refused (no allowance, no free slot) or fails at
is logged to the server's stderr and left for `ts nightly-index`, which stays.
