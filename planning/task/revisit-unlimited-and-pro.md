# Revisit unlimited and Pro

Noted 2026-11-10. Four designations say what somebody may do, in two
projects, and nothing joins them: noesis's plan, `free` or `unlimited`
(`accounts.plan_of`), set by hand with `scripts/accounts.py plan`; and The
Floor's Pro, bought in the app or marked by hand (`transcripts_unlimited`,
Pro too since 2026-11-10, The Floor's `isPro`). noesis learns of Pro only as
a channel member's `pro`, which says who pays for a channel's library
(`members.py`), never as a person's own standing.

What it cost on 2026-11-10: Liliana, made `unlimited` here by hand, was
refused Extract argument in her channel's library, since only The Floor's
`pro` counted there; `server._paying` now takes a plan set on the account as
paying too. Asked to make her "Pro" meant noesis's `unlimited`, and setting
The Floor's mark first was the wrong thing done.

Decided then, not built: **Pro at The Floor, bought or marked, should make
somebody `unlimited` at noesis.** The likely shape is noesis asking, as it
asks who belongs (`members.py`): a route of The Floor's, say `GET
/noesis/users/<user>` answering `pro`, kept a minute, failing to the plan
kept here; recorded among the calls between services. Open:

- Whether the reverse holds: does `unlimited` here make anybody Pro at The
  Floor, or is noesis's plan only noesis's?
- Whether one word should name both, and which project owns it, rather than
  each keeping its own and copying.
- What paying means in a channel's library once the two are joined: funding
  (`Group.funded`) still counts only The Floor's `pro`, so a channel whose
  only member is `unlimited` here may act and not spend.
- `plan_of` making every holder of a minted token `unlimited`, which is why
  `_paying` reads the account's own row instead.

The Floor's side is its `planning/task/revisit-unlimited-and-pro.md`.
