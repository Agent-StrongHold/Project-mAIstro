---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/maistro-rsi/tests: +58
---

# 552 epic M5-B: RSI containment validation + canonical convergence (#50)

Lane for epic #552. First pass validated containment at base c5e070d97;
re-validated after merging origin/develop `ab8b3737f` (merge `6912141b0`,
+364 commits of child-issue work); this pass implements the epic's
"canonical convergence" exit criterion (#50) on top: RSI campaigns now
execute as canonical Run/NodeRun/Attempt work, consume the generic M3
work-source contracts, and gate kept promotions through the shared M4
promotion contract — as a downstream consumer, never a second authority.

Re-validated after syncing the lane branch onto the latest origin/develop
(`fad17a87c`, merge `85e84fc6a` — +98 upstream commits incl. the M5-B #2171
bounded frontier-model campaign surface): the #50 convergence seam is
the sole author and unchanged by the sync; all gates were re-run and pass.

## What this pass adds (issue #50, epic exit criteria)

- `packages/maistro-rsi/src/maistro_rsi/canonical_provenance.py` —
  `RsiCycleProvenance`: admit/run/record one RSI cycle as one canonical
  Run/NodeRun/Attempt in an authorized Workspace/Project (modeled on
  Canvas's `canonical_execution.py`). Includes the #1572 Goal binding
  through `RunStore.create_run` (the service wrapper drops it), idempotent
  admission per cycle id, and a `wrap_executor` seam so the autorun
  coordinator's existing executor gains canonical identity without a second
  scheduler.
- `packages/maistro-rsi/src/maistro_rsi/work_source.py` — `RsiWorkSource`:
  the #98/#100/#101 consumption half. Objectives are selected and claimed
  through the authorized `AgentBacklogSurface` (never the store directly),
  receipts are filed into the generic `BacklogHistoryStore` as Run
  references, discovered work is proposed back as new PROPOSED items with
  `source="rsi"`, and closure requires evidence refs (a completed Run alone
  is never closure evidence, ADR-082426-19ed).
- `packages/maistro-rsi/src/maistro_rsi/promotion_contract.py` — the shared
  M4 contract (#116): kept promotions are gated and minted through
  `maistro.governance.promotion` with the CODE scope's protected
  constituents being exactly #109's `EVALUATOR_ORACLE_PATTERNS`; no
  canonical evaluation Runs or evaluator versions ⇒ no shared record
  (fail-closed, never fabricated).
- Wiring: `autorun.py` (`run_autonomous(provenance=…, work_source=…)`;
  refuses `work_source` without `provenance`; a stall intervention's
  reviewer directions are proposed back into the generic backlog as new
  PROPOSED items and journaled against the discovering Run) and
  `local_loop.py` (`LocalRsiLoop(provenance=…, campaign_id=…,
  actor_principal_id=…)`; each executed cycle files its canonical receipt,
  and every promotion review carries a `decision.shared_contract` leg that
  reports recorded/skipped/refused honestly). The work-source seam is a
  public package API (`from maistro_rsi import RsiWorkSource`), so it is
  reachable from any `import maistro_rsi` — not built-but-never-wired.

## Salvage pass (this round): executor report identity, claim-checked closure, real fragment matching

Post-rate-limit salvage of the lane's uncommitted work, plus the named CI
gate failure (`Supply chain (pip-audit)`), fixed at its root:

- `canonical_provenance.wrap_executor` returns the executor's own report
  object. The Attempt's durable result round-trips through `evidence_json`
  (Sqlite and Pg), so the old read-back handed `HtrCoordinator.run` a plain
  dict after the first executed cycle — `report.evidence` would trip. The
  spine still persists the payload; the caller keeps object identity.
- `LocalRsiLoop` derives a unique default campaign id (`local-loop-<hex>`) so
  two loops sharing a provenance store cannot file cycles 1..n against each
  other's terminal Runs (#50 collision); an explicit `campaign_id` still wins.
- `rsi_promotion_contract` matches the CODE-scope protected set through the
  shared segment-boundary matcher (`_matches_segment_patterns`), so repo-root
  diff paths like `packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py`
  are refused — verbatim matching let them evade the #109 fence the contract
  claims to enforce.
- `AgentBacklogSurface.close` (new, claim-checked like `write`) and
  `RsiWorkSource.close` now route the terminal status move through the
  authorized surface instead of the raw store: a stale snapshot can no
  longer close work another actor holds, and revoked access fails closed.
- **pip-audit gate repair** (CI-exact commands re-run locally, exit 0):
  `uv.lock` upgraded `fastmcp` 4.0.11 → 4.1.3 and `setuptools` 84.0.0 →
  84.2.1 — both advisories (GHSA-7xgj-8392-5q4r, GHSA-vqqp-x5qm-5qp4,
  GHSA-xmj3-9gf7-h52w) have fixed versions, so per the gate's own policy
  they are upgraded, not allowlisted. The only remaining finding is the
  already-triaged ecdsa pair.

Salvage deltas: `packages/maistro-rsi/tests` +5
(`test_sqlite_backend_returns_the_executor_report_object`,
`test_default_campaign_ids_are_unique_per_loop`,
`test_refuses_evaluator_edits_at_real_repository_paths`,
`test_stale_snapshot_cannot_close_another_claimants_item`,
`test_close_is_refused_when_workspace_access_is_revoked`),
`packages/maistro-core/tests` +1 (`test_close_is_authorized_and_claim_checked`).

## Repair round: closure attribution + standalone discovered work (+2 RSI)

Review of the salvage head found two settlement bugs in the #50 wiring,
both fixed in `autorun.py` and pinned by two new tests in
`test_canonical_convergence_wiring.py`:

- **P1 — stale-evidence closure.** A resumed (persisted) tree that claimed
  a *new* item settled it against the tree's cumulative best — the
  predecessor item's proven improvement. `_claim_seed_objective` now always
  binds the claimed instruction into the tree (reusing an existing node on
  crash-resume, same dedupe rule as config seeds), and
  `_settle_sourced_objective` closes only when the best candidate descends
  from the claimed item's own node (`_bind_objective_node`,
  `_in_claimed_lineage`); anything less releases the claim with an explicit
  reason. Pinned by
  `test_resumed_tree_never_closes_a_new_item_on_stale_evidence`.
- **P2 — lost discovered work.** Stall directions were filed as *children*
  of the claimed item, so a campaign that improved *after* a stall crashed
  settlement with an uncaught `BacklogClosureError` (the backlog forbids
  both decomposing a terminal parent and closing a parent with open
  children), losing the discovered-work submissions. They are now filed
  standalone — the claimed item is named in each child's details and the
  provenance link lives in the audit journal, not in parentage. Pinned by
  `test_discovered_directions_survive_closing_the_claimed_item`.

Executed this round: the six targeted suites — **87 passed**; vulture gate
(CI-exact args) — **1302 findings == 1302 reviewed identities, exit 0**;
suite-inventory gate for `packages/maistro-rsi/tests` — expected 1780 ==
collected 1780 after this note's +47.

Executed this pass: full `uv run pytest packages/maistro-rsi/tests -q` —
**1774 passed, 4 skipped**; `packages/maistro-core/tests/backlog` —
**97 passed, 20 skipped**; `uv run ruff check .` and
`uv run ruff format --check .` — clean (3491 files); CI's exact ten-package
`uv run mypy` — no issues in 1105 source files; `uv run mypy --strict
packages/maistro-core/src` — no issues in 826 files;
`uv run python scripts/pip_audit_gate.py pip-audit.json` on a fresh
CI-shaped audit (`uv sync --locked --all-extras`, `uv pip freeze
--exclude-editable`, `pip-audit --strict --format=json`) — exit 0.

## Tests added (+45 node IDs in packages/maistro-rsi/tests, +1 in packages/maistro-core/tests)

- `test_canonical_provenance.py` (12): admission provenance + idempotency,
  Goal binding both-or-neither, run-through-the-spine with durable Attempt
  results, failure propagation with terminal Run/NodeRun, observed-outcome
  receipts (success and failure), sync-facade refusal inside a live loop,
  wrap_executor one-call-one-Run, find_cycle scoping.
- `test_work_source.py` (9): authorized claim ordering, #101 journal
  receipts with Run references, evidence-ref-required closure, release
  keeps the item open, discovered work filed as new rsi-sourced items,
  unwired-history tolerance, deterministic objective text.
- `test_rsi_promotion_contract.py` (11): CODE-scope classification, kept
  promotion minting + mechanical authority ≠ author, refusals for missing
  Runs/evaluator versions, evaluator-oracle edits, self-approval, no-op,
  stale base, version chaining on one subject.
- `test_canonical_convergence_wiring.py` (8): `run_autonomous` refuses
  work_source-without-provenance; improved campaign closes the claimed item
  citing its canonical Run; unimproved campaign releases the claim; the
  full local loop (real git fixture) records every executed cycle as a
  completed canonical Run and its promotion reviews report the shared
  contract honestly (skipped without evaluator provenance, recorded with
  it, refused loudly on an oracle edit).

## Executed and passing (this pass, head of lane branch)

- New tests: `uv run pytest packages/maistro-rsi/tests/test_canonical_provenance.py
  test_work_source.py test_rsi_promotion_contract.py
  test_canonical_convergence_wiring.py` — **40 passed**.
- Regression on the two wired drivers: `uv run pytest
  packages/maistro-rsi/tests/test_autorun.py test_local_loop.py
  test_promotion_review.py test_review_promotions.py` — **102 passed**.
- Full RSI suite: `uv run pytest packages/maistro-rsi/tests -q` —
  **1758 passed, 4 skipped** (was 1664 at the pre-sync head; +94 from
  develop's #2171 campaign surface — not part of this pass's delta).
- Containment batteries re-run (no gate weakened): all green at the
  post-sync head — host-shell/non-production-reachability/quarantine/
  promotion-review/sensitive-paths/regression-judge/argv/spec/gate-helpers,
  harvest-boundary/export/rate-pacer/fitness/inventory/red-green/
  evolve-bridge/gateway/quota/mutation, isolated-wrapper/harvest/checkpoint,
  **216** Conductor containment, child-behavior suites
  (#108/#109/#392/#2043/#2101/#110-partial).
- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run mypy` with CI's exact ten-package argument list — **no issues in
  1068 source files** (was 1048; +20 from develop's new source files).
- `uv run python scripts/check-radon-baseline.py` — 0 new, 0 regressed,
  0 stale (134 C-or-worse blocks at the synced base fad17a87; unchanged
  from the post-sync baseline).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact args) —
  1321 findings == 1321 reviewed identities, exit 0.
- `uv run python scripts/check-reachability.py` — no newly unreachable
  module (`work_source` is reachable via the package `__init__
  export`); 1419 production modules, 168 unreachable.
- `uv run interrogate -f 64 packages/maistro-rsi/src` — 68.6% ≥ 64% floor.
- `uv run python scripts/check-suite-inventory.py` — the only RSI drift is
  this note's **+40** (unchanged; develop's #2171 campaign tests are in
  the synced baseline, not the delta). **Re-validation update:** an earlier
  pass of this note recorded the gate aborting on collection errors in the
  four reference-gallery extension suites; that is no longer true at the
  current head — develop's #2213 wiring makes `gallery-weather-connector`,
  `gallery-unit-skill`, `gallery-model-adapter`, and `gallery-renderer-pack`
  installed workspace members (`pyproject.toml`, uv-managed), and after a
  fresh `uv sync --locked --extra dev` the **full gate exits 0**: all 21
  suites match, RSI collects 1762 (baseline 786 + folded deltas incl. this
  note's +40), 32346 unique node IDs, 0 duplicates. No known residual gate
  failures remain for this lane's scope.

## Containment half (still proven, prior passes)

- RSI is non-production-reachable: static import freeze on engine packages;
  Conductor confined to two policy-gated files; quarantine + signed
  approval gate promotion; sensitive-path protection; fail-closed regression
  judge; argv-only model arguments; SPEC §3 fail-closed conformance.
- #804 non-instantiation re-verified at the post-sync head: `grep -riE
  "workspace[_ ]agent|goal.?reconcil" packages/maistro-rsi/src` matches only
  the design docstring in `work_source.py` that attributes the generic
  contract to #804 — there are zero imports or call sites of a workspace
  agent / goal reconciler in RSI. The #50 convergence pass consumes the
  generic contracts only, no reconciliation loop of its own.
- Bandit gate mandatory in fitness; per-gate state/evidence on TraceNote
  (#304/#820); CI-side execution evidence is `scripts/check-gates-ran.py`.

## Still open for the epic

- The epic's other children (#302–#359/#509/#820 sub-items, #108/#109/#111/
  #114/#392 remainder) are tracked in their own issues; several landed
  upstream via the develop sync and pass here.
- Milestone re-parenting of children is GitHub hierarchy state, not
  verifiable from the repository.

## CI-repair round at 90f272bb (this pass): radon/xenon, diff coverage, container scan — +11 RSI

Repair against the merge-queue evaluation at head `90f272bb`. Four of the
failing gates are fixed at their root and re-proven locally with CI's exact
commands; the promotion-surface cluster is **not** fixable inside this
round's authority and is documented below as blocked with the required
owner action (the same resolution this repository recorded for the
execution-lifecycles ratchet in `docs/1572-repair-checkpoint.md`).

Fixed this round:

- **Quality / Radon** — `autorun.py:_settle_sourced_objective` was a new
  C(11) block (the only unbaselined finding;
  `scripts/check-radon-baseline.py`: "127 reviewed C-or-worse blocks ->
  128"). The nested release-reason ternaries moved into
  `_release_reason` (A(3)); the block is now B(9) and the gate exits 0
  with the ledger unchanged at 127 == 127 (no baseline edit, Boy-Scout
  fix not a floor raise). `XENON_BASELINE` pin test
  (`tests/test_complexity_gate_scope.py`) passes: 5 passed.
- **Quality / Xenon** — block violations 128 -> **127** (== baseline
  127), module-rank violations 0, project-average violations 0 (CI's
  exact `xenon --max-absolute B --max-modules B --max-average A
  -i third_party ...` over all ten shipped trees).
- **Coverage gate (diff half)** — `canonical_provenance.py` measured
  77.6% of 58 changed branch arcs (< 80% floor): twelve defensive
  branches were untested. Eleven new white-box tests in
  `TestDegenerateCanonicalPaths` pin them (terminal-run settlement,
  terminal-NodeRun skip during failure projection, lost-record refusals
  via a vanishing-lookups store wrapper, resume from QUEUED/RUNNING,
  no-Attempt refusal, re-close idempotence, RUNNING-node leaves the Run
  open, non-string hypothesis falls back to the neutral objective). The
  twelfth (`wrap_executor`'s `if produced:` false arc) is unreachable by
  construction — `_cycle` appends unconditionally before `run_cycle`
  returns — and the floor clears without touching production code.
  `scripts/check-diff-coverage.py` (base `4de7e906`): **"ok: every
  measured file this change touches is at or above 90% lines / 80%
  branch arcs"**.
- **Container scan + SBOM + cosign** — the hive-conductor frontend lock
  carried `zod` 4.4.3 (GHSA-mrhx-c7xc-m3w5, high) and the canvas lock
  six advisories (zod, body-parser, undici, ip-address, @vitest/mocker).
  Fixed by lockfile-only `npm audit fix` in both frontends (no
  package.json change; all fixes in-range, none allowlisted):
  `npm audit` now reports **0 vulnerabilities** in both trees, and
  `npm ci` + `npm run build` pass inside the digest-pinned
  `node:22-alpine@sha256:0a71...` builder; the full hive-conductor image
  builds locally (exit 0). `exact-debt-ledger`'s vulture component
  (CI-exact args) exits 0 — no ledger amendment required.

## Promotion-surface: blocked on an owner act (two-merge), not repairable here

The branch's #50 convergence wires `local_loop`/`autorun` (both
promotion roots) through `work_source` / `canonical_provenance` /
`promotion_contract` into the canonical core. Any static import of a
`maistro.runs.*` / `maistro.workspaces.*` / `maistro.graph.*` /
`maistro.runtime` submodule executes that package's `__init__` re-export
shim, which eagerly imports the wiring/stores — so the derived closure
grows from 278 modules (150 core) at base to **703 (≈562 core)**, leaving
**386 modules** "reachable from the promotion path and not protected"
(scripts/check-promotion-surface.py, exit 1; same finding reds
`check-ratchet-provenance.py` -> `check-promotion-surface-provenance.py`
inside exact-debt-ledger, the ci.yml escalation step, and the real-tree
tests in `tests/test_check_promotion_surface.py`).

The gate offers exactly two remedies and this round can take neither:

1. *Tolerate with reasons* — `ratchet_provenance.load_authorizations`
   reads `quality/ratchet-authorizations.json` **from the merge base**
   (`4de7e906`): 50 promotion-surface grants exist there and all 50
   already sit in the tolerated ledger; **none** of the 386 is
   authorized at base. A candidate-side ledger edit is refused by
   design ("candidate baseline edits cannot approve them"), so this is
   mechanically impossible in the change that grows the closure.
2. *Protect via `SENSITIVE_PATH_PATTERNS`* — the reached set spans ~40
   core directories, so any pattern set that covers it escalates
   ordinary application surface, which the pinned policy test
   `packages/maistro-rsi/tests/test_sensitive_paths.py::
   TestItStaysASurfaceAndNotAWildcard::test_ordinary_application_surface
   _does_not_escalate` forbids by name
   (`maistro/memory/learnings/store.py` must not escalate). Rewriting
   that pin would defeat its documented purpose (a wildcard escalation
   surface) and is a policy act, not a repair.

Shrinking the closure instead would mean deleting the implemented,
tested #50 convergence (destroying this lane's acceptance work),
re-exporting it through dynamic imports (gate evasion), or a repo-wide
public-facade refactor of the four package inits (far outside a focused
repair). **Unblock path** (matches the #1572 precedent): an owner lands
the promotion-surface decision on develop — either the tolerance grants
for the ordinary-infrastructure remainder plus baseline entries, or a
deliberate seam-level protection tier for the canonical
backlog/workspaces/runs/graph/runtime/governance packages — after which
this branch requeues unchanged. No ledger, grant, pin, or workflow was
edited this round.

Executed this round (CI-exact commands, all exit 0 unless noted):
`uv run ruff check .`; `uv run ruff format --check .`; the six targeted
driver suites; `uv run python scripts/check-suite-inventory.py --suite
packages/maistro-rsi/tests` (expected 1791 == collected 1791 after this
note's +58); `uv run python scripts/check-suite-inventory.py --suite
packages/maistro-core/tests` (ok); `uv run python scripts/check-radon-baseline.py`; the xenon
scan above; `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'`;
`scripts/check-diff-coverage.py` (above); CI's ten-package mypy (no
issues in 1105 files); full `packages/maistro-rsi/tests` 1787 passed +
`packages/maistro-core/tests/backlog` 97 passed.

## Re-verification round at e656361d9 (independent first-hand pass)

Every claim in the previous section was re-executed from scratch at the
repair head; no file was changed by this round (the tree at `e656361d9`
is bit-identical to what the previous round left), so the inventory
delta above is unchanged. Results:

- `check-radon-baseline.py` → **exit 0**: 127 C-or-worse blocks == 127
  baseline entries, 0 new / 0 regressed / 0 improved / 0 stale.
- xenon, CI's exact ten-package argv → **127 blocks** (`==` baseline),
  0 module-rank, 0 project-average.
- `check-vulture-baseline.py` (CI-exact args) → **exit 0**, 1302 == 1302.
- `check-frontend-typed-client.py` → **exit 0** (53 raw-fetch + 136
  hand-typed tolerances, none new).
- CI's ten-package `mypy` → **Success: no issues found in 1105 files**.
- Diff-coverage gate reproduced end-to-end: fresh `coverage run --branch`
  producers (`packages/maistro-rsi/tests`: **1787 passed, 4 skipped**;
  `packages/maistro-core/tests/backlog`: 97 passed, 20 skipped) → `coverage xml` → `check-diff-coverage.py --base
  4de7e906` → **"ok: every measured file this change touches is at or
  above 90% lines / 80% branch arcs"** (7 changed files measured; 6
  test files exempt by declaration). The publish-set aggregate floor
  (87%) was not re-run in full; every non-exempt file this branch
  changes measures ≥90% lines, which can only raise an aggregate the
  base already passes.
- Container gate: `npm audit` → **0 vulnerabilities** in both frontend
  trees (prod-only and full); the previously failing `frontend` stage of
  `packages/hive-conductor/Dockerfile` builds at the digest-pinned
  `node:22-alpine@sha256:0a7108…` (**exit 0**), the **full
  hive-conductor image builds (exit 0)**, and the canvas frontend
  `npm ci` + `npm run build` pass in a clean scratch copy (the worktree
  copy has a root-owned stale `node_modules` that EACCESes `npm ci` —
  environmental, not a lock defect; the audit reads the same lock).
- `tests/test_check_promotion_surface.py` → **3 failed, 40 passed**;
  the 3 are the same real-tree findings documented below, unchanged.

The blocked half was re-derived, not assumed. `git fetch origin` first:
**origin/develop is still `4de7e906`** — no grant landed, so the
merge-origin/develop remedy has nothing to merge. The provenance
mechanics were re-read from `scripts/ratchet_provenance.py`
(`resolve_baseline` reads the ledger at the merge base;
`load_authorizations` reads grants at the base sha): a candidate-side
row is refused by construction. The closure growth was measured with
the checker's own graph functions: cutting every `maistro.*` import
from `work_source.py` removes only **4** uncovered modules, while
cutting them from `canonical_provenance.py` removes **380** (closure
703 → 283) — the amplifier is the acceptance-mandated import of
`maistro.runs.service` etc. behind the #50 convergence, and every
module that could host the concrete import instead (autorun, cli,
`__main__`, campaign_cli, `services.rsi`, `local_loop`) is itself a
promotion root, so no import shape shrinks the closure without dynamic-
import evasion or deleting the convergence. Escalating the ~40 reached
core directories instead is pinned out by name
(`TestItStaysASurfaceAndNotAWildcard` requires
`maistro/memory/learnings/store.py` — in the uncovered set — to stay
non-escalating).

**Disposition (unchanged): BLOCKED on an owner act.** All in-branch-
repairable CI reds from the 90f272bb evaluation are fixed and now
verified first-hand (radon, xenon, diff-coverage, container scan,
vulture, frontend-typed-client + mypy). The remaining cluster —
`check-promotion-surface.py`, the three real-tree tests,
`check-promotion-surface-provenance.py` inside exact-debt-ledger, and
the dependent Quality-gate summary — resolves only when an owner lands
the promotion-surface tolerances (or a deliberate protection tier) on
develop under the two-merge rule, after which this branch requeues
**unchanged**. Same resolution shape as the #1572 checkpoint.
