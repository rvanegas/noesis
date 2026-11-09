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

## Inferences have stances too

Added later on 2026-11-09, at the prompt. A step with justifiers is also an
inference, and a member may accept that a conclusion follows while rejecting
a premise, or deny that it follows while accepting every proposition in it.
Roxana keeps stances on each argument as it does on each proposition. So a
line also says who accepts and who rejects its inference
(`inference accepted:`, `inference rejected:`, only with `from:`, nobody on
both sides of a pair), dianoia returns them
(`inference_accepted`, `inference_rejected`), and `export` sends them as each
argument's `accepted` and `rejected`. Stances count in an export's digest
only where there are any, so an argument recorded before keeps its digest.

The web client follows: *Extract argument* is offered on a chat as well as a
document, until the stem has its argument, and *Send to Roxana* on the
`.argument.md` alone, where the stances can be read before they go.

## A person's own library records its owner's stances

Added later on 2026-11-09, at the prompt. In a person's library the one
participant is its owner, so an argument from their chat says what they
asserted, granted or disputed, and their goal in Roxana is what they
justify, not whatever the last proposition is, which Claude may have drawn.
The server names the owner to a run in `NOESIS_OWNER`, by the display name
auth keeps (`members.display_name`, asked with noesis's own token, the user
name if auth does not answer); on the Mac without the server, `roxana_user`
stands in. Before extraction their chat headings (`## Prompt`, their names)
become that name, and a document of theirs is said to be theirs. **Claude is
nobody's stance**: its turns stay `## Claude`, and dianoia is never given it
as a participant, since it has no account in Roxana and its lines are
context, not a position anybody holds.

## A proposition never names a participant

Found on 2026-11-09 in Roxana discussions 5e48 and d4r4: extracted steps such
as "Rodrigo holds that P", then, once that was forbidden, "Rodrigo's standard
would permit Q" and "Rodrigo himself judged R". Both people accept such
reports, so the stances fell on the attribution and the disagreement
vanished. dianoia's prompt now forbids naming a participant in a proposition
(its decision says how a standard and an argument from someone's own
practice are written instead), the editing prompt says the same, and
`argue` and `export` warn of any proposition that still names one
(`argue.naming`), sending it all the same, since the person may mean it.
