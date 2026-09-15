---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +65
---
# claude-m1-issues-merge-plan-l7g9xz-95af

Fixes the starvation defect shared by durable-run recovery, HITL-pause
expiry, and hive-conductor's `/v1/hitl/pending` scan: a bounded
oldest-first page combined with a post-hoc eligibility filter could let a
long ineligible prefix starve real work forever. All three now page
through a new `fair_page_scan` combinator instead of taking the first
page's worth of candidates as the whole answer.

`packages/maistro-core/tests` (+54): a new
`graph/durable_runs/test_fair_scan.py` suite covers `fair_page_scan`
directly (cursoring, short-but-nonempty pages, `max_inspected`/`limit`
stops, and — after the review finding that a per-tick bound restarting from
the top is the same starvation one size up — six `ScanContinuation` cases:
the reviewer's exact repro of a row behind the 2,000-row ceiling reached on
the next tick, the control row just inside it, resuming after the last
*inspected* row rather than the page, the restart from the top after walking
off the end, a stale position past the end, and a fetch failure leaving the
position untouched); `test_recovery_wakeup.py`, `test_hitl_settlement.py`,
and `test_continuation_conformance.py` gained cases exercising the new
`after` cursor parameter across the in-memory, SQLite, and PostgreSQL
`DurableRunStore`/`GraphContinuationStore` backends, plus per-candidate
failure isolation in `recover_queued_graph_runs`/`resume_due_graph_runs`;
`test_recovery_wakeup.py` also gained the multi-tick regression at the
production seam (more foreign-owned QUEUED Runs than one tick inspects, the
owned one reached on the second tick with a held continuation), and the new
`runs/test_fair_scan_parity.py` repeats that regression over the real keyset
paging of all three `RunStore` backends (three collected items; the
PostgreSQL leg runs where `MAISTRO_TEST_PG_DSN` is set).

`packages/hive-conductor/backend/tests` (+1): `test_hitl_door.py` gained
a case covering the rewritten `/v1/hitl/pending` route's internal manual
paging against the same starvation scenario.

A second review round found the same starvation one layer further down, at
the canonical store rather than at the combinator, and added 20 more cases
(+5 in `graph/durable_runs/test_fair_scan.py`, and a new
`graph/durable_runs/test_canonical_due_scan.py` whose five cases run against
all three continuation backends). `CanonicalDurableRunStore.list_due` reads a
page of due-index ids and drops the ones whose canonical Run has since gone
terminal, so a page made entirely of settled rows comes back empty — which is
also what the end of the index looks like. The walk read the two as the same
thing and reset to the top, so a settled prefix longer than one page hid the
live Run behind it on every tick. The new cases cover a fetcher reporting
progress and results separately (`ScanPage`), the inspection ceiling counting
dropped rows, exhaustion still restarting from the top, and — over the real
store on each backend — a hundred settled rows ahead of one genuinely due Run
being paged past in a single scan.

A further +5 in `graph/durable_runs/test_recovery_wakeup.py` close what the
diff-coverage floor found: the whole `scan_due_page` branch of
`_due_page_fetcher` was unexercised at the seam, so the fix was tested one
layer down but not where production reaches it. A miniature store implementing
the same page contract now proves the due tick prefers it over `list_due` and
never calls the latter, and a store without it still gets the plain listing.
Three error arms the same change introduced are covered too: cancellation
during a due resume and during a queued resume each abort the tick rather than
being swallowed by per-candidate isolation, and a due candidate with no
`resume_at` raises rather than paging from an invented cursor. `recovery.py`
is now at 100% line coverage.

A third review round (Codex on the develop merge) found three defects in this
branch's own code and each is now pinned by a case that fails without its fix.

`packages/maistro-core/tests` also covers, in this round:

- **A failure after the candidate was claimed is raised, not isolated**
  (`test_recovery_wakeup.py`, +2). `recover_queued_graph_runs`' generic
  `except Exception` arm reported every failure as candidate-local, unlike the
  `(KeyError, ValueError)` arm beside it, which re-reads the record first.
  `resume_durable_graph` checkpoints the QUEUED continuation and moves the Run
  to RUNNING before anything that can fail that way, so a swallowed failure
  stranded the Run for good: the QUEUED scan no longer returns it and the due
  index never held it. The pair covers both halves of the rule -- a claimed
  candidate raises, an untouched one is still isolated so the tick carries on.

- **Keyset cursors page by instant, not by printed offset**
  (`test_continuation_conformance.py`, +3, one per backend). Rows were ordered
  as `datetime` and then paged past by comparing `isoformat()` strings. Those
  agree only while every row prints the same offset: `01:00+01:00` is the
  earlier instant than `00:30+00:00` but its string sorts after, so a cursor at
  the first row excluded the second from every later page, permanently --
  the starvation this branch exists to remove, reintroduced by a formatting
  detail. `resume_at` is whatever the pausing node computed and nothing
  required it to be UTC. `cursor_time` now normalizes every cursor key and
  every index column written beside one. PostgreSQL never had the bug (it
  parses the cursor back to a `timestamptz`), so this is the case where the
  three backends silently disagreed and only a conformance test could say so.

- **A filtering page cannot inspect past the budget it was given**
  (`test_canonical_due_scan.py`, +6, two cases per backend). The walker passes
  its *remaining* inspection budget as the page size, but `scan_due_page` kept
  its own independent 2,000-row ceiling, so one nominally 2,000-row tick could
  inspect nearly twice that. The budget is now passed through as
  `max_inspected`. The second case drives the real `_due_page_fetcher` seam and
  proves the cap is a pace rather than a horizon: capped below the stale
  prefix, the live Run is unreachable on the first tick and reached on a later
  one.

A fourth round, from re-reading the develop-merge resolution adversarially
before it landed rather than from a reviewer.

`packages/hive-conductor/backend/tests` (+1):
`test_hitl_door.py::test_pending_pages_by_instant_when_created_at_offsets_differ`.
The cursor-normalization fix reached every site in maistro-core and missed the
one outside it: `list_pending_human_work` still built its keyset cursor with a
bare `.isoformat()` while `list_by_status` had moved to comparing a
UTC-normalized key. Agreement then depended on every `created_at` printing the
same offset -- the precise assumption the fix exists to remove -- and a
disagreement would silently stop the walk advancing, hiding the HITL pause it
was paging toward.

The case is deliberately expensive in setup, because two cheaper shapes do not
reproduce it and the first two attempts at this test passed against the bug:

- Records must share one Workspace. The route loops Workspaces on the outside
  and pages on the inside, so the `seeded` fixture's Workspace-per-record
  shape never reaches the cursor at all. (The same is now true of
  `test_pending_reaches_a_hitl_pause_behind_a_long_machine_prefix`, which
  predates the Workspace scoping and no longer exercises the inner walk its
  docstring describes.)
- The machine prefix must exceed `_PENDING_SCAN_PAGE_SIZE`, so 101 rows. Below
  that the whole set returns in the first page and the cursor is never the
  thing that decides.

The machine rows print at `+01:00` and are the earlier instants; the human
pause prints UTC and is the later one. Normalized, it sorts after them and is
found; compared raw, `12:30:00+00:00` sorts before `13:05:00+01:00` and it is
excluded from every later page.
