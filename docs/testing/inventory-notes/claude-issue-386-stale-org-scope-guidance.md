---
inventory-delta:
  tests/: +19
---
# claude-issue-386-stale-org-scope-guidance

Nineteen new node IDs, all in `tests/test_check_retired_guidance.py`. Nothing
removed or reparametrised.

## The instruction file outranked the decision that corrected it

`packages/maistro-core/CLAUDE.md` told agents:

    - **No `org_id` in core.** Multi-tenant isolation is Stronghold-only.

ADR-068 superseded that shorthand. Root `CLAUDE.md` decision 7 records the
correction, ADR-019 gained a §"Scope vs. tenancy" section stating it outright,
and the code it governs carries **214** `org_id` references with the column
shipped in the schema. The package file kept directing against all of it.

Proximity is why that matters. An agent working in `packages/maistro-core/`
reads the package instruction file, and it is the more specific of the two — so
the stale bullet won every time, and the root decision that corrected it never
came up.

## It had already propagated

`docs/specs/SPEC-183-oauth2-user-auth-implementation.md:69` carried it into an
acceptance criterion:

    No `org_id` anywhere (ADR-019 CI grep).

There is no such grep, and ADR-019 is the document that records the correction.
That is the shape #386 reports — normative text moving from an instruction file
into criteria that then govern implementation.

**This session produced a third instance while the issue was still open.** The
first draft of PR #425's tests justified "the row has no `org_id`" with
"multi-tenancy belongs to the importing product, never to maistro-core", taken
from the package file. It was corrected before merge, and the PR body says so.
Three propagations from one stale bullet is the argument for a gate rather than
a one-time edit.

## `scripts/check-retired-guidance.py`

The DoD asks CI to detect future normative contradictions. "These two documents
disagree" is not decidable, so the gate does not attempt it. What it checks is
narrower and real: **a statement a decision has declared retired must not still
be written as a directive.**

`quality/retired-guidance.json` is what makes it decidable — each entry names
the retired pattern, the decision that retired it, and the replacement. Adding
an entry is a deliberate act taken when a decision supersedes text living
elsewhere, so the gate never has to infer what "retired" means.

## Recording is not directing

`TestRecordingIsNotDirecting` is the half that keeps the gate honest. Every one
of these says the retired words on purpose:

- root decision 7's own *"(Supersedes the older …)"* clause
- ADR-019's *"The 'no `org_id` in core' shorthand conflated scope with tenancy"*
- SPEC-227's note that the package file's phrasing is stale
- `test_sqlite_learnings_scope.py`'s reference, *"per ADR-068:275"*

A line passes when it also carries one of the entry's `citation_markers` — the
superseding ADR's id, or a word like "supersedes" or "stale". Without that
allowance the only way to pass would be to **delete the history of the change**,
which is worse than the defect: a reader could no longer find out that the rule
moved or why.

`test_the_superseding_decision_is_a_citation_marker_for_its_own_entry` closes
the obvious hole — an entry whose canonical citation does not satisfy its own
check would force exactly that deletion.

`test_the_marker_must_be_on_the_same_line` records a deliberate strictness. A
citation three paragraphs away does not stop the directive from reading as a
directive to someone skimming, which is how this survived.

## Discrimination, measured

Run against the tree before the two edits, the gate reports both stale lines and
exits 1. After them it exits 0 across 357 governed files. `TestAgainstTheRealTree`
asserts the glob actually reaches `packages/maistro-core/CLAUDE.md` — a gate
whose glob missed it would have looked correct throughout, since the root file
was already right.

`test_the_clean_message_says_how_much_it_looked_at` exists because "ok" with no
denominator cannot be told from "ok, I scanned nothing" — the same vacuous-pass
shape that let a diff-coverage run report "0 changed file(s) measured" and pass
earlier in this session.
