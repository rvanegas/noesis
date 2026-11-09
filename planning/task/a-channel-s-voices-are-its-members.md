# A channel's voices are its members

Decided 2026-11-09. A channel's chat has several people in it, and each is a
member speaking for themselves, not one user under several names. This
replaces *Voice* in
`2026-11-07-an-application-keeps-libraries-for-its-groups.md`, which counts
every member's lines as the library's single voice. Move this reasoning there
once it ships.

## Display names are auth's

A person's display name is stored at auth.rvanegas.co and sent from there to
noesis and Roxana. The Floor's display name is that name, and every place a
member is named uses it: the `Voices:` line, documents, argument stances, and
the people on Roxana's accept and reject toggles, which show user names now.
This changes auth (`~/src/dianoia-auth`), Roxana and The Floor too, and the
names they pass to each other go through technosophia's `SERVICES.md`.
noesis's own speaker names (`accounts.speaker_names`) still say which chat
headings are a person. The display name is how noesis refers to them.

## Reading a channel's chat

- **`Voices:`** (`mcp_server._voiced`): the reader's headings are the user,
  every other member is named as one, e.g. `## Ana and ## Ben are other
  members of the channel`, and a model is a model. The reader is `_caller()`.
- **`guide`** says the same about the open channel library.
- **The index** (`cmd_index._annotate_voice`) and runs (`NOESIS_USER_NAMES`,
  `members.voices`) label each member by name, never as `user`, since a run
  in a channel has no single reader.

## Documents

In a channel library, a `.document.md` is written in Claude's voice about
what each member thinks, naming them: "Ana holds that…, Ben objects that…".
It is not the members' joint writing, and no member speaks in it. The writing
assistant's instructions (`edit_tools`) say so in a channel: a member's
request changes the account, but the document does not become theirs. The
index labels such a document as Claude's account of the members' thoughts
rather than "the user's own writing", and `review` reads it the same way.

## Arguments

- **From a document or a chat.** `noesis argue` reads a `.document.md` only.
  It also takes a `.chat.md`, where the stances are stated, and writes the
  stem's `.argument.md` either way.
- **One argument that every voice took part in.** Extraction returns the
  members who accept each proposition and the members who reject it. dianoia's
  `/argument/extract` returns `Step`s with no stances, so it learns the
  members' names and returns stances: a contract change between services.
- **`.argument.md` carries them**, e.g.
  `- 3 (from: 1, 2; accepted: Ana, Ben; rejected: Cy): …`, which `argue`'s
  parser, `check_argument`, the numbering check and the `edit_tools` prompt
  (now "the user writes the propositions") learn. Stances are optional, so
  existing files stay valid and need no migration.
- **Export fills Roxana's lists** (`cmd_export._layout_entry`), `accepted` and
  `rejected` from the stances, where they are sent empty now.

## Goals

Each member has their own goal. It is the proposition the member is
justifying. A member who justifies nothing takes the goal of the member whose
justification they reject. Today the conclusion is the run's caller's goal
alone (`NOESIS_CALLER`).
