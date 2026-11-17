# A transcript's file name carries its time of day

Rodrigo, 2026-11-16. With more than one document on a day, the file listing
loses their order: it shows only date and title, so they sort by title, and
the times are inside each file. Before transcripts there was one a day and the
order did not matter, which is why the timestamp was never added. **Proposed:
a document imported by hand keeps the date alone; one that comes in as a
transcript (from The Floor) gets the hour and minute it began too**, so some
names carry one more number than others. That is a little strange, and is the
price of not renaming everything.

**What it touches**: the title is recovered from the name by stripping the
date, and now optionally the time, and taking what follows; which is why a
title may not begin with a numeral. The time's format has to keep that
unambiguous. `form.py`'s filename derivation and `library.role_of` are where
the rule lives; The Floor's segment titles
(`thefloor` task *A segment has one title wherever it is shown*) depend on it.
