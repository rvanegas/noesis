# An application keeps libraries for its groups

Agreed at The Floor's prompt on 2026-11-07, for a library per channel: its
transcripts go in by themselves, its members import sources, and every member
reaches it and nobody else. The Floor's side is its task
`a-channel-has-its-own-noesis-library.md`; this is noesis's.

## The application owns, and alone says who belongs

A channel's library is `thefloor/<handle>`: the application is the owner, as
a person is the owner of `<user>/<library>`, and the handle — a slug of the
channel's name and a random suffix, minted by The Floor — is the library's
name. **noesis asks The Floor who belongs rather than being told**: pushing
each change is the shape The Floor's 2026-11-03 decision rejected for names,
where a lost or replayed call leaves two ends disagreeing, and here the
disagreement would be about who may read. Answers are kept a minute, so
leaving closes the library within one with nothing sent. An application that
does not answer admits nobody (503) and lists nothing.

## How (`noesis/members.py`)

- **The operator marks the client** with the URL it answers at
  (`scripts/client_libraries.py`), which makes `libraries/<client id>/` and so
  takes the name in the register: no person can sign up as `thefloor`.
- **Two questions, asked with the client's own id and secret as HTTP Basic**:
  `GET <url>/noesis/libraries/<name>` — the group's name, and its members by
  user name, each with whether they pay and the name they go by in its
  transcripts — and `GET <url>/noesis/users/<user>/libraries`.
- **The application signs in with the same pair** and is then the owner: it
  makes the library (`POST /libraries`) and files into it.
- **A member reaches it as their own**, through every way in (`library_root`):
  files, runs, imports, MCP. Guests are never members; The Floor leaves them
  out of its answer.
- **Listed by the group's name.** `/libraries` and `/me` carry `names`, id →
  the group's current name, since the handle is only an id and survives the
  channel's renames; the web client lists the id, and heads a chosen
  library with its group's name. A group without one, a channel nobody
  named, is shown by who else is in it, "With Ann and Bob" (since
  2026-11-09). Since 2026-11-11 `/libraries` gives each
  library as `{id, name, users, documents}` instead, and the web client
  chooses among them in a view that shows all four.

## Claude consults one library, by a token confined to it

The Floor's *Ask Claude* consults a channel's library through `/mcp`, with a
token Anthropic's servers carry. `POST /applications/token` (the
application's pair) issues one for an hour, scoped `library:<owner>/<name>`,
no refresh: `/mcp` opens that one library and no other of the owner's, and
the file and run API refuses it. The owner has no account, so its tokens last
while the mark does.

## Who pays

The Floor's *Pro*, divided among a channel's Pro members — and noesis has no
payment at all, only free and unlimited accounts. So **the application pays
and divides**: a group's library is metered as itself, `<owner>/<library>`,
which has no account and so is uncapped, and `GET /applications/spending`
tells the application what each spent in a month. A group nobody in pays for
is refused whatever would spend (402); reading goes on.

## Voice

*Replaced on 2026-11-09 by `2026-11-09-a-channel-s-voices-are-its-members.md`:
each member is their own voice.*

Every member's lines are the library's own voice — the name The Floor gives
each, and the names each keeps here — and anybody else's (Claude's, a
guest's) context.

## The hours of a segment

Separately, and for every library: The Floor's text of a segment imports with
its hours on the line under the date (`*2:21 PM–4:09 PM*`). Two segments of
one day were told apart by nothing else, the title being a model's. A segment
imported before this one is not recognised on import again, its text having
changed, and would be filed a second time under a new title.
