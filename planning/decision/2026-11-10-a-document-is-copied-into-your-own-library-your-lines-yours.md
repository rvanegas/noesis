# A document is copied into your own library, your lines yours

Decided at the prompt on 2026-11-10 and built the same day. The Floor is
retiring *Send to noesis*, which filed a segment's text in a person's own
library, because a channel's transcripts are already filed in the channel's
library (`2026-11-07-an-application-keeps-libraries-for-its-groups.md`) and
the two read as one action offered twice. A member who wants their own copy
now makes it here: **`POST /libraries/{user}/{library}/copy`**, `{file, to}`,
and *Copy to your library* on a chat's or document's view in the web client.

## How it copies

By import, of the source file's bytes under its own name, into `to`, a library
of the caller's own: it is staged, checked and repaired as any import is, a
noesis chat keeps its title and date, and a title the target already has is
refused rather than renamed. Only a chat or a document, and only by a person:
neither a service nor an application copies into a library of its own. The
target is indexed when anything is, as an import is.

## Voices

A chat in a person's library is read by its owner's names
(`accounts.speaker_names`); in a channel's, each member is their own voice
(`2026-11-09-a-channel-s-voices-are-its-members.md`). A copy moves a chat from
the second reading to the first, so the copier's own lines have to be among
their names, or the copy reads them as somebody else's. So:

- **The heading the copier goes by in the source is added to their names**:
  in a group's library, the name the application gives them
  (`members.speakers`). This is the step *Send to noesis* did with the Floor
  display name, now done by the side that knows the group.
- **When no heading of the chat is the copier's by either, it asks** (409,
  `detail.speakers`, every speaker but Prompt and the models) instead of
  copying: a member renamed since the transcript, or somebody copying a chat
  they were not in. The answer comes back as `names`, which must each be a
  heading in the chat, never a near match; `[]` copies with no name taken.

## Not done

A document's assets are not copied with it: the chats this exists for, The
Floor's transcripts, have none. A copy does not follow its source as the
channel's library grows a segment; it is a copy, made again by hand.
