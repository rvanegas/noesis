# Deleting an account reaches every project

Decided 2026-11-09, closing the tasks *Deleting an account reaches every
project* and *Account deletion*. Since sign-in moved to dianoia-auth, one
person has one account there and a part in each project. Deleting in The
Floor deleted The Floor's alone.

**Each place deletes its own, and says so.** auth.rvanegas.co/account has
*Delete my account*. It asks for a sign-in of the last ten minutes and the
user name typed, deletes everything auth keeps for the person (the name then
held for good), and tells each project, `DELETE /users/<user>`, with a token
auth signs as itself (scope `<project>:erase`, never granted to a client).
noesis and The Floor answer; Roxana holds nothing that is anybody's. The
Floor's own *Delete account* still deletes The Floor's alone, and its policy
says the account at auth is separate.

Not chosen: The Floor's button reaching auth. It would have made a podcast
app's button end somebody's noesis library, and given one client the power to
delete identities. It can still be added later as a second way into the same
deletion, offered on The Floor's confirmation.

**One recovery window, thirty days**, at noesis and The Floor alike. A
deletion takes effect at once for everybody; for thirty days the operator can
still undo it by hand, which nothing in a client can. At noesis a deleted
person's libraries move to `deleted/`, and a file deleted through the API to
`trash/`. Both are outside the library, since the index, the name checks and
asset lookup scan the library tree and not all of them skip `.noesis/`
(deletion.py). The Floor's deleted channels and recordings moved from seven
days to thirty to match its transcripts.
