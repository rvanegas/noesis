# A channel's voices are its members

Decided at the prompt on 2026-11-09 and built the same day. A channel's
chat has several people in it, and each is a member speaking for
themselves, not one user under several names. This replaces *Voice* in
`2026-11-07-an-application-keeps-libraries-for-its-groups.md`, which counted
every member's lines as the library's single voice: when Ann read a channel's
chat through claude.ai, Bob's words came to her labelled as her own.

## Members are named by display name

A member is named by the display name The Floor gives them, the `name` in
its `/noesis/libraries/:handle` answer, or by their user name when it gives
none. Their headings are that name plus the names they keep here
(`members.speakers`). Display names are to be stored at auth.rvanegas.co
and sent from there to noesis and Roxana: those are tasks in other projects
(dianoia-auth's `display-names-are-stored-here.md`, The Floor's
`display-names-are-auth-s.md`, Roxana's `toggles-show-display-names.md`).
noesis already reads the name The Floor shows, so nothing here waits on them.

## Nobody in a channel is the library's voice

- **Over MCP the reader is the user** (`mcp_server._heard`). The reader's
  headings are the user. Every other member's are "another member of the
  channel, speaking for themselves". `guide` says the same. With The Floor's
  confined token, nobody there is the user.
- **A run has no reader**, so it names each member: `NOESIS_MEMBERS` (JSON),
  the index's `[VOICE: member — <name>]`, and `NOESIS_USER_NAMES` empty.

## A channel's document is Claude's account

A channel's `.document.md` is written in Claude's voice about what each
member thinks, naming them. It is not the members' joint writing, and no
member speaks in it. The writing assistant (`edit_tools._CHANNEL_DOCUMENT`),
`reply`'s system prompt (`channel_note`: the latest speaker is the one
asking), the index label and `review` (`CHANNEL_REVIEW_NOTE`) all treat it
that way.

## One argument, with every member's stances

- **`argue` extracts from a document or a chat.** The chat is where the
  stances are stated, and until now argue read only documents.
- **Stances in `.argument.md`**:
  `- 3 (from: 1, 2; accepted: Ann; rejected: Bob): …`. They are optional, so
  existing files stay valid and need no migration. A name containing a comma,
  semicolon or parenthesis cannot stand in a list and is left out.
- **dianoia is given `participants`** and returns `accepted` and `rejected`
  for each step (dianoia's `extraction-returns-each-participant-s-stances.md`).
  noesis keeps only names that are members. Until dianoia returns stances,
  extraction works as it did and the lists are empty.

## Each member has their own goal

`export` fills Roxana's `accepted`, `rejected` and `goal` with members' user
names, which Roxana matches against whoever is signed in. A member's goal is
what they are justifying: the last proposition with justifiers that they
accept, one that none of their others justifies. A member who justifies
nothing takes the goal of the first member whose justification they reject,
meaning that goal or anything it rests on (`cmd_export.member_goals`). Only
if no member has a goal is the conclusion the sender's, as before.
