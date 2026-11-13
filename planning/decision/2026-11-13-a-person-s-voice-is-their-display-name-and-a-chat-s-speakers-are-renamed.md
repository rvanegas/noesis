# A person's voice is their display name, and a chat's speakers are renamed

2026-11-13. Until today noesis kept, per person, the chat headings besides
`Prompt` that were their own voice: set in the web client's *Your names*, by
The Floor's *Send to noesis*, and by a copy, which added the heading the
copier went by. Since display names moved to auth (2026-11-09), the name a
person speaks under at The Floor is their display name, so the list mostly
repeated a name noesis can already ask auth for. A person's voice is now
`Prompt` and their display name alone (`members.voices`), and the list is
gone: the table, `PUT /me/names`, *Your names*, `scripts/accounts.py names`.

What that leaves to put right is the chat, not the person: one in which they
spoke under another heading, or a guest whose name came out wrong. A chat's
*Speakers* action (`GET`/`POST …/voices`) offers each of its speakers to
rename, to the person themselves, to a name spoken under in the library's
latest chats, or to another; the lines under each are kept. A copy renames
the speaker the copier was to their display name, in the copy alone, where
it added to their names before (it changes
`2026-11-10-a-document-is-copied-into-your-own-library-your-lines-yours.md`).

Paid for it: a person who renames themselves at auth finds their older chats
under the old name read as somebody else's until they rename them, since
noesis is not told of renames; and the names kept until today were moved
once, by `scripts/migrate_names.py`, into the headings of each person's own
chats.
