# Deleting an account reaches every project

Found 2026-11-09, preparing The Floor's 1.14.0 for App Review. Since sign-in
moved to dianoia-auth (`auth.rvanegas.co`), one person has one account there
and a part in each project: The Floor's account, a noesis library (connected
at The Floor's sign-in from build 422), Roxana's discussions. **Deleting an
account in The Floor deletes The Floor's alone** (Guideline 5.1.1(v) asks
that much, and it does); the account at dianoia-auth and the noesis library
stay. The Floor's privacy policy says deletion removes "your address … and
every sign-in", which is now true of The Floor's copy only.

Beside `account-deletion.md`, which asks for a person to remove their own
noesis account, libraries and grants, and predates the move: the account it
means is now dianoia-auth's, and its libraries and plan are noesis's.

Two ways, to be chosen:

- **The Floor's deletion reaches dianoia-auth**: a call from The Floor's
  server, as the person, that deletes the account there and asks each
  project to delete what it holds for that user (noesis its libraries, plan
  and spend; Roxana nothing owned, its discussions having no owner). One
  tap ends every project's access, which is what somebody deleting usually
  means and what they may not expect from The Floor's button.
- **Each place deletes its own, and says so**: `/account` at dianoia-auth
  gains *Delete my account*, which reaches the projects as above, and The
  Floor's deletion screen and privacy policy say plainly that the account at
  auth.rvanegas.co is separate and where to delete it.

Either way dianoia-auth needs the deletion itself (accounts, reservations,
refresh tokens, sessions, consents; the user name held afterwards, so it is
never given to somebody else) and a call each project answers. Until then
the policy's sentence wants narrowing.
