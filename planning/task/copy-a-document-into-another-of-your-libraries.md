# Copy a document into another of your libraries

Noted 2026-11-10, for The Floor, which is retiring its *Send to noesis* in
favour of this (thefloor, `planning/task/noesis-is-pro-s-and-send-to-noesis-goes.md`).

A reader of a document in a library they can open but do not own — a Floor
channel's library, `thefloor/<handle>`, above all — copies it into one of
their own, from the web client's view of the file. Rodrigo: it has to
**handle voices correctly**.

## Voices

A chat of several speakers is read after a `Voices:` line naming which
headings are the *owner's*, by the owner's names (`_voiced`). In a channel's
library nobody is the owner, so every speaker is context; copied into a
person's library, their own lines have to become their thoughts and nobody
else's. So the copy:

- **Recognises the copier by their names**, as `_voiced` already would once
  the file is theirs, and their display name at auth, which since 2026-11-09
  is the one The Floor shows on their lines.
- **Asks which speaker is them when none matches** — one or several, or none
  ("I was not in this one") — and adds what they choose to their names
  (`PUT /me/names`'s effect), so the next copy needs no asking. This is the
  step *Send to noesis* did silently with the Floor display name.
- Never takes somebody else's heading as theirs because it is close: a
  person's names are theirs alone, and two people in one room may share a
  first name.

## Open

- Whether the copy is indexed like an import (it should be, since that is the
  point of having it) and under what name, given names are unique across a
  library: the source's, with a collision refused or suffixed.
- A source document's assets come with it.
- Whether the channel library, as it grows a segment, is ever followed by the
  copy. Recommended: no; a copy is a copy, made again by hand.
