---
inventory-delta:
  tests/: +36
---
# claude-m2-374-citation-status

The registry linter asks whether a cited document *exists*. #374 is about the
stronger question: does an **active** document rest its authority on something
that is not itself active — a Superseded ADR, a Deprecated one, or a decision
still merely Proposed.

**`tests/test_check_citation_status.py` (+34)**

*The rule, across status combinations.* Accepted and Implemented are authority;
Proposed, Fully Specced, AC Defined, In Progress, Tests Passing, Deprecated,
Deferred, Denied and Will Not Implement are not. AC Defined and In Progress are
still active *sources* and are checked, so unfinished work cannot silently claim
Proposed authority. The asymmetry is the substance and has its own test: a
**Proposed source may rest on a Proposed decision**, because a document that has
not shipped governs nothing and so makes no false claim. Only active documents
are held to the rule, since those are the ones a reader takes as describing what
the system does now.

*Which fields govern.* `substrate` and `implements` assert live authority and
are checked. `related`, `blocks` and `blocked_by` are navigational and are not
— holding them to the rule would make it impossible to reference history at
all, which is the escape hatch the error message recommends. `supersedes` is
exempt by construction: requiring its target to be active would make every
supersession self-contradictory.

*Supersession chains.* A Superseded citation names its active replacement, so
the error does the lookup rather than reporting only that the target is
Superseded. Chains are followed to their active end and reported where they
actually broke, not at the citation three links away. Every supersession branch
is traversed, including branches hidden behind an immediate active replacement.
A cycle is reported rather than looped — bounded by a path set, because a cycle
has no depth at which it becomes legitimate. Two live claimants to one
superseded decision is a fork nobody can follow, and fails. The same-status case
is covered too: two Accepted (or two Implemented) replacements are still
contradictory, rather than being collapsed into one set member. A transition
test confirms that a replacement remains invalid while Proposed and becomes the
named active replacement only after Accepted. The source-status matrix
exercises every lifecycle state, not just the representative Proposed case.

*One defect, one voice.* A citation to a document that does not exist is left
to `linker.check_links`, which already reports dangling references.

*The gate itself.* Loaded in-process as a module rather than only run as a
subprocess: a subprocess proves it works and measures none of it, and `scripts/`
is a coverage producer here, so a new gate sitting at 0%% would be the same
"written but never exercised" shape these ledgers exist to find. `main` takes
its argv explicitly for the same reason. Writing those tests found a crash in
the `--update` reporting line when the ledger sits outside the repo root.

*The ratchet.* Keyed on the citation, not on the reason: the reason is prose
and will be reworded, and keying on it would turn every improvement to an
error message into a wave of phantom findings. A fixed citation must shrink
the ledger in the same change.

*Corpus cleanup.* Superseded citations now name ADR-095 or ADR-019, while
historical/deprecated or not-yet-authoritative references were moved from
`substrate`/`implements` to `related`. The seven violations exposed when AC
Defined and In Progress sources became checked were handled the same way. The
citation baseline is now empty, so every active governing citation must resolve
to an Accepted or Implemented authority.

`cli lint` remains responsible for reference existence; the citation-status
gate enforces the stronger lifecycle relationship and fails on any new
exception.

Five vulture entries pruned rather than banked: `Status.ACCEPTED`,
`IMPLEMENTED`, `SUPERSEDED`, `FULLY_SPECCED` and `TESTS_PASSING` were enum
members nothing consulted until this checker read them.
