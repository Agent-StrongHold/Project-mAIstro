# M8-A1 research note — Hypothesis state machines over the canonical execution lifecycle

Epic: #880. Leaf: #881. Status at this head: **experiment executed** against the
real canonical persistence seam (`PgRunStore` over PostgreSQL), with a
demonstrated-mutant battery. Disposition: **INCUBATE**, with three WATCH
follow-ups. No product code changed.

## Research question

Do bounded `RuleBasedStateMachine` runs over the real Run → NodeRun → Attempt
lifecycle find sequencing/state defects that the current example-based and
security-focused property suites do not — at a CI cost the repo is willing to
pay?

## What was built

`formal/models/test_execution_lifecycle_state.py` (three collected nodes):

1. **`ExecutionLifecycleMachine`** — a Hypothesis state machine driving the
   real `PgRunStore` against a migrated PostgreSQL, in the style of I29
   (`test_run_lease_fence.py`). Five rules (`move_run`, `create_node_run`,
   `claim_attempt`, `move_attempt`, `move_node_run`) sample targets from the
   *full* status sets, so illegal moves are generated as often as legal ones.
   Six invariants compare the store against a model that evolves by table
   arithmetic over the published `RUN_TRANSITIONS` / `ATTEMPT_TRANSITIONS` —
   never by reading a stored status to decide what to expect, which is the
   #410 evidence rule. The model encodes the store's documented cross-level
   contracts rather than copying them:
   - **Earned completion (#241/#43).** A Run may only complete when its
     *latest* NodeRun per node completed; a failed/cancelled/timed-out or
     paused (human-wait) latest NodeRun blocks, an open one is cascaded.
   - **Cascade settlement (ADR-082426-a47f).** A terminalizing Run settles
     every open NodeRun to CANCELLED in the same write.
   - **Attempt exclusivity.** At most one live Attempt per NodeRun, with the
     live set imported from the store (`_ACTIVE_ATTEMPT_STATUSES`).
   - **#1335 fence.** COMPLETED is the one Attempt exit refused under a
     terminal Run, and it is refused *before* the table check; FAILED and
     CANCELLED stay legal there because they record physical outcomes.
   - **Closed Runs admit no work.** `create_node_run` and (via the terminal
     NodeRun guard) `create_attempt` must refuse under a terminal Run.

2. **Two deterministic witnesses** for the contracts whose counterexamples sit
   at the end of long, specific sequences: the earned-completion path (both
   directions, including retry via a *new* NodeRun for the same node) and the
   #1335 fence (cancel under a live RUNNING Attempt, then the refusal, then
   the legal FAILED sibling, then the closed-Run work refusals).

## Why the deterministic witnesses exist (a real measurement, not a hedge)

The machine alone did **not** catch the earned-completion mutant at the PR
budget: threading "Run RUNNING + latest NodeRun terminal-not-completed +
`move_run(COMPLETED)`" is a ≥4-draw specific window, and 15 examples × 16
uniform steps missed it (expected hits ≈ 10⁻²). That is the honest finding
about *shallow state machines over slow backends*: uniform random walks reach
contract boundaries polynomially rarely, and a nightly budget only shifts the
threshold. The witnesses pin the two deepest sequences so every CI pass proves
them; the machine keeps their interleavings. Anything less documented — e.g.
claiming the machine "covers" earned completion — would have been false at the
budget CI actually runs.

## Evidence

**Mutant battery** (each a one-line mutation of a PYTHONPATH-shadowed copy of
`packages/maistro-core/src`; worktree untouched; `pytest
formal/models/test_execution_lifecycle_state.py --hypothesis-seed=0`):

| # | Mutant | Caught by | Counterexample quality |
|---|--------|-----------|------------------------|
| M1 | `_validate_run_transition` → no-op | machine, `move_node_run` rule | shrunk to a **single step**: init, then `move_node_run(CREATED)` — a self-transition accepted |
| M2 | `check_completion_is_earned` → early return | witness `test_completion_of_the_run_is_earned_by_its_latest_node_run` | deterministic; machine alone missed it at PR budget (see above) |
| M3 | terminal-run cascade disabled | machine invariant `no_open_node_run_under_terminal_run` **and** the #1335 witness's cascade assertion | invariant message names the exact open NodeRun left behind |
| M4 | `refuse_completion_under_terminal_run` → pass (#1335 removed) | witness `test_attempt_completion_is_refused_under_a_terminal_run` | deterministic |
| M5 | terminal-NodeRun guard removed from `create_attempt` | machine `claim_attempt` rule **and** the #1335 witness | machine shrink took ~29 s |
| M6 | terminal-Run guard removed from `create_node_run` | machine `create_node_run` rule **and** the #1335 witness | machine shrink took ~48 s |

**Runtime.** PR budget (15 examples × 16 steps + witnesses): 3.9–7.5 s against
a local pgvector:pg18. Measured 60-example run: 17.6 s — roughly linear, so a
10k-example nightly for this module would be ~45–50 min and is *not*
recommended; nightly budgets should raise `MAISTRO_FORMAL_PG_EXAMPLES` into
the low hundreds instead.

**Flake rate.** Zero failures across seeds 0–3 on the unmutated tree (four
runs, small sample). Timing is exempted (`deadline=None`, as I29) because a
live database sets the pace.

**Defects found: none.** The store held every contract the model probed — the
lifecycle tables, the earned-completion check, the cascade, the #1335 fence
and the closed-Run guards all behaved exactly as their docstrings claim. That
is a real (negative) result: this family of sequencing bugs is *already
covered* at this head, chiefly by `packages/maistro-core/tests/runs/`
(spine conformance, #1335/#241 regression tests) and I29. The prototype's
value is therefore a **regression net with demonstrated teeth**, not a defect
harvest.

**Maintenance burden.** Moderate and bounded: the model encodes six documented
contracts against two imported tables; a deliberate change to any of them
(e.g. a new Run status, or a fourth live Attempt status) fails the machine
loudly and the fix is table-arithmetic in one file. The two deterministic
witnesses are ordinary store calls and age like any integration test. The
PostgreSQL dependency is shared with I29 and already provisioned in
`formal-conformance.yml`; without a DSN the module skips, which CI never does.

## Comparison against existing coverage

`tests`/`packages/maistro-core/tests/runs` pin the contracts *pointwise* —
each rule with hand-chosen inputs. I29 pins the Attempt-level lease/fence
interleavings. What neither does, and the machine adds, is cross-level
interleavings under a single generative walk: cancel a Run mid-Attempt and
then retry the node, complete a Run over a *retried* NodeRun while an older
failed one exists, move an Attempt under a Run that paused. No counterexample
from that space survived the store — but the space is now being searched every
CI pass.

## Trust-boundary implications

None introduced; the artifact is test-only, per the research guardrails:

- **No product code changed.** The module lives in `formal/models/`, imports
  only the published transition tables and `PgRunStore`, and
  `scripts/check-formal-oracle-independence.py` verifies it touches no oracle
  or security-implementation path.
- **The private import is read-only and test-scoped.** The test imports
  `_ACTIVE_ATTEMPT_STATUSES` straight from the installed `maistro.runs.pg_store`;
  the shipped module is never modified, and the machine fails loudly if the
  live set drifts rather than silently widening what it treats as
  authoritative. (The mutant battery is the thing that shadows
  `packages/maistro-core/src` on `PYTHONPATH`; the test itself does not.)
- **No new authority surface.** The machine drives only public store mutators
  against a throwaway, migrated PostgreSQL (local pgvector container via
  `MAISTRO_TEST_PG_DSN`); it holds no credentials, bypasses no gate, and
  writes nothing a production caller trusts. INCUBATE (not GRADUATE) keeps it
  evidence, not a canonical authority.

## Disposition: INCUBATE

Keep the module in `formal/models/` and let it run in PR CI as-is. It earns
its ~8 s: six demonstrated-mutant contracts on the canonical spine, in the
suite whose job is exactly this. Before counting its invariants in the #410
evidence ledger, it should survive one nightly soak with
`MAISTRO_FORMAL_PG_EXAMPLES` in the low hundreds — that soak has not been run
here and is the one claim this note does not make.

**WATCH (follow-up candidates, none scheduled by this issue):**

- **Recovery interplay.** The machine holds no lease TTLs, so the
  reclaim sweep (`reclaim_expired_attempts`), lease renewal and
  `recovered_attempt` parking are unmodelled. A clock-controlling rule set
  over the same spine is the natural M8-A1 sequel and is where a real
  sequencing defect is most plausible.
- **Tasks seams.** `maistro.tasks.queue` / `maistro.tasks.runner` and
  lane admission/cancellation were candidate targets this prototype did not
  reach; receipts-vs-spine contradiction is only pinned pointwise today.
- **Cross-store conformance.** The machine runs against `PgRunStore` only;
  running the same model against the SQLite backend (as the spine conformance
  suite parametrizes) would turn it into a differential oracle for the two
  stores' lifecycle behavior.

## Validation at this head

- Clean runs, seeds 0–3: `3 passed` each (pgvector:pg18 at 127.0.0.1:18881,
  `alembic upgrade head`, `MAISTRO_TEST_PG_DSN` set).
- `uv run ruff check formal/` → clean; `uv run ruff format --check formal/` →
  38 files already formatted.
- `python3 scripts/check-formal-oracle-independence.py --base <merge-base>` →
  OK (no oracle or security-implementation paths touched).
- `python3 scripts/check-suite-inventory.py --suite formal/` → ok (667
  collected = 664 before + this change's +3); full check collects 13/14
  suites ok, with `packages/hive-conductor/backend/tests` failing to collect
  under bare system python (no `pydantic` installed outside the uv venv) —
  an environment artifact of this worktree, unrelated to the change.
