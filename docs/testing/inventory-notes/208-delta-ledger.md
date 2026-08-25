---
inventory-delta:
  tests/: +74
---

# The inventory count becomes a sum of deltas (#208)

Seventy-four root-suite node IDs, all in `tests/test_check_suite_inventory.py`,
covering the ledger this change introduces and the gate script it replaces. No
other suite moves — the change is entirely in `scripts/` and `docs/`.

Seventy-four is a lot for one file, so it is worth saying what they are, because
they are not seventy-four tests of one thing. Sixty-two landed with the
implementation; **twelve more came from review**, one per finding plus the cases
they implied. Roughly a third pin the design; the rest exist because `scripts/`
is inside the diff-coverage gate since #257, and the rewrite left most of this
file's behaviour unexercised. Measured before and after: **51% → 99%** line
coverage of `check-suite-inventory.py`, the single remaining miss being the
`if __name__ == "__main__"` guard.

- **11** pin #208's actual acceptance criteria — that two changes write
  different paths and their deltas sum (`TestNoSharedWrite`, 4), that the
  tripwire still fires (`TestTripwireIntact`, 4), and that folding deltas into
  the baseline is arithmetically invisible and edits no note (`TestCompaction`,
  3). Nothing else in the repository checks that two PRs can both add tests
  without colliding, which is the whole reason the issue was reopened.
- **10** drive `main` end to end with collection stubbed (`TestDriver`),
  including the two exit codes that matter most: drift is 1, and a suite that
  *failed to collect* is still 1 even under `--update`. Papering over a broken
  suite by recording it as the new truth is the one way this gate could be
  turned into its own opposite.
- **9** cover writing a delta — that prose and unrelated front matter survive a
  rewrite, that what `--update` writes is what the checker parses back, and
  that further drift accumulates onto a delta already recorded rather than
  replacing or double-counting it (`TestWritingADelta` 5, `TestRecordDelta` 5,
  less one counted above).
- **9** make an unreadable delta raise rather than read as zero
  (`TestUnreadableDeltaRaises`, 4), and confirm that notes with no front matter
  — every note written before this change, plus the directory's own `README.md`
  — contribute nothing (`TestNotesWithoutDeltas`, 3), with hand-written spacing
  and neighbouring front-matter keys tolerated (`TestFrontMatterTolerance`, 2).
  This is the failure mode the design introduces: the number is derived now, so
  a malformed block that silently contributed zero would be a quiet wrong
  answer of exactly the kind this gate exists to catch.
- **5** cover `collect` itself (`TestCollectParsing`) — that the *last* summary
  line wins, that a non-zero exit raises instead of returning a plausible
  count, and both invocation traps: `PYTHONPATH` is prepended rather than
  clobbered, and bare-python suites never shell out to `uv`.
- **5** cover baseline corruption (`TestBaselineErrors`), including a count of
  `true`, which is an `int` in Python and would otherwise pass a naive check.
- **4** cover deriving a note name from the branch (`TestDefaultNoteSlug`),
  where every failure — detached HEAD, git error, no git at all — must yield
  nothing rather than a guess, since a wrong name is a shared path again.
- **3** keep drift and collection failure apart in `run_checks`, **3** guard
  that the inventory and its notes directory still agree, and **2** cover
  rendering.

One test changed meaning while being written, which is worth recording. It was
first asserted that re-running `--update` after a base move leaves the delta
alone, and it failed: the code accumulated 6 into 12. The code was right. Drift
is measured against an expected that *already contains this note's own delta*,
so any reported gap is new movement, and adding it is correct. If nothing new
were added there would be no drift at all, and `--update` returns at "ok"
without touching the file — which is the property that actually makes it safe
to re-run, and is now asserted directly.

**Twelve from review.** Codex raised seven findings and all seven were real,
which is worth recording because they share a shape: every one was a way this
gate could report success while gating nothing.

- Two branches whose names *sanitise* alike (`feature/foo`, `feature-foo`,
  `Feature_Foo`) wrote the same note — recreating the exact conflict this change
  removes. Names now carry a digest of the exact branch string.
- A recipe with no baseline count was silently dropped from the check, and
  `--suite <that-one>` reported success having collected nothing. Both
  directions of the recipe/baseline correspondence are now required.
- The rewritten `SUITE-INVENTORY.md` still claimed every table row is
  collected, but removing the count parsing removed the only thing reading that
  table. A documented claim nothing checks is precisely what this repository
  exists to prevent, and it does not get an exemption for being in this
  document. The table is parsed again — for identities, not counts.
- `inventory-delta:` with nothing under it, or an entry accidentally written at
  the top level, both read as "no delta" instead of raising.
- `--note feature/foo` wrote a nested file `note_files()` never scans;
  `..` escaped the directory.
- A note already folded by `--compact` could be updated forever without the
  ledger moving — a trap with no exit.

One finding did not change the code but changed what is claimed: node-ID counts
are **not** additive when two changes interact, as when two branches each append
to a different parametrize list feeding one Cartesian product. The base-move
invariance is real for independent changes and is now stated that way, in all
three places it was overstated. The design's answer is that the failure is loud
— the sum stops matching collection and you get ordinary drift — and there is a
test pinning exactly that.

This note is itself the first use of the mechanism: the `+74` above was written
by `check-suite-inventory.py --update`, not by hand.
