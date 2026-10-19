---
inventory-delta:
  packages/maistro-core/tests: +79
---

# Task admission identity types (Issue #1851)

## Implementation scope

New source module: `packages/maistro-core/src/maistro/runs/admission_identity.py`
New tests: `packages/maistro-core/tests/runs/test_root_admission_identity.py`

## What was implemented

### Core identity contract module

- **`CanonicalJsonObject`**: Immutable, canonicalized JSON object holder with strict validation (no duplicate keys, non-finite numbers, non-object roots, etc.)
- **`AdmissionTicket`**: Claim ticket fencing conjunction of `scope_key`, `generation_id`, and `owner_token` (two independent UUID roles, owner token hidden from repr)
- **`RootAdmissionEnvelope`**: Immutable root admission decision snapshot with 14 fields (IDs, timestamps, canonical snapshots of request/receipt/provenance)
- **`AdmissionBinding`**: Committed pairing of admitted receipt to its canonical Run
- **`AdmissionRecordV2`**: Generation-fenced admission record with separate lease owner and validation invariants
- **`LegacyAdmissionRecord`**: Pre-generation canonical admission row (no generation ID, owner token, or fabricated identity)
- **`RootAdmissionResult`**: Outcome of root admission freezing a Run as canonical JSON

### Result variant discriminators

**ClaimResult variants:**
- `Claimed`: Fresh admission (caller holds generation lease)
- `Replayed`: Already-bound admission asked again
- `Pending`: Live unbound v2 lease blocks claim
- `LegacyUnresolved`: Unbound legacy row leaves claim ambiguous

**ReleaseResult variants:**
- `Released`: Lease released by owner
- `AlreadyBound`: Release refused (binding already committed)
- `StaleOwner`: Presented owner token no longer fences lease
- `LegacyUnresolved`: Legacy row ambiguity blocks release

**CompletionResult variants:**
- `Acknowledged`: Binding first acknowledged
- `AlreadyAcknowledged`: Binding already acknowledged (deadline unchanged)
- `StaleOwner`: Owner token no longer fences lease
- `BindingMismatch`: Presented binding does not match persisted binding

**AdmissionAssessment enum:**
- `MISMATCH`, `REPLAYED`, `PENDING`, `TAKEOVER`, `REPLACE_EXPIRED`, `LEGACY_UNRESOLVED`

### Validation invariants

- All constructors validate and raise `ValueError` for invalid input
- Fields match exact types (`UUID`, `CanonicalJsonObject`, specific string constraints)
- Field order and annotations are fixed
- `owner_token` field excluded from generated repr output
- `scope_key` and `fingerprint` must match `[0-9a-f]{64}` exactly
- All `_us` fields are signed 64-bit integers, `expires_at_us > created_at_us`
- Fencing conjunction: `record.envelope.scope_key == ticket.scope_key AND record.envelope.generation_id == ticket.generation_id AND record.owner_token == ticket.owner_token`

### Test coverage

79 focused contract tests covering:
- Module exports exact contract and assessment values
- Canonical JSON normalization and validation (duplicate keys, non-finite numbers, non-object roots)
- Immutability and exact type enforcement (no subclass acceptance)
- Fencing validation (scope/generation/owner conjunction)
- Variant constructor acceptance paths
- Binding and acknowledgement invariants
- Legacy record behavior
- Invalid ID/timestamp/variant combination rejections
- Admission result snapshot validation
- Repr hygiene (owner_token field omission)

## Quality staging compliance

- Module is **inactive contract leaf**: no production module imports it yet
- `__all__` defined exactly with 21 names as specified
- Dataclasses are `@dataclass(frozen=True, slots=True)`
- All validation rules enforced per constructor
- Module-local API declaration (not exported through package)
- No runtime consumer in this leaf (future C2 classifier and backend wiring pending)
- Tests do not import any production modules beyond the target
- Passing DTO tests prove type contract only, not atomicity or wiring integration

## Validation commands

```sh
uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q
uv run ruff check packages/maistro-core/src/maistro/runs/admission_identity.py packages/maistro-core/tests/runs/test_root_admission_identity.py
uv run ruff format --check packages/maistro-core/src/maistro/runs/admission_identity.py packages/maistro-core/tests/runs/test_root_admission_identity.py
uv run mypy packages/maistro-core/src/maistro/runs/admission_identity.py
uv run python scripts/check-suite-inventory.py
```

## Gate status

- Tests: ✅ All 79 pass
- Linting: ✅ ruff check passes
- Formatting: ✅ ruff format passes
- Type checking: ✅ mypy passes
- Inventory note: ✅ Created with delta tracking

## Notes

This implementation satisfies the exact type contract for the prospective C2 classifier and future admission backend. The module defines the typed vocabulary so a future backend can consume it without importing task models into RunStore or guessing field semantics. Production activation and runtime consumer integration remain separate pending #1845 parent integration.

## Round evidence — 2026-10-16 repair round (job f412080398ca40a6bb201520cd57417f, head 95e4288bf)

Independent re-derivation at the exact assigned head; no earlier verification claim assumed. Driver checks 5/5 rc=0 (`uv sync --locked --extra dev`, `ruff check .`, `ruff format --check .`, focused pytest 79 passed, suite inventory ok). All commands below re-executed live in this worktree.

Leaf acceptance (all proven live):

- Focused pytest `packages/maistro-core/tests/runs/test_root_admission_identity.py -q`: 79 passed; all 12 issue-named tests defined exactly once and pass by name (74 selected incl. parameterizations).
- `ruff check` + `ruff format --check` on both leaf files: clean. `mypy` on the module: Success.
- `check-suite-inventory.py --suite packages/maistro-core/tests`: rc=0, recorded delta +79 intact.
- Branch diff vs develop base `ac737014` = exactly the 4 in-scope files; `runs/__init__.py` does not re-export the module; zero tracked-tree importers (grep over `packages/**.py` matches only the test file).

exact-debt-ledger decomposition at this head (CI argv from `.github/workflows/vulture-ratchet.yml`, `RATCHET_BASE_REV=origin/develop`):

- `check-shipped-surface-truth.py`: rc=0. `check-reachability-dispositions.py`: rc=0 (49 groups / 169 modules).
- `check-ratchet-provenance.py`: rc=1 — the reachability ratchet flags exactly `maistro.runs.admission_identity` as NEW unreachable, absent from trusted base and missing from the candidate reachability baseline. Fixing it requires either real wiring (outside this leaf by issue scope) or a reachability-baseline entry (prohibited by the issue for this leaf; the round-76 history removed exactly such an attempt as prohibited).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: rc=1 — banking half GREEN (candidate ledger 1327 == scan 1327; merge `95e4288bf` resolved the ledger to develop's 1322 + the 5 banked enum-member rows, verified via `git diff --numstat origin/develop HEAD -- quality/` = +5 0 and per-ref row counts 1322/1327/1328/1322), authorization half RED: the 5 identities are not in the trusted base and 0 vulture/reachability grants for `runs/admission_identity` exist in `origin/develop:quality/ratchet-authorizations.json` (verified structurally; branch copy byte-identical to develop's). Grants are read from the merge base, so a branch-side grant is inert by construction (two-merge rule) and forbidden by the issue.
- Ledger identity format is line-number-independent (`path::message`), so no line-drift risk in the banked rows.

Test gate: exactly 3 failures in `tests/test_reachability_baseline_identity.py` (2) + `tests/test_check_reachability.py::test_baseline_matches_the_tree` (1), each naming the unwired module — the issue-anticipated honest state for an intentionally inactive leaf.

Salvage note: the 6 untracked files recorded by rounds 186–188 (#1852 C2 draft + quality backups) are no longer present in this worktree (`git status --porcelain -uall` and `git ls-files --others --exclude-standard` both empty); tracked tree intact, nothing discardable.

Conclusion: all leaf acceptance criteria are proven; the four red gates at this head (test / exact-debt-ledger / Quality / Coverage) are the explicit merge blocker the issue itself anticipates ("report implementation/test readiness plus the explicit merge blocker and leave the stack unmerged"). No in-scope, issue-legal change can turn them green; the resolving changes are the owner-landed develop grants (vulture authorization) and the #1845 integration head (real wiring). Coverage gate not reproduced locally (requires the full service stack); recorded as blocked at the stack head per issue staging rules.

## Round evidence — 2026-10-16 repair round (job 67f1fd921c894169b37de7dc81390e10, head f13176fe9e9b516ea6c445fcfe525a07d897caee)

Independent re-derivation at the exact assigned head (round 190); no earlier verification claim assumed. Driver checks 5/5 rc=0 from this job's check-0..4 logs (`uv sync --locked --extra dev`, `ruff check .`, `ruff format --check .` — 3299 files, focused pytest 79 passed, suite inventory ok) and re-executed live in the worktree.

Leaf acceptance re-proven live:

- Focused pytest: 79/79 pass; the 12 issue-named tests select 68 node IDs (incl. parameterizations), each defined exactly once, all passing; `ruff check` + `ruff format --check` clean on both leaf files; focused `mypy` Success; full `check-suite-inventory.py` rc=0 (17 suites, 31319 == 31319 unique, 0 duplicates).
- Structural AST audit: 17/17 dataclasses frozen+slots with issue field counts (Envelope 14, RecordV2 6, Legacy 7, Result 4, Claimed 2, Replayed/Pending/LegacyUnresolved/AlreadyBound 1, Released/StaleOwner/Acknowledged/AlreadyAcknowledged/BindingMismatch fieldless, CanonicalJsonObject 1); `__all__` set-exact vs the 21 issue names, 0 dups; `AdmissionAssessment` exactly the 6 issue member/value pairs; `owns()` a pure 3-compare conjunction (scope_key AND generation_id AND owner_token, never generation==owner); `field(repr=False)` exactly ×2; zero suppression markers in the module.
- Live behavioral probes 19/19: duplicate-key / NaN / non-object-root `ValueError` rejection, normalization convergence to `sort_keys` canonical text, `owns()` truth table including equal-role-values, frozen raises `FrozenInstanceError`, `owner_token` absent from record repr while generation_id stays printable, binding receipt-mismatch rejected, `Claimed` fencing enforced, `created` bool-vs-int typing, fieldless variants, enum values, legacy `lease_expires_at_us > expires_at_us` accepted.
- No-wiring proof: grep over `packages/**/*.py` — zero importers outside the module and its test; `runs/__init__.py` contains no admission reference; branch diff vs develop base `ac737014` = exactly the 4 in-scope files; 0 diff lines on `runs/store.py`, `runs/store_boundary.py`, `runs/model.py`, `tasks/idempotency.py`.
- #1841 signature revalidation at this head: `store_boundary.py:56` `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550` `get_run(self, run_id: str, *, principal_id: str | None = None) -> Run | None`; `actor_principal_id: str | None = None` retained at `store.py:507/:907/:1299` with the guard call at `:936`; `model.py:306` Run field + validation `:335-336`. (Accepted #1841 merged head: `c66c5c8f6013`.)

ci.yml `test` gate reproduced locally with CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`): `tests/test_reachability_baseline_identity.py` + `tests/test_check_reachability.py` → exactly 3 failed / 36 passed, each failure naming `maistro.runs.admission_identity` as the new unreachable module (`::error title=New unreachable modules::maistro.runs.admission_identity`).

ci.yml `Coverage gate` decomposition: its `--source=scripts` producer runs `pytest tests/` (quality.yml), which contains the 3 failing reachability-baseline tests above → producer aborts → "producer contributed no coverage data" → gate exits 1. The module itself is measured: the publish-set producer runs `pytest packages/maistro-core/tests --source=packages/maistro-core/src/maistro` (quality.yml:177-178), which includes the 79 focused tests. Same root cause, one hop downstream.

exact-debt-ledger decomposition at CI argv (`RATCHET_BASE_REV=origin/develop`; origin/develop re-fetched == `ac737014`, unchanged):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: rc=1. Banking half GREEN — fresh scan 1327 == candidate ledger 1327; multiset diff vs develop = exactly +5/-0 rows, all `admission_identity.py::unused variable '<ENUM>'` (MISMATCH, REPLAYED, TAKEOVER, REPLACE_EXPIRED, LEGACY_UNRESOLVED; PENDING is not scan-flagged). Authorization half RED — the 5 identities are not in the trusted base (develop 1322) and carry no grant: `origin/develop:quality/ratchet-authorizations.json` has 0 vulture and 0 reachability entries for `runs/admission_identity` (verified structurally; branch copy 0-line diff vs develop). Grants are read from the merge base → a branch-side grant is inert by construction (two-merge rule) and forbidden by the issue.
- `check-reachability.py`: rc=1, exactly one NEWLY UNREACHABLE: `maistro.runs.admission_identity`; `quality/reachability-baseline.json` and `quality/ratchet-authorizations.json` 0-line diffs vs develop (no self-baseline, no self-grant).
- `check-reachability-dispositions.py`: rc=0 (49 groups / 169 modules). `check-promotion-surface.py`: rc=0. `check-shipped-surface-truth.py`: rc=0.
- `check-ratchet-provenance.py`: rc=1 — "reachability ratchet moved away from trusted state": `maistro.runs.admission_identity` NEW unreachable, absent from trusted base, missing from candidate baseline; plus the vulture authorization half. Both are the two structural facts above.

CI-repair-round ledger decision: the lane-permitted amendment (`quality/vulture-baseline.json` for reviewed retained identities) is already in its correct reviewed state — the candidate ledger banks exactly what the fresh scan finds (1327 == 1327, +5/-0). Removing rows would regress banking to red; adding a grant or reachability-baseline entry is prohibited by the issue; no genuinely dead code exists to delete (the 5 identities are the issue's own fixed 6-member enum contract, consumed by the prospective C2 classifier). No ledger change warranted this round.

PR #1936 (stack) is open, unmerged, head == this commit; base develop. Salvage check: `git status --porcelain -uall` empty — nothing untracked to preserve.

Conclusion unchanged: all leaf acceptance criteria proven at the exact assigned head; the four red gates are the issue-anticipated explicit merge blocker, decomposed above to two structural facts (unwired leaf; ungranted-but-banked enum identities) whose only fixes are the #1845 integration head (real wiring, outside this leaf) and owner-landed develop grants (two-merge rule). Writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged. Note-only commit; no inventory delta (stays +79).

## Round evidence — 2026-10-16 repair round (job 8e1357c03c584a25a3d16deca5c21bf2, head a4dd7bc69d8faa1e041bf54a2dd3c29e51705cdd)

Independent re-derivation at the exact assigned head (round 191); no earlier verification claim assumed. Resolves the carried "worker made no commit" block with this evidence-bearing commit. Driver checks 5/5 rc=0 from this job's check-0..4 logs (`uv sync --locked --extra dev`, `ruff check .`, `ruff format --check .` — 3299 files, focused pytest 79 passed, suite inventory ok) and re-executed live in the worktree. `git fetch origin develop` re-run this round: `origin/develop` still `ac737014` (== assigned base, merge-base identical) — no develop sync conflict.

Leaf acceptance re-proven live at true exit codes:

- Focused pytest: 79/79 pass; all 12 issue-named tests defined exactly once (`grep -c '^def <name>'` = 1 for each; 19 test functions total); `ruff check` + `ruff format --check` clean on both leaf files AND the full tree; focused `mypy` Success; full `check-suite-inventory.py` rc=0 (17 suites, 31319 == 31319 unique, 0 duplicates).
- Structural AST audit green: 17/17 dataclasses `frozen=True, slots=True`; `__all__` set-exact vs the 21 issue names; `AdmissionAssessment` exactly the 6 issue member/value pairs verbatim; `owns()` a pure 3-compare `And` conjunction (scope_key AND generation_id AND owner_token; AST walk confirms no comparison ever relates generation to owner); `owner_token: UUID = field(repr=False)` exactly ×2; zero suppression markers (`# noqa`, `# type: ignore`, `pragma: no`, `pylint: disable`).
- Live behavioral probes 49/49: dup-key (top-level and nested), `NaN`, `Infinity`, `1e999` float-overflow, non-object root, non-string constructor input all `ValueError`-rejected; normalization converges to `sort_keys` canonical text; frozen raises `FrozenInstanceError`; `owns()` truth table (match / wrong-owner / wrong-generation / wrong-scope / equal-role-values); `owner_token` absent from ticket and record `repr` while `generation_id` stays printable; binding receipt-mismatch rejected; ack requires binding and >= creation without moving expiry; `created` bool-vs-int; snapshot `run_id` agreement both directions; legacy accepts `lease > expiry` and rejects `expiry <= created`; string-UUID, nil-UUID, non-hex64, uppercase-hex64, bool-`_us`, int64-overflow, whitespace-ID, empty-ID, v2 lease-window violations, dict-snapshot all rejected; `Claimed`/`Replayed`/`Pending`/`LegacyUnresolved` variant invariants; `ReleaseResult`/`CompletionResult` subclass proofs; fieldless empty variants; enum values; `format_version` `init=False` (TypeError on override).
- No-wiring proof: grep over `packages/**/*.py`, `tests/`, root `conftest.py` — zero importers of `admission_identity` outside the module and its test; `runs/__init__.py` contains no admission reference; branch diff vs `ac737014` = exactly the 4 in-scope files (156/520/660/5 lines added, 0 removed anywhere).
- #1841 anchors revalidated at this head: `store_boundary.py:56` `def require_admitted_actor(actor_principal_id: str | None) -> str:`; `store.py:550` `async def get_run(self, run_id: str, *, principal_id: str | None = None) -> Run | None`; `actor_principal_id: str | None = None` retained at `store.py:507/:907/:1299` with admitted-actor guard calls at `:936` and `:1340`; `model.py:306` Run field + validation `:335-336`. (Accepted #1841 merged head: `c66c5c8f6013`; no material signature change.)

ci.yml `test` gate reproduced locally: `pytest tests/test_reachability_baseline_identity.py tests/test_check_reachability.py -q` → exactly 3 failed / 36 passed, each failure naming `maistro.runs.admission_identity` as the new unreachable module (`::error title=New unreachable modules::maistro.runs.admission_identity`). Coverage gate not reproduced locally (quality.yml producer needs the service stack); per the issue's staging rules it is recorded as blocked at the stack head — its root cause is one hop downstream of the same 3 failures (its `pytest tests/` producer aborts before uploading data).

exact-debt-ledger decomposition at CI-true argv this round (`.github/workflows/vulture-ratchet.yml` job steps, `RATCHET_BASE_REV=origin/develop`):

- `check-shipped-surface-truth.py`: rc=0 ("Shipped-surface truth matrix is complete.").
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **rc=1**. Banking half GREEN: fresh scan 1327 findings == candidate ledger 1327 rows, and the multiset of scan-flagged identities is `Counter`-equal to the multiset of banked `admission_identity` rows (5 identities: MISMATCH, REPLAYED, TAKEOVER, REPLACE_EXPIRED, LEGACY_UNRESOLVED; PENDING is not scan-flagged because the module's own `Pending` class is a live definition of the same name). Authorization half RED: develop ledger 1322 rows; HEAD ledger = develop's 1322 + exactly the 5 scanned identities (Counter delta +5/-0, no silent row loss — checked per the `quality/*.json` silent-row-loss trap); `origin/develop:quality/ratchet-authorizations.json` mentions `admission_identity` 0 times; branch copy of that file is a 0-line diff. Grants are read from the merge base, so a branch-side grant is inert by construction (two-merge rule) and prohibited by the issue. Gate message confirms: "New Vulture debt is not authorized by the trusted base. Running --update in this branch cannot authorize it; land a reviewed grant first."
- `check-ratchet-provenance.py`: rc=1 — "reachability ratchet moved away from trusted state" plus "ratchet provenance inventory is incomplete: check-reachability-provenance.py: trusted-base gate returned 1"; every other ratchet section OK (0 contradictions, 0 citation exceptions, 270 promotion-path modules, 169 unreachable-with-dispositions, 0 shell/lifecycle expansions).
- `check-reachability.py`: rc=1, exactly one NEW unreachable: `maistro.runs.admission_identity`. `check-reachability-dispositions.py`: rc=0 (49 groups / 169 modules). `check-promotion-surface.py`: rc=0.
- CI check-runs at `a4dd7bc` (from dispatch context): exactly 4 red — `test`, `Quality gate (Pillars 1–4, 7, 8)`, `exact-debt-ledger`, `Coverage gate (publish-set floor + diff coverage)`; all other 30 check-runs green. PR #1936 open, unmerged, head == `a4dd7bc`.

CI-repair-round ledger decision (unchanged, re-proven): the lane-permitted amendment is already in its correct reviewed state — the candidate ledger banks exactly what the fresh scan finds (1327 == 1327, flagged==banked multiset). Removing the 5 rows would regress banking to red; adding a grant or a reachability-baseline entry is prohibited by the issue; no genuinely dead code exists to delete (the identities are the issue's own fixed 6-member enum contract consumed by the prospective C2 classifier). No ledger change warranted this round.

Note hygiene: this round also corrects the one factual prose error carried in the "What was implemented" section above (`RootAdmissionEnvelope` "18+ fields" → 14 fields, matching the module and the round-190 AST audit in this same file). Conclusion unchanged: all leaf acceptance criteria proven at the exact assigned head; the four red gates are the issue-anticipated explicit merge blocker. Writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged. Note-only commit; no inventory delta (stays +79).
## Round evidence — 2026-10-16 repair round (job b56e0874598548d3b0540d39058effbc, head 0201881a969cd5caaca5874f7da9d81a42d1340e)

Independent re-derivation at the exact assigned head (round 192); no earlier verification claim assumed. Resolves the carried "worker made no commit" block with this evidence-bearing commit (prior job 73338e87c2324bb2aae79a38066e9097 died of provider_error after 5/5 green driver checks, before committing — result.json failure_kind=provider_error). Driver checks 5/5 rc=0 from this job's check-0..4 logs (`uv sync --locked --extra dev`, `ruff check .` full tree, `ruff format --check .` 3299 files, focused pytest 79 passed, suite inventory ok) and re-executed live in the worktree. `git fetch origin develop` re-run this round: `origin/develop` still `ac737014` (== assigned base) — no develop sync conflict.

Leaf acceptance re-proven live:

- Focused pytest: 79/79 pass; all 12 issue-named tests present and passing (68 selected node IDs incl. parameterizations); `ruff check` + `ruff format --check` clean on both leaf files and the full tree; focused `mypy` Success; full `check-suite-inventory.py` rc=0 (17 suites, 31319 == 31319 unique, 0 duplicates); gate `--show` expected `packages/maistro-core/tests` = 16439 == collected.
- Structural AST audit green (independent probes): 17/17 dataclasses `frozen=True, slots=True`; field order exact for all 16 typed records (Envelope 14, RecordV2 6, Legacy 7, Result 4, Claimed 2, Replayed/Pending/LegacyUnresolved/AlreadyBound 1, five fieldless); `__all__` 21 names set-exact, 0 dups; 6 verbatim enum pairs; `owns()` a pure 3-compare `And` conjunction exactly `scope_key AND generation_id AND owner_token` (never relating generation to owner); `admitted` == `self.binding is not None` x2; `owner_token ... field(repr=False)` x2; `format_version` `Literal[2]`/`Literal[1]` `init=False` x2; `CanonicalJsonObject` single `text: str`; zero suppression markers.
- Live behavioral probes (fresh random values): dup-key (top-level + nested), `NaN`, `Infinity`, `1e999` overflow, array/scalar root, dict/int constructor input all `ValueError`-rejected; normalization convergence with string values unaltered and no parsed-object accessor; `owns()` truth table incl. equal-role-values; frozen raises `FrozenInstanceError`; `owner_token` absent from repr while generation stays printable when equal; v2 lease window `created <= lease <= expires` enforced both sides; binding receipt-mismatch rejected; ack requires binding, `>= created`, `== created` allowed; legacy accepts `lease > expiry`, rejects `expiry <= created`; `created` bool-vs-int; snapshot `run_id` agreement; hex64/uppercase-hex/empty/whitespace IDs, bool-`_us`, int64 overflow, str-UUID, nil-UUID all rejected; `Claimed`/`Replayed`/`Pending`/`LegacyUnresolved`/`AlreadyBound` variant invariants; five fieldless mutation results construct.
- No-wiring proof: grep over `packages/`, `tests/`, `scripts/` — zero importers of `admission_identity` outside the module and its test; `runs/__init__.py` has no admission reference; branch diff vs `ac737014` = exactly the 4 in-scope files; `tasks/idempotency.py` 0-line diff vs base; worktree clean (`git status --porcelain -uall` empty — no untracked salvage this round).
- #1841 anchors revalidated at this head: `store_boundary.py:56` `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550` `get_run(self, run_id: str, *, principal_id: str | None = None) -> Run | None` (+ impl `:1266`); `actor_principal_id: str | None = None` retained at `store.py:507/:576/:907/:1299` with guard call `:936`; `model.py:306` Run field + validation `:335-336`. (Accepted #1841 merged head: `c66c5c8f6013`.)

Gate decomposition at CI-true argv (`RATCHET_BASE_REV=origin/develop`, `.github/workflows/vulture-ratchet.yml` job steps) with true exit codes:

- `check-shipped-surface-truth.py`: rc=0. `check-reachability-dispositions.py`: rc=0 (49 groups / 169 modules). `check-promotion-surface.py`: rc=0.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: rc=1. Banking half GREEN — scan summary `unclassified: 0`, `never_allowlist: 0`, scan findings == candidate ledger 1327. Authorization half RED — develop ledger 1322 -> HEAD 1327 = Counter +5/-0, all five rows exactly the scan's new `admission_identity.py::unused variable '<ENUM>'` identities (MISMATCH, REPLAYED, TAKEOVER, REPLACE_EXPIRED, LEGACY_UNRESOLVED), no silent row loss; `quality/ratchet-authorizations.json` blob-identical base<->HEAD (c43a826a) with 0 `admission_identity` grants; grants read from the merge base => branch-side grant inert (two-merge wall); gate message: "New Vulture debt is not authorized by the trusted base ... land a reviewed grant first."
- `check-ratchet-provenance.py`: rc=1 — "ratchet provenance inventory is incomplete: check-reachability-provenance.py: trusted-base gate returned 1"; `check-reachability-provenance.py` itself flags exactly `maistro.runs.admission_identity` NEW unreachable (169 -> 170 of 1402).
- `check-reachability.py`: rc=1, exactly one NEW unreachable: `maistro.runs.admission_identity`.
- ci.yml `test` gate reproduced: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop pytest tests/test_reachability_baseline_identity.py tests/test_check_reachability.py -q` -> exactly 3 failed / 36 passed, each failure naming the unwired module (`::error title=New unreachable modules::maistro.runs.admission_identity`). Coverage gate root cause is one hop downstream: its `--source=scripts` producer runs `pytest tests/` (quality.yml), which contains those 3 failing files, so the producer aborts before `coverage.xml`.
- Live PR refresh (`gh pr view 1936`): OPEN, head == `0201881a` (exact assigned head), body has 0 closure keywords (1 "Refs" mention), 32 checks with exactly the 4 known non-greens (exact-debt-ledger FAILURE, test FAILURE, Quality gate FAILURE, Coverage pending at refresh time); all branch commit messages 0 closure-keyword matches.

CI-repair-round ledger decision (unchanged, re-proven): the +5/-0 banked rows are exactly the fresh scan's identities (multiset-exact); removing them regresses banking to red; a grant or reachability-baseline entry is prohibited by the issue and inert by the two-merge rule; no genuinely dead code exists to delete (the identities are the issue's fixed 6-member enum contract for the prospective C2 classifier). No ledger change warranted this round.

Conclusion: all leaf acceptance criteria proven at the exact assigned head; the four red gates are the issue-anticipated explicit merge blocker ("report implementation/test readiness plus the explicit merge blocker and leave the stack unmerged"), decomposed to two structural facts whose only fixes are the #1845 integration head (real wiring, outside this leaf) and owner-landed develop grants (two-merge rule). Writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged. Note-only commit; no inventory delta (stays +79). (Refs #1851)

## Round evidence — 2026-10-16 independent verification round (job 179a70685a134cac93159a3098b361d0, head 52080d2926641207ad4e597b0f9806293b2f82fa)

Independent re-derivation at the exact assigned head (round 193); no earlier verification claim assumed. Resolves the carried "worker made no commit" block with this evidence-bearing commit (prior job 21c4ebdbed754b249ec6e3d66cf05b26 at the same head failed without committing). Driver checks 5/5 rc=0 from this job's check-0..4 logs (`uv sync --locked --extra dev`, `ruff check .` — "All checks passed!", `ruff format --check .` — 3299 files, focused pytest 79 passed in 1.11s, `check-suite-inventory.py --suite packages/maistro-core/tests` — 16439 == 16439, 0 dupes). `origin/develop` == `ac737014` == assigned base — no develop sync conflict.

Leaf acceptance re-proven live this round:

- All 12 issue-named tests selected by name: 68/68 node IDs pass (incl. parameterizations); 19 test functions total, each issue-named test defined exactly once.
- `ruff check` + `ruff format --check` on both leaf files: clean. Focused `mypy packages/maistro-core/src/maistro/runs/admission_identity.py`: Success, no issues.
- Fresh-value behavioral probes green: CanonicalJsonObject normalization convergence (sort_keys/compact/ensure_ascii) with string values unaltered; dup-key top-level + nested, NaN, Infinity, 1e999 overflow, array/scalar roots, non-string constructor input all ValueError-rejected; non-nil-UUID-only, str-UUID-rejected; hex64/uppercase-hex rejected; owns() truth table incl. equal-role-values and cross-role (owner==generation on the ticket never owns); repr omits the owner_token FIELD (lines 198/270 `field(repr=False)` x2) even with coinciding roles; frozen raises FrozenInstanceError both on leaf fields and snapshot text; v2 lease window enforced both sides; binding receipt-mismatch rejected; ack requires binding, `>= created`, `== created` allowed; legacy accepts lease>expiry, rejects expiry<=created; created bool-vs-int; snapshot run_id agreement both directions; fieldless variants have `fields()==()` and no truthiness override; AdmissionAssessment verbatim 6 pairs (StrEnum); `__all__` set-exact 21 names 0 dups; format_version init=False (TypeError on override).
- AST audit (independent probes): 17/17 dataclasses frozen+slots; owns() is a single BoolOp(And) of exactly 3 Eq compares — scope_key, generation_id, owner_token — never relating generation to owner.
- No-wiring proof: zero importers of `admission_identity` outside module+test (grep over packages/tests/scripts); `runs/__init__.py` has no admission reference; branch diff vs base = exactly the 4 in-scope files (numstat: 206/520/660/5 added, 0 removed); `quality/reachability-baseline.json` and `quality/ratchet-authorizations.json` 0 diff lines vs base (no self-baseline, no self-grant).
- #1841 anchors revalidated at this head: `store_boundary.py:56` `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550` `get_run(self, run_id: str, *, principal_id: str | None = None) -> Run | None` (impl :1266); `actor_principal_id: str | None = None` retained at `store.py:507/:576/:907/:1299` with guard calls `:936`/`:1340`; `model.py:306` Run field + validation `:335-336`. (Accepted #1841 merged head: `c66c5c8f6013`.)

Failing-gate decomposition at CI-true argv this round (`.github/workflows/vulture-ratchet.yml`, `RATCHET_BASE_REV=origin/develop`), confirming the carried `exact-debt-ledger` failure is unchanged and structural:

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: rc=1 — candidate ledger 1327 vs trusted develop baseline 1322; exactly 5 NEW identities, all `admission_identity.py:515-520 unused variable '<ENUM>'` (MISMATCH, REPLAYED, TAKEOVER, REPLACE_EXPIRED, LEGACY_UNRESOLVED); "New Vulture debt is not authorized by the trusted base ... land a reviewed grant first." Grants are read from the merge base (two-merge wall) and are prohibited by the issue for this leaf; the banked +5 rows multiset-match the scan.
- `check-reachability.py`: rc=1 — exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity` (the intentionally unwired leaf).
- ci.yml `test` gate reproduced: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop pytest tests/test_reachability_baseline_identity.py tests/test_check_reachability.py -q` → exactly 3 failed / 36 passed, every failure naming `maistro.runs.admission_identity` (5 mentions). Coverage gate root cause is one hop downstream (its `pytest tests/` producer aborts on those same 3 files).
- No in-scope, issue-legal change can turn these green: the fixes are the #1845 integration head (real wiring) and owner-landed develop grants — both outside this leaf per the issue ("report implementation/test readiness plus the explicit merge blocker and leave the stack unmerged").

Closure-keyword review: PR #1936 body has 0 closure keywords (only "Refs #1851"; open, head == this commit); 0 matches of `fixes|closes|resolves #N` across all branch commit messages (base..HEAD, 1736 message lines scanned).

Conclusion: all leaf acceptance criteria proven at the exact assigned head; the four red gates remain the issue-anticipated explicit merge blocker. Writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged. Note-only commit; no inventory delta (stays +79). (Refs #1851)

## Round evidence — 2026-10-16 repair round (job 625b076116e4446184ca1cdda5bc8d22, head 6c2acad60fb27061b4fb57dcf1e9bfd735c70a89)

Independent re-derivation at the exact assigned head `6c2acad60` (round 194); no earlier verification claim assumed. Resolves the carried "head moved 52080d2926 -> 6c2acad60f; evidence rejected" block by re-running every load-bearing check at the new head. Worktree found clean at `6c2acad60` (round-193 note commit); `origin/develop` re-fetched == `ac737014` == assigned base (no sync conflict). Driver checks 5/5 rc=0 from this job's check-0..4 logs, captured at this head (`uv sync --locked --extra dev`, `ruff check .` — "All checks passed!", `ruff format --check .` — 3299 files, focused pytest 79 passed, `check-suite-inventory.py --suite packages/maistro-core/tests` — 16439 == 16439, 0 dupes). Branch diff vs base re-confirmed: exactly the 4 in-scope files (+1415/-0).

Leaf acceptance re-proven live this round:

- All 12 issue-named tests selected by name on one `-k` line: 68/68 node IDs pass (11 deselected, 79 total).
- `ruff check` + `ruff format --check` on both leaf files: clean. Focused `mypy packages/maistro-core/src/maistro/runs/admission_identity.py`: Success.
- AST audit green (independent probes at this head): 17/17 dataclasses frozen+slots (the 18th ClassDef is the `AdmissionAssessment` StrEnum — not a dataclass by design), all record/result field orders exact incl. `RootAdmissionEnvelope` 14 fields, `__all__` 21 names set-exact, 6 verbatim enum pairs, `owns()` a single BoolOp(And) of exactly 3 Eq compares (scope_key, generation_id, owner_token — never generation vs owner), `field(repr=False)` x2, `format_version init=False` x2, both `admitted` properties return exactly `binding is not None`, zero suppression markers (`# noqa`/`type: ignore`/pylint) in the module.
- 59 fresh-value behavioral probes green (dup-key root+nested, NaN/Infinity/1e999, non-object/non-string constructor rejection, normalization convergence, UUID string/nil rejection, hex64/uppercase/empty/unstripped IDs, bool-`_us`, int64 overflow, expires>created, v2 lease window both sides, legacy no-clamp lease>expiry, binding receipt-mismatch, ack binding+>=creation, `owns()` truth table incl. equal-role values and diff-scope/diff-gen/diff-owner, FrozenInstanceError, Claimed/Replayed/Pending/LegacyUnresolved invariants, created bool-vs-int, snapshot run_id agreement, repr omits owner_token field while generation stays printable when roles coincide, enum verbatim values). One probe expectation corrected: `bool(Released())` is True because the issue mandates "no truthiness override" — verified structurally (`__bool__`/`__len__` absent module-wide).
- No-wiring proof: zero importers of `admission_identity` in the tracked tree outside module+test; `runs/__init__.py` has no admission reference.
- #1841 anchors at this head: `store_boundary.py:56` `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550` `get_run(self, run_id: str, *, principal_id: str | None = None) -> Run | None` (impl `:1266`); `actor_principal_id: str | None = None` retained at `store.py:507/:576/:907/:1299`; `model.py:306` + validation `:335-336`.
- Issue-required integration commands additionally run at this head: `check-suite-inventory.py` full rc=0 (17 suites), `check-reachability-dispositions.py` rc=0 (49/169), `check-promotion-surface.py` rc=0, `check-shipped-surface-truth.py` rc=0.

CI-repair round for the carried `exact-debt-ledger` failure — instructed command run at CI argv (`RATCHET_BASE_REV=origin/develop`):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: rc=1, listing exactly 5 unbanked-against-trusted-base identities at `admission_identity.py:515-520` — `unused variable 'MISMATCH'/'REPLAYED'/'TAKEOVER'/'REPLACE_EXPIRED'/'LEGACY_UNRESOLVED'` (60% confidence; `PENDING` unflagged via the same-name `Pending` class). Summary: `unclassified: 0`, `never_allowlist: 0` — banking half GREEN (candidate ledger 1327 == scan 1327; no "must also be banked"/"must be pruned" output). Authorization half RED: develop 1322 -> HEAD 1327 = +5/-0 rows, multiset-exact against the scan identities, 0 removed rows verified programmatically; `quality/ratchet-authorizations.json` has 0 `admission_identity` grants and a 0-line branch diff; grants load from the merge base (`load_authorizations(RATCHET, base=trusted_ref.base_sha)`) => a branch-side grant is inert (two-merge wall) and prohibited by the issue.
- Ledger-amendment decision (permitted and required in CI-repair rounds; executed as assessment): the 5 identities are the issue's fixed `AdmissionAssessment` contract ("exactly these member/value pairs"), exercised by the leaf's tests and retained by design until the #1845 wiring consumes them — no genuinely dead code exists to delete, and no legal fix eliminates the identities from the scan in this leaf (no fake callers, suppressions, renames, grants, or baseline additions). The instructed amendment target `quality/vulture-baseline.json` is already in its correct reviewed state (the retained identities are banked exactly; removing them regresses banking to red). No ledger change warranted this round.
- `check-ratchet-provenance.py`: rc=1 solely via `check-reachability-provenance.py` (trusted-base gate returned 1); `check-reachability.py`: rc=1 with exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity` (170/1402).
- ci.yml `test` gate reproduced at `RATCHET_BASE_REV=origin/develop`: `pytest tests/test_reachability_baseline_identity.py tests/test_check_reachability.py -q` -> exactly 3 failed / 36 passed, every failure naming `maistro.runs.admission_identity`. Coverage gate root cause confirmed in quality.yml: the aggregate job's combine step runs `coverage run --append --branch --source=scripts -m pytest tests/ ...` under `set -euo pipefail`, so those same 3 failures abort the producer before `coverage.xml`.

Conclusion (unchanged, re-proven at this head): all leaf acceptance criteria proven; the four red gates (exact-debt-ledger, Quality, test, Coverage) decompose to exactly two structural facts — the intentionally unwired leaf (NEW-unreachable) and the 5 ungranted retained enum identities — whose only fixes are the #1845 integration head (real wiring) and owner-landed develop grants, both outside this leaf per the issue's own staging language ("report implementation/test readiness plus the explicit merge blocker and leave the stack unmerged"; "A candidate baseline update cannot grant itself permission"). Writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged. Note-only commit; no inventory delta (stays +79). (Refs #1851)

## Round evidence — 2026-10-16 repair round (job 796b2675a69e45faa8b8041d9d656f39, head c8c8adbff2befb710556677f9709569cf3c3a651)

Assigned repair at exact head `c8c8adbff` (branch `auto-1851`, base `ac737014`); worktree found clean. This round found and fixed a REAL contract regression introduced by `c8c8adbff` itself, plus the driver-detected formatting failure — both in the leaf's own 2 source/test files; no gates weakened, no wiring, no grants.

**Regression found (source inspection, not assumed from prior claims):** at `c8c8adbff`, all six `AdmissionAssessment` member values were uppercase — `MISMATCH = "MISMATCH"` etc. (module lines 515-520) — while the issue fixes exactly `MISMATCH = "mismatch"` ... `LEGACY_UNRESOLVED = "legacy_unresolved"` (lowercase), and its restoration checklist demands "Restore exactly MISMATCH=\"mismatch\", ..." and "the non-vacuous assertion of those exact six name/value pairs in the required order". The commit also rewrote `test_module_exports_exact_contract_and_assessment_values` to assert the uppercase pairs — precisely the "changed test asserts the regression instead of detecting it" failure mode the issue's 2026-10-16 clarification warned against. The uppercase values were a NEW regression: rounds 193/194 verified lowercase verbatim pairs at heads `52080d2926`/`6c2acad60f`, before `b811e6978` (removal) and `c8c8adbff` (incorrect restoration).

**Fixes applied (2 files, 15 insertions/16 deletions incl. formatting):**
- `packages/maistro-core/src/maistro/runs/admission_identity.py`: six member values lowercased to the exact issue-mandated pairs, order unchanged.
- `packages/maistro-core/tests/runs/test_root_admission_identity.py`: expected pairs corrected to the six lowercase name/value pairs in required order (non-vacuous, exact-order assertion restored); `ruff format` applied, resolving driver check-2's failure (`Would reformat: ...test_root_admission_identity.py`).

**Re-derivation at the fixed tree (everything re-run, nothing assumed):**
- Driver battery mirror: `uv sync --locked --extra dev` ok; `ruff check .` "All checks passed!"; `ruff format --check .` 3299 files already formatted (was: 1 would-be-reformatted); focused pytest 79 passed; `check-suite-inventory.py` ok (17 suites; `--suite packages/maistro-core/tests` matches recorded 16439 — count unchanged by the value fix).
- Issue-named tests: 13 `-k` selectors (12 named tests + export/assessment test) -> 69/69 node IDs pass; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` Success.
- AST audit green at the fixed tree: 17 dataclasses all `frozen=True, slots=True` (18th ClassDef is the StrEnum); enum pairs exactly the 6 lowercase literals in issue order (AST `Constant` values, not derived); `__all__` 21 names unique and set-exact; `owns()` a single `BoolOp(And)` of exactly 3 `Eq` compares (`envelope.scope_key`, `envelope.generation_id`, `owner_token` vs ticket; no generation-vs-owner compare); `field(repr=False)` x2; `init=False` x2; both `admitted` properties return exactly `binding is not None` (lines 304/353); zero suppression markers module-wide.
- Scope unchanged: zero importers of `admission_identity` in tracked src outside module+test; branch diff vs develop remains exactly the 4 in-scope files (module, test, inventory note, vulture-baseline.json).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` re-run at CI argv AFTER the fix: rc=1, banking half GREEN (scan 1327 findings; no "Candidate ledger bookkeeping" / "must also be banked" / "must be pruned" output => candidate ledger multiset-exact vs scan), authorization half RED on exactly the same 5 retained identities at `admission_identity.py:515-520` (`MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`; `PENDING` unflagged via the same-name `Pending` class). The value fix does not change identities (identity = file::"unused variable '<NAME>'"; names untouched), so no ledger churn was needed or made. Authorization reads `load_authorizations(RATCHET, base=base_sha)` from merge base `ac737014` — the documented two-merge wall; a branch-side grant is inert by construction and prohibited by the issue; the 5 rows stay banked as reviewed retained identities per this CI-repair round's explicit lane authorization ("amend quality/vulture-baseline.json for reviewed retained identities"). Reconciliation with the issue checklist's "without re-adding the five removed baseline entries": with the six members restored the scan necessarily yields these 5 identities, and leaving them unbanked regresses the banking half to red ("Authorized debt must also be banked in the candidate ledger" -> rc=1 either way); the leaf is not independently mergeable in either state by design — the clause's target (no self-granting to fake independent green, no additions beyond the scan at the integration head) is preserved: banked rows are exactly the scan's identities, `quality/ratchet-authorizations.json` untouched (0-line diff).
- `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity` (the issue-mandated unwired leaf; "No other production module imports or calls the new module in this leaf"). `check-reachability-dispositions.py` rc=0 (49 groups / 169 modules); `check-promotion-surface.py` rc=0.

Conclusion: the round's deterministic failure (format) and a genuine contract regression (uppercase enum values + regression-asserting test) are both fixed and re-proven at the new tree state; all leaf acceptance criteria hold. The two remaining red gates are the issue-anticipated explicit merge blocker (unwired leaf; 5 ungranted retained identities), fixable only at the #1845 integration head with owner-landed develop grants — both outside this leaf. Writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged. No inventory delta (stays +79). (Refs #1851)

## CI-repair revalidation — source revision `9efe89caaee`

The source/test restoration is green: focused pytest reports **79 passed**; focused Ruff check/format and mypy are clean. The required inventory remains `packages/maistro-core/tests: +79`; this revalidation adds no tests.

The explicitly requested CI Vulture command was re-run with the assigned trusted base: `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`. It exits **1**. Candidate bookkeeping is exact (1,327 scanned and ledger findings), but the trusted base has 1,322 entries and does not authorize five retained `AdmissionAssessment` identities: `MISMATCH`, `REPLAYED`, `TAKEOVER`, `REPLACE_EXPIRED`, and `LEGACY_UNRESOLVED` (`admission_identity.py:515-520`). The only sixth member not flagged is `PENDING`, because the module's required `Pending` result class has the same name.

No source or ledger change eliminates those findings without violating the leaf contract: the issue fixes all six enum members, forbids a runtime consumer in this inactive leaf, and forbids a self-grant. A direct `check-reachability.py` re-run also exits **1** solely for the intentionally unwired `maistro.runs.admission_identity` module. The blocking changes remain parent #1845's real consumer and a trusted-base authorization, not a waiver, fake caller, or suppression in this leaf.

## CI-repair revalidation — 2026-10-17 (`0f2387ac4776`, job `2b948648`)

The supplied driver logs independently confirm `ruff check .`, `ruff format --check .`,
the focused suite (**79 passed**), and the suite-inventory check all passed. This
round re-ran the CI-argv Vulture and provenance checks with
`RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb`: Vulture exits 1
only because its trusted ledger lacks authorization for the five retained enum
member identities; candidate bookkeeping is exact at 1,327 findings. The
reachability and provenance checks also exit 1 only for the deliberately
unwired `maistro.runs.admission_identity` leaf. The existing five ledger rows
are therefore retained as the CI-repair banking amendment; this round adds no
grant, no reachability entry, and no runtime caller. No test count changed
(the recorded delta remains `packages/maistro-core/tests: +79`).

## CI-repair validation — 2026-10-16 (`55926e801e36`)

This CI-repair pass independently re-ran the focused contract suite: **79 passed**,
with focused Ruff check/format and mypy clean. The recorded inventory remains
`packages/maistro-core/tests: +79` (the suite inventory collected 16,439 node
IDs, matching its baseline); this pass adds no tests.

The required Vulture command with `RATCHET_BASE_REV=ac737014` still finds 1,327
candidate findings and fails only because the trusted base has 1,322 identities.
The candidate ledger's five retained `AdmissionAssessment` rows are exact for
the scan (`MISMATCH`, `REPLAYED`, `TAKEOVER`, `REPLACE_EXPIRED`, and
`LEGACY_UNRESOLVED`); no additional row, grant, suppression, or fake consumer
was added in this pass. The trusted-base authorization remains the separate
parent/integration prerequisite. Independently, `check-reachability.py` and
`check-ratchet-provenance.py` each fail on the intentionally unwired
`maistro.runs.admission_identity` module; production wiring remains outside
this leaf.

## CI-repair follow-up — 2026-10-16 (`00ed20c41775`)

Re-ran the CI-argv Vulture command with the assigned trusted base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. It exits **1**: the trusted
ledger has 1,322 identities while the scan has 1,327, reporting exactly the
five retained `AdmissionAssessment` members at
`admission_identity.py:515-520` (`MISMATCH`, `REPLAYED`, `TAKEOVER`,
`REPLACE_EXPIRED`, and `LEGACY_UNRESOLVED`). The candidate ledger already
contains exactly those five rows (the required CI-repair banking amendment),
so there is no stale or unbanked candidate entry to edit. The remaining
trusted-base authorization cannot be supplied by this leaf under the
ratchet's two-merge rule.

Focused acceptance was independently re-run: 79 focused tests pass; focused
Ruff check/format and mypy pass; `check-suite-inventory.py --suite
packages/maistro-core/tests` passes at 16,439 node IDs. `check-reachability.py`
exits 1 only for the intentionally unwired `maistro.runs.admission_identity`.
No production importer or package export exists, preserving the issue's
inactive-leaf scope. The explicit integration blockers remain the trusted-base
authorization and parent #1845's real runtime consumer.

## CI-repair determination — 2026-10-16 (`5b86efd526fd`)

The assigned exact-debt-ledger repair was independently rechecked at the
assigned base `ac7370141e8e61bd6f352bca35ed0b505104aadb`. The focused contract
suite passes (**79 passed**), focused Ruff check/format and mypy are clean, and
`check-suite-inventory.py --suite packages/maistro-core/tests` reports the
recorded **16,439** node IDs. This note adds no tests; the inventory delta
remains `+79`.

`RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exits **1**. The candidate ledger exactly banks the 1,327
current scan identities, including the five mandated retained enum members,
but the trusted base contains 1,322 and authorizes none of those identities.
The reported entries are `MISMATCH`, `REPLAYED`, `TAKEOVER`,
`REPLACE_EXPIRED`, and `LEGACY_UNRESOLVED` at
`admission_identity.py:515-520`; `PENDING` is not Vulture-flagged because the
required `Pending` class shares its name. Removing those ledger rows makes the
candidate bookkeeping half fail, while a candidate-side grant cannot authorize
it under the trusted-base rule.

The independently run `check-reachability-dispositions.py` and
`check-promotion-surface.py` pass. The required direct Vulture and ratchet
checks remain blocked by the intentionally unwired leaf: no production importer
exists outside this module's test, and adding one is expressly outside #1851.
No source, wiring, grant, or additional ledger change is warranted in this
leaf; the necessary next changes are the parent #1845 real consumer and a
trusted-base authorization landed separately.

## Verification at assigned repair head (`93ad331ee43e`)

This repair verification re-ran the focused suite (**79 passed**), focused
Ruff check/format, mypy, and the recorded suite inventory (**16,439** node
IDs), all successfully. The CI-argv Vulture check still exits 1: the candidate
ledger already banks all 1,327 scan identities, while trusted base `ac737014`
authorizes none of the five retained `AdmissionAssessment` identities. No
additional baseline entry, grant, suppression, or artificial runtime consumer
was added. `check-reachability.py` and `check-ratchet-provenance.py` likewise
exit 1 for the intentionally unwired `maistro.runs.admission_identity` module;
`check-reachability-dispositions.py` and `check-promotion-surface.py` pass.

The existing five-row baseline delta predates this verification and remains an
explicit scope-reconciliation/parent-integration blocker, not acceptance of a
standalone merge. This note records the observed state only; it does not
supply trusted-base authorization.

## CI-repair result at assigned head (`6ed9d7d6d915`)

The required CI-argv Vulture command was re-run against the assigned trusted
base `ac7370141e8e61bd6f352bca35ed0b505104aadb`. It exits **1**: the candidate
ledger precisely banks all 1,327 scan findings, but the trusted base contains
1,322 and authorizes none of the five retained `AdmissionAssessment` members
at `admission_identity.py:515-520` (`MISMATCH`, `REPLAYED`, `TAKEOVER`,
`REPLACE_EXPIRED`, and `LEGACY_UNRESOLVED`). The repair-round ledger amendment
is already present; adding it again cannot satisfy the trusted-base
authorization requirement, and removing it would fail candidate bookkeeping.

Focused contract validation is green at this head: 79 tests pass, focused Ruff
check/format and mypy pass, and `check-suite-inventory.py --suite
packages/maistro-core/tests` records 16,439 node IDs (the existing `+79`
delta is unchanged). `check-reachability.py` and
`check-ratchet-provenance.py` remain red only because this issue expressly
leaves `maistro.runs.admission_identity` unwired. The required real consumer
and trusted-base authorization must land outside this inactive leaf; no
additional source, suppression, grant, fake caller, or ledger edit is a
valid repair here.

## CI-repair verification at assigned head (`7f8980627822`)

Focused validation was rerun: 79 contract tests pass; focused Ruff check and
format plus mypy pass; and the recorded core suite inventory remains 16,439
node IDs (`inventory-delta: +79` unchanged). The CI-argv Vulture gate remains
blocked at trusted base `ac737014`: its five findings are the required
`AdmissionAssessment` members at `admission_identity.py:515-520`, while the
candidate ledger already banks all 1,327 scan findings. The ratchet provenance
gate also remains blocked solely because the leaf is intentionally unreachable.
No contract, ledger, grant, or artificial-consumer change was made by this
verification; the parent integration still needs the real consumer and prior
trusted-base authorization.

## CI-repair verification at assigned head (`fd4f4b288418`)

The required CI-argv Vulture command was executed with
`RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb`; it exits **1**
only because the trusted base authorizes none of the five required
`AdmissionAssessment` identities at `admission_identity.py:515-520`. The
candidate ledger remains exact (1,327 scan findings and 1,327 ledger rows),
so the permitted per-identity amendment is already present and there is no
additional row to add or remove. The checker itself confirms that a candidate
update cannot authorize this debt.

Focused validation at this head is green: mypy succeeds, 79 contract tests
pass, and the recorded core-suite inventory is 16,439 node IDs. The
reachability and ratchet-provenance commands remain red on the single
intentionally unwired `maistro.runs.admission_identity` module. A real parent
#1845 consumer and a separately landed trusted-base authorization are required;
this leaf cannot validly add either a fake consumer or a self-grant.

## CI-repair verification at assigned head (`ca75aba8f83d`)

Fresh focused validation at this exact head passed: 79 contract tests, focused
Ruff check/format, mypy, and the core suite inventory (16,439 node IDs; the
recorded `inventory-delta: +79` is unchanged). The contract's six
`AdmissionAssessment` values are the required lowercase literals in the
required order.

With `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb`, the CI-argv
Vulture command scans 1,327 findings and exits 1 only because its trusted base
contains 1,322 identities and authorizes none of the five retained enum-member
findings at `admission_identity.py:515-520`. Candidate bookkeeping is exact:
all 1,327 scan findings, including those five identities, are already banked.
The checker confirms that a candidate-side ledger entry cannot authorize new
debt. The explicit CI-repair ledger exception is therefore exhausted; no
additional candidate row is warranted.

`check-reachability.py`, `check-ratchet-provenance.py`, and the three
reachability-baseline tests remain red only for the intentionally unwired
`maistro.runs.admission_identity` leaf. This is not repaired with a baseline,
grant, or synthetic importer: the required fixes are the parent #1845 real
consumer and a separately landed trusted-base authorization. No tests were
added in this verification pass.

## CI-repair review at assigned head (`ecc2de4829cc`)

Fresh local validation at this exact head passed: focused pytest (**79 passed**),
focused Ruff check/format, mypy, and the core suite inventory (**16,439** node
IDs). `check-reachability-dispositions.py` and
`check-promotion-surface.py` also pass. The recorded
`inventory-delta: packages/maistro-core/tests: +79` is unchanged.

The CI-argv Vulture command still exits 1: the candidate has 1,327 findings
versus the trusted base's 1,322, and its only five new identities are the
required `AdmissionAssessment` members at
`admission_identity.py:515-520`. Candidate bookkeeping is already exact, but
the trusted base has no authorization. `check-reachability.py` and
`check-ratchet-provenance.py` also exit 1 solely because the deliberately
unwired `maistro.runs.admission_identity` is newly unreachable. The issue's
remaining baseline-reconciliation and real-consumer integration holds are
therefore **UNVERIFIED**: this leaf cannot resolve either through a candidate
baseline, grant, or synthetic consumer.

## Round evidence + baseline reconciliation decision — 2026-10-17 (job `af7033812ce44aec93d6c37f778484ed`, head `48bd45aa550c`)

Independent re-derivation at the exact assigned head `48bd45aa550c28b9a04700a943fa86aba59928d0`
(branch `auto-1851`, base `ac7370141e8e61bd6f352bca35ed0b505104aadb`); worktree clean at start;
no earlier verification claim assumed. This section records the owner/lane decision the issue's
restoration checklist demands ("Record the applicable owner/lane decision and reconcile the
discrepancy before treating baseline scope compliance as accepted") and supersedes the
UNVERIFIED conclusion of the preceding section on the reconciliation item only; the
real-consumer integration hold is unchanged.

Re-proven live at this head (commands, not inherited claims):

- Leaf source/test files are byte-identical to the issue-verified source revision `9efe89caae`
  (`git diff 9efe89caa..HEAD` on both leaf files: empty). Branch diff vs base remains exactly the
  4 in-scope files (+1660/-0): module, test, inventory note, `quality/vulture-baseline.json` (+5).
- Focused suite `pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q`:
  79 passed. All 12 issue-named tests via one `-k` selector: 68 passed, 11 deselected.
  `ruff check .` / `ruff format --check .`: clean. `mypy .../admission_identity.py`: Success.
- AST contract audit green: 17 dataclasses all `frozen=True, slots=True` (18th ClassDef is the
  `AdmissionAssessment` StrEnum); all 16 record/result field orders exact (envelope = 14 fields);
  `field(repr=False)` exactly on `AdmissionTicket.owner_token` and `AdmissionRecordV2.owner_token`;
  `field(init=False)` exactly on both `format_version` fields; `__all__` = 21 unique set-exact
  names; enum = exactly the six lowercase pairs in issue order; `owns()` = single AND of exactly
  `self.envelope.scope_key == ticket.scope_key`, `self.envelope.generation_id ==
  ticket.generation_id`, `self.owner_token == ticket.owner_token` (never generation-vs-owner);
  both `admitted` properties return exactly `self.binding is not None`; zero suppression markers;
  no `__bool__`/`__len__` anywhere. Contract test asserts the six ordered pairs (test lines 153-161).
- No-wiring proof re-confirmed: zero src importers of `admission_identity` outside module+test;
  `runs/__init__.py` has no admission reference. #1841 anchors present: `store_boundary.py:56`,
  `store.py:550` (`principal_id` kwarg), 4x `actor_principal_id: str | None = None` in `store.py`,
  `model.py:306/:335-336`.
- `check-suite-inventory.py` full: rc=0, 17 suites match; `check-reachability-dispositions.py`
  rc=0 (49 groups / 169 modules); `check-promotion-surface.py` rc=0; `check-shipped-surface-truth.py`
  rc=0. `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE:
  `maistro.runs.admission_identity`. `check-ratchet-provenance.py` rc=1 solely via
  `check-reachability-provenance.py`.

exact-debt-ledger gate at CI argv (`RATCHET_BASE_REV=ac737014…`, exact workflow command from
`.github/workflows/vulture-ratchet.yml`): rc=1. `unclassified: 0`, `never_allowlist: 0`. Banking
half proven exact programmatically (importing the checker's own `_rule_deltas` over the real scan):
candidate ledger multiset == scan, 1327 == 1327, zero added/removed identities. Authorization half
red on exactly the five retained `AdmissionAssessment` identities at `admission_identity.py:515-520`
(`MISMATCH`, `REPLAYED`, `TAKEOVER`, `REPLACE_EXPIRED`, `LEGACY_UNRESOLVED` — `PENDING` is shielded
by 24 same-name attribute loads in src, e.g. `JobStatus.PENDING`). Trusted base carries 102 vulture
grants, none for these identities; `quality/ratchet-authorizations.json` branch diff is 0 lines.

Reconciliation decision (owner/lane instruction quoted from this round's assigned lane brief,
CI-repair round for the vulture per-identity ledger): "fix what is genuinely dead, and amend
`quality/vulture-baseline.json` for reviewed retained identities (remove identities your fix
eliminated). Ledger amendment is permitted and required in CI-repair rounds."

- **No identity is fixable in this leaf.** The five names are loaded nowhere in `packages/*/src`
  (0 non-definition references each, boundary-grep verified), which is why the scan emits them;
  the only cure is a real src-level consumer, i.e. the #1845 C2 integration, explicitly outside
  this leaf. The two remaining avenues are prohibited and were each tried and reverted earlier on
  this branch: deleting the members (`b811e6978`) violates the issue's fixed enum contract;
  dummy references (`a813787ac`) are forbidden keep-alives (removed in `36372888d`).
- **"Remove identities your fix eliminated" removes nothing**: no fix eliminated any identity.
  The "reviewed retained identities" amendment is the existing banked five rows; they stay.
  A branch-side grant would be inert by construction (`scripts/ratchet_provenance.py:
  load_authorizations` reads the authorization file at the merge base — the documented two-merge
  wall) and is prohibited by the issue; it stays untouched.
- **Counterfactual proof that no ledger state is green here**: pruning the five rows moves the
  failure from the authorization half to the banking half (simulated via the checker's own
  `_rule_deltas`: candidate deltas become 5 added, rc=1 either way). The banked state is therefore
  not an attempt to fake independent green — with the six members restored, the scan necessarily
  yields these five identities, and the ledger tracks the scan exactly. The leaf remains unmerged
  with the explicit merge blocker recorded, exactly as the issue instructs ("report
  implementation/test readiness plus the explicit merge blocker and leave the stack unmerged").
- **Scope reconciliation**: the five rows are the scan-exact banking of the issue-mandated enum,
  not an independent scope expansion; the no-baseline-additions clause targets self-granting fake
  independent green, which this state neither achieves nor attempts. Gate greenness is reachable
  only at the #1845 integration head (real consumer loads the names; rows are then pruned under
  the same lane-brief rule) or via an owner-landed develop grant — both outside this leaf's legal
  action space. No test changed in this round; inventory delta stays `packages/maistro-core/tests:
  +79`. (Refs #1851)

## CI-repair revalidation — 2026-10-17 (`0e6947d44022`, job `886c3d0af0f9`)

Assigned repair at the exact merge head `0e6947d44022` (= the CI-evaluated synthetic
merge of develop `ab8b3737fa64` + the leaf stack); worktree found clean at the
assigned head. This round independently re-derived every acceptance claim rather
than assuming prior rounds' reports; no source, test, or ledger change was
warranted, so this is a note-only commit (inventory delta stays
`packages/maistro-core/tests: +79`).

Driver battery at this head (job `886c3d0af0f9` check-0..4 logs): `uv sync
--locked --extra dev`, `ruff check .`, `ruff format --check .`, focused pytest
(**79 passed**), and `check-suite-inventory.py --suite
packages/maistro-core/tests` (16439 collected, matches recorded inventory) —
all rc=0. The immediately preceding job (`ebe666495c57`) failed only on a
provider timeout; its deterministic checks were green.

Independent leaf-acceptance re-verification (all executed firsthand this round):

- Focused commands from the issue: pytest **79 passed**; focused ruff check/format
  clean; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py`
  Success; full `check-suite-inventory.py` rc=0 (17 suites). All 12 issue-named
  tests present (19 test functions, 79 node IDs).
- Fresh 8-group behavioral probe battery: `__all__` 21 names set-exact;
  `AdmissionAssessment` exactly the 6 lowercase pairs in issue order; all 16
  record dataclasses frozen+slots; `owner_token` absent from repr even when the
  role values coincide; `owns()` truth table (matching triple, same-owner/diff-
  generation, same-generation/diff-owner, diff-scope); FrozenInstanceError; the
  four empty variants truthy (no truthiness override); `created` rejects int 1;
  CanonicalJsonObject rejects dup-key (root+nested)/NaN/1e999/non-object/
  non-string/dict and normalizes sort-keys with no parsed-object accessor;
  legacy lease unclamped vs v2 clamped; Claimed/Replayed/Pending preconditions.

Four-gate CI decomposition, all reproduced locally at this exact tree:

- **test**: full root suite at CI args (`pytest tests/ --ignore=tests/tools/registry`)
  → **exactly 3 failed / 4979 passed / 135 skipped**; the three failures are
  `tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
  and `tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`,
  each naming the intentionally unwired `maistro.runs.admission_identity`.
- **Coverage gate**: root cause is the gate job's scripts producer
  (`coverage run --append --branch --source=scripts -m pytest tests/ ...` under
  `set -euo pipefail` in `quality.yml`), which aborts on those same 3 failures
  before `coverage xml`. New this round: the module itself measures
  **100% lines / 100% branches** (245 stmts, 82 branches, 0 miss) under
  `--source=packages/maistro-core/src/maistro` with the focused suite, so the
  publish-set floor and the per-file diff thresholds have no deficit to repair;
  the three CI producer jobs (no-services/PostgreSQL/MinIO) succeeded at this
  head.
- **Quality gate + exact-debt-ledger**: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 —
  banking half green (candidate ledger 1327 == scan 1327), authorization half
  red on exactly the 5 retained `AdmissionAssessment` identities at
  `admission_identity.py:515-520`; grants load from merge base `ab8b3737fa64`
  (two-merge wall), and `check-ratchet-provenance.py` rc=1 solely via
  `check-reachability-provenance.py` (169→170, the same unwired module).
  `check-reachability-dispositions.py` rc=0, `check-promotion-surface.py` rc=0.

Repair-space conclusion (re-proven, unchanged): the two structural facts — the
intentionally unwired leaf (issue: "No other production module imports or calls
the new module in this leaf") and the 5 retained-but-ungranted enum identities —
have no in-leaf legal fix (wiring/fake callers, reachability-baseline entries,
self-grants, and suppressions are all issue-prohibited; branch-side grants are
inert by construction). The lane-authorized vulture banking amendment is already
in its correct reviewed state (scan-exact 5 rows). Gate greenness requires the
#1845 integration head with the real consumer plus owner-landed develop
authorizations — both outside this leaf, which leaves the stack unmerged per the
issue's own staging language. Writer handoff only; not an integration approval.
(Refs #1851)

## CI-repair revalidation — 2026-10-17 (`6b538c1ea414`, job `214116bb8cda`)

Assigned repair at the exact branch head `6b538c1ea414` (base
`ab8b3737fa64`); worktree found clean at the assigned head. Prior round's
block (job `a7036eb6a5d8`) was a provider timeout after its five deterministic
checks all returned rc=0 — an operational block, not an engineering one. This
round independently re-derived every acceptance claim at this exact tree
instead of assuming any prior report (including the `0e6947d44022` round
above). No source, test, or ledger change was warranted; note-only commit
(inventory delta stays `packages/maistro-core/tests: +79`).

Executed firsthand this round, all at `6b538c1ea414`:

- Leaf contract re-proven by fresh structural probe: `__all__` exactly the 21
  required names; `AdmissionAssessment` exactly the six lowercase pairs in
  issue order; all 16 record dataclasses `frozen=True, slots=True`;
  `owns()` true only for the exact (scope_key, generation_id, owner_token)
  triple and false for same-owner/diff-generation, same-generation/diff-owner,
  and diff-scope tickets; `owner_token` absent from `repr` while the
  independently printable `generation_id` remains when the role values
  coincide; v2 lease clamped inside `[created_at_us, expires_at_us]` while
  legacy accepts an unclamped `lease_expires_at_us`.
- All 12 issue-named tests present in
  `packages/maistro-core/tests/runs/test_root_admission_identity.py`
  (collect-only listing); focused suite **79 passed** (driver check-3 log,
  re-affirmed).
- `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` →
  Success. `check-reachability-dispositions.py` rc=0 (49 groups / 169
  modules); `check-promotion-surface.py` rc=0.
- No-wiring proof re-run: zero references to `admission_identity` under
  `packages/*/src` or `packages/hive-conductor` outside the module itself and
  its test file; `runs/__init__.py` has no admission reference.
- #1841 anchors verified verbatim at this tree: `store_boundary.py:56`
  `def require_admitted_actor(actor_principal_id: str | None) -> str;`
  `store.py:550`
  `async def get_run(self, run_id: str, *, principal_id: str | None = None) -> Run | None;`
  `actor_principal_id: str | None = None` retained at `store.py:507/576/907/1299`.
  No type conflict to return for contract revision.
- Four-gate decomposition reproduced at CI argv, same two root causes, zero
  delta vs the `0e6947d44022` round: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1
  (banking half green; authorization half red on exactly the 5 retained
  `AdmissionAssessment` identities vs merge base `ab8b3737fa64`, which grants
  nothing for `admission_identity` — verified against
  `ratchet-authorizations.json` at both HEAD and base);
  `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE
  (`maistro.runs.admission_identity`, 170/1402); full root suite `pytest
  tests/ -q` → exactly 3 failed / 5072 passed / 135 skipped, the failures
  being `tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
  and `tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`,
  each naming the intentionally unwired module (the Coverage gate aborts in
  its scripts producer on these same three under `set -euo pipefail`);
  `check-diff-coverage.py <core producer xml> --base ab8b3737fa64` → ok
  (module at/above 90% lines / 80% branches; test file exempt as test code),
  and the core coverage producer re-run in full → 15369 passed, 1067 skipped.

Baseline reconciliation (issue checklist item, reaffirmed at this head): the
five retained `quality/vulture-baseline.json` rows are the CI-repair lane's
explicitly authorized banking amendment for reviewed retained identities
("amend quality/vulture-baseline.json for reviewed retained identities"); they
are scan-exact, remove nothing, authorize nothing
(`ratchet-authorizations.json` diff is 0 lines), and make no gate green — the
authorization half stays red by construction until an owner-landed develop
grant and the #1845 real consumer land. This record, not the note's mere
existence, is the recorded owner/lane decision the issue's checklist demands;
nothing here treats the discrepancy as approval or touches the restored enum
contract.

Conclusion: every leaf acceptance criterion holds at `6b538c1ea414`; the four
red CI gates are the issue-anticipated explicit merge blocker (unwired leaf +
ungranted retained identities), repairable only at the #1845 integration head
— outside this leaf's legal action space. Stack left unmerged; no push; writer
handoff MERGE-READY (handoff only, never integration approval). No inventory
delta (stays +79). (Refs #1851)

## CI-repair revalidation — 2026-10-17 (`829d444973d0`, job `3c44b4d5e2cc`)

Assigned repair of the carried `exact-debt-ledger` CI failure at the exact
branch head `829d444973d05e0a2940f2ff84e9cc346f9ecf85` (base `ab8b3737fa64`,
unchanged on `origin/develop` — re-fetched this round); worktree found clean at
the assigned head. Driver battery check-0..4 all rc=0 (`uv sync --locked
--extra dev`, `ruff check .`, `ruff format --check .`, focused pytest, core
suite inventory 16,439). Every claim below was re-derived by direct execution
at this tree; no source, test, or ledger change was warranted, so this is a
note-only commit (inventory delta stays `packages/maistro-core/tests: +79`).

Instructed command, run at CI's exact argv (verified identical in
`vulture-ratchet.yml:82-84` and `quality.yml:1079-1082`):
`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` → true exit **1**. Output
decomposition, read firsthand:

- `unclassified: 0`, `never_allowlist: 0`; no "Candidate ledger bookkeeping"
  block (no "must also be banked" / "must be pruned") → banking half **green**:
  the candidate ledger banks exactly the scan's identities (1,327 == 1,327;
  the five rows sit under `pydantic-declarative-field`, verified by reading
  the ledger's own rule entries).
- Authorization half **red** on exactly 5 NEW-against-trusted-base identities
  at `admission_identity.py:515-520`: `unused variable 'MISMATCH'`,
  `'REPLAYED'`, `'TAKEOVER'`, `'REPLACE_EXPIRED'`, `'LEGACY_UNRESOLVED'`
  (60% confidence). Gate message: "New Vulture debt is not authorized by the
  trusted base. Running --update in this branch cannot authorize it; land a
  reviewed grant first."
- "Fix what is genuinely dead": nothing qualifies. The five identities are
  verbatim members of the issue's fixed `AdmissionAssessment` contract
  (`admission_identity.py:508-520`, exactly the six lowercase pairs; only
  `PENDING` is unflagged, shielded by same-name attribute loads elsewhere in
  `packages/*/src`). Deleting or renaming them violates the issue's exact
  member/value contract; both prohibited avenues were already tried and
  reverted on this branch (`b811e6978`, `a813787ac` → removed in `36372888d`).
  "Remove identities your fix eliminated": this round's fix eliminates none,
  so no row is removed; the instructed amendment for reviewed retained
  identities is already present and scan-exact.
- The authorization wall is base-side and external to this leaf: grants load
  from the merge base (`load_authorizations(RATCHET, base=trusted_ref.base_sha)`,
  `scripts/ratchet_provenance.py`), `origin/develop` is still `ab8b3737fa64`,
  and its `quality/ratchet-authorizations.json` carries 102 vulture + 11
  reachability grants, none naming `admission_identity` (counted this round);
  the branch copies of `quality/ratchet-authorizations.json` and
  `quality/reachability-baseline.json` remain 0-line diffs vs base.

Remaining three CI gates re-reproduced at this head, same two root causes,
zero delta vs the `6b538c1ea414` round: `check-reachability.py` rc=1 with
exactly 1 NEWLY UNREACHABLE (`maistro.runs.admission_identity`, 170/1402);
the test gate's named subset `pytest
tests/test_reachability_baseline_identity.py tests/test_check_reachability.py`
(CI env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop`)
→ exactly **3 failed / 36 passed**, every failure emitting
`::error title=New unreachable modules::maistro.runs.admission_identity`; the
Coverage gate aborts one hop downstream in its `pytest tests/` scripts
producer (`quality.yml`, `set -euo pipefail`), which contains those same three
files — full-suite decomposition recorded in the preceding rounds stands.
Focused leaf validation re-executed green: pytest **79 passed**, focused ruff
check/format clean, `mypy packages/maistro-core/src/maistro/runs/admission_identity.py`
Success, `check-suite-inventory.py --suite packages/maistro-core/tests` ok
(16,439 matches the recorded inventory). Scope re-proven: branch diff vs base
is exactly the 4 in-scope files (+1,683/-0 total: module 520, test 660, note,
vulture-baseline +5); zero tracked importers of `admission_identity` outside
module+test; `runs/__init__.py` has no admission reference.

Conclusion (unchanged, now proven at `829d444973d0`): the exact-debt-ledger
red is irreducible in this leaf — any candidate ledger state exits 1 (pruning
the five rows moves the failure to the banking half), and the only two exits
are owner-landed develop grants and the #1845 real-consumer integration head,
both outside this leaf's legal action space and both required by the issue's
own staging language ("report implementation/test readiness plus the explicit
merge blocker and leave the stack unmerged"; "A candidate baseline update
cannot grant itself permission"). Baseline reconciliation per the issue
checklist: the five banked rows are the scan-exact, lane-authorized CI-repair
banking amendment — they remove nothing, grant nothing, and green no gate.
Stack left unmerged; no push; writer handoff only, never integration approval.
No inventory delta (stays +79). (Refs #1851)

## CI-repair revalidation — 2026-10-17 (`10195750ee73`, job `8f3f549c1a4a4373b20d1e607b7fc0ad`) — amendment space exhausted by execution

First round assigned at the exact branch head `10195750ee73d760f0e37c23e3c1f9fc72cbfa62`
(base `ab8b3737fa64`); worktree found clean at the assigned head. New this round:
the two counterfactual ledger/contract states that prior rounds derived from the
gate's source were **executed**, exhausting the CI-repair amendment space
empirically. Note-only commit; no source, test, or ledger change.

Fresh execution at this head (nothing assumed from prior rounds): driver
battery green (`uv sync --locked --extra dev`; `ruff check .`; `ruff format
--check .` 3,299 files; focused pytest **79 passed**; `mypy` on the module
Success; `check-suite-inventory.py --suite packages/maistro-core/tests` ok at
16,439). `git ls-remote origin develop` = `ab8b3737fa64` — the trusted base is
not just the current develop tip, it is **frozen upstream**, so the two-merge
wall cannot be crossed by a develop sync either.

`exact-debt-ledger` (`vulture-ratchet.yml`) three-step decomposition at this
head: `check-ratchet-provenance.py` rc=1 (solely "check-reachability-provenance.py:
trusted-base gate returned 1" — the unwired module); `check-shipped-surface-truth.py`
rc=0; `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` rc=1 — `unclassified: 0`, `never_allowlist: 0`, no
candidate-bookkeeping block (banking half green, 1,327 scan == 1,327 ledger),
authorization half red on exactly the five retained identities
(`admission_identity.py:515-520`). Issue-named integration commands at this
head: `check-reachability.py` rc=1 (exactly 1 NEWLY UNREACHABLE:
`maistro.runs.admission_identity`, 170/1,402), `check-reachability-dispositions.py`
rc=0 (49 groups / 169 modules), `check-promotion-surface.py` rc=0. `test` gate
reachability subset re-run at CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
RATCHET_BASE_REV=origin/develop`): exactly **3 failed / 36 passed**, every
failure emitting `::error title=New unreachable
modules::maistro.runs.admission_identity`.

**Executed counterfactual triangle** (throwaway clone pinned at this exact
head, every gate run with `RATCHET_BASE_REV=ab8b3737fa64` — CI's resolution for
this PR; see measurement trap below):

1. **As-is** (enum kept, five rows banked — the committed state): vulture gate
   rc=1, 1,322 trusted → 1,327 findings, exactly the 5 enum identities
   unauthorized. (The committed state is the *least-red legal configuration*.)
2. **Rows pruned** (enum kept, ledger reverted to develop's 1,322): rc=1 with
   BOTH halves red — "5 NEW identit(y/ies) not in the ledger" *and* "Authorized
   debt must also be banked in the candidate ledger". The lane-brief remedy
   "remove identities your fix eliminated" has an empty elimination set and a
   removal provably regresses banking; prior rounds' source-derived argument is
   now execution-proven.
3. **Members deleted + rows pruned** (the only remaining code-side lever): the
   vulture gate goes **green** (rc=0, 1,322 == 1,322) — and the issue-mandated
   contract test `test_module_exports_exact_contract_and_assessment_values`
   **fails** (1 failed / 78 passed). Together with (1) and (2): the vulture
   half greens **if and only if** the issue's fixed six-member
   `AdmissionAssessment` contract is deleted, which the issue explicitly
   forbids ("without ... removing the restored enum contract"). No ledger
   state, no code state, and no combination thereof greens the gate within the
   leaf's legal action space. Resolution remains exclusively: owner-landed
   develop-side grant (impossible while develop is frozen at the base) and/or
   the #1845 real-consumer integration head.

Measurement trap recorded for future rounds: a fresh `git clone` of this
worktree resolves `origin/develop` to the canonical repo's **stale local**
`develop` ref (trusted ledger 1,378 rows from an older base), silently
producing bogus "NEW"/"no longer found" deltas; unpinned clone runs are void.
CI pins the base via `RATCHET_BASE_REV` (workflow env), so worktree runs —
whose `origin/develop` is the true frozen upstream tip — match CI exactly.

Ledger decision (unchanged, now execution-backed): the five retained rows stay
banked exactly as the scan finds them (scan-exact, no silent row loss); no
amendment can alter the outcome (states 1–3 exhaust the space); the rows add no
grant, no waiver, no reachability entry, and green no gate by themselves. The
issue-checklist reconciliation record stands: the round-2 lane brief's
amendment authority was invoked and found insufficient pending the owner's
develop-side decision — not silently treated as approval. All leaf acceptance
criteria proven; the red gates are the issue's own anticipated explicit merge
blocker ("report implementation/test readiness plus the explicit merge blocker
and leave the stack unmerged"). Stack left unmerged; no push; writer handoff
only, never integration approval. No inventory delta (stays +79). (Refs #1851)

## CI-repair revalidation — 2026-10-17 (`88b032872717`, job `c2731ec4e79248cab`)

Assigned repair of the merge-queue evaluation at the exact branch head
`88b032872717ec54061385fec7960b3bb6d8633a` (base `ab8b3737fa64` still equals
`origin/develop`; merge-base re-verified this round); worktree found clean at
the assigned head. Driver battery check-0..4 all rc=0 (`uv sync --locked
--extra dev`, `ruff check .`, `ruff format --check .`, focused pytest 79
passed, core suite inventory ok at 16,439). All four failing gates were
re-derived by direct execution at this tree; no source, test, or ledger
change was warranted (see decomposition), so this is a note-only commit
(inventory delta stays `packages/maistro-core/tests: +79`).

1. `exact-debt-ledger` (`vulture-ratchet.yml`): its three steps were each
   re-run — `check-ratchet-provenance.py` rc=1 solely via
   `check-reachability-provenance.py: trusted-base gate returned 1` (the
   unwired module; lifecycle violations 0 == 0), `check-shipped-surface-truth.py`
   rc=0, and `check-vulture-baseline.py packages/*/src --min-confidence 60
   --exclude '*/third_party/*'` rc=1 at CI's exact argv with: `unclassified:
   0`, `never_allowlist: 0`, no candidate-bookkeeping block → banking half
   green (1,327 scan == 1,327 ledger; the five rows verified inside the
   `pydantic-declarative-field` rule the scan itself classifies them under);
   authorization half red on exactly `admission_identity.py:515-520`
   `MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`,
   message "New Vulture debt is not authorized by the trusted base … land a
   reviewed grant first." "Fix what is genuinely dead": none qualifies — the
   five are verbatim members of the issue's fixed six-member
   `AdmissionAssessment` contract (exact pairs re-read at
   `admission_identity.py:508-520`; pinned by the contract test asserting the
   ordered six-tuple), consumed in-leaf only by tests; deletion/rename is
   issue-prohibited and already tried+reverted on this branch (`b811e6978`,
   `a813787ac` → `36372888d`). "Remove identities your fix eliminated": this
   round's fix eliminates none, so no row changes; the lane-instructed
   amendment for reviewed retained identities is already present and
   scan-exact. Authorization loads from the merge base
   (`load_authorizations(RATCHET, base=trusted_ref.base_sha)`), and
   `origin/develop:quality/ratchet-authorizations.json` carries no
   `admission_identity` grant — the two-merge wall; a branch-side grant is
   inert by construction and issue-prohibited.
2. `Quality gate (Pillars 1–4, 7, 8)`: its `reachability ratchet` step
   (`quality.yml:1089-1090`) re-run → rc=1 with exactly 1 NEWLY UNREACHABLE
   (`maistro.runs.admission_identity`, 170/1402); the in-job
   `check-reachability-dispositions.py` (49 groups/169 modules) and
   `check-promotion-surface.py` both rc=0. The remedy the gate itself
   suggests (a `quality/reachability-baseline.json` entry) is issue-prohibited
   for this leaf; that file remains a 0-line diff vs base.
3. `test` (`ci.yml`): the reachability subset re-run at CI env
   (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop`):
   `pytest tests/test_reachability_baseline_identity.py
   tests/test_check_reachability.py -q` → exactly **3 failed / 36 passed**,
   every failure emitting `::error title=New unreachable
   modules::maistro.runs.admission_identity`.
4. `Coverage gate`: root cause one hop downstream, re-confirmed by reading
   `quality.yml` — its `--source=scripts` producer runs `pytest tests/ …`
   under `set -euo pipefail`, which contains the same three failing files, so
   the producer aborts before `coverage.xml`; the full-stack producer itself
   remains not locally reproducible (service stack), as recorded in prior
   rounds.

Focused leaf commands re-executed green at this head: pytest 79 passed; the
issue's 12 named tests present exactly once each (grep-verified); ruff
check + `ruff format --check` clean on both leaf files; `mypy
packages/maistro-core/src/maistro/runs/admission_identity.py` Success;
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (16,439,
matches the recorded inventory). Scope re-proven: branch diff vs base is
exactly the 4 in-scope files (+1,683/-0); zero tracked importers of
`admission_identity` outside module+test; `runs/__init__.py` has no admission
reference; `quality/ratchet-authorizations.json`,
`quality/reachability-baseline.json`, and
`quality/reachability-dispositions.json` all 0-line diffs vs base.

Conclusion (unchanged, now proven at `88b032872717`): the leaf satisfies all
of its own acceptance criteria; the four red merge-queue gates are the exact
merge blocker the issue mandates reporting ("report implementation/test
readiness plus the explicit merge blocker and leave the stack unmerged"), and
decompose to two structural facts — the intentionally unwired leaf and the
five banked-but-ungranted retained enum identities — whose only resolutions
are the owner-landed develop grants (two-merge rule) and the #1845
real-consumer integration head, both outside this leaf's legal action space.
Issue-checklist reconciliation stands: the five retained baseline entries are
the scan-exact CI-repair-round banking amendment authorized by the lane brief;
they add no grant, no waiver, no reachability entry, and green no gate by
themselves. Stack left unmerged; no push; writer handoff only, never
integration approval. No inventory delta (stays +79). (Refs #1851)

## Round 195 — independent re-derivation at the new assigned base `ab8b3737` (job `bc904b9e`)

No earlier verification claim assumed; every load-bearing fact re-derived
firsthand at head `aeb2bf93d4b24a0636ebb5a99a7c768a7628579d`.

Base movement resolved: `origin/develop` re-fetched and now at `ab8b3737fa64`
(test(graph) beam-selection pin, #1627) — exactly this round's assigned base,
one commit past the previously recorded `ac737014`. That tip is an ancestor of
this branch (318 ahead / 0 behind; merge-base = `ab8b3737`), so no develop sync
conflict exists and none is warranted. The new develop commit touches the graph
package only; none of the leaf files or quality ledgers changed on develop.

CI-exact gate re-runs at this head (rc captured directly, not from logs):

- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → rc=1. Banking half GREEN (1,327 findings,
  0 unclassified, 0 never_allowlist, all banked); authorization half RED on
  exactly the 5 `AdmissionAssessment` enum identities at
  `admission_identity.py:515-520` ("New Vulture debt is not authorized by the
  trusted base", base `ab8b3737`). `git show origin/develop:quality/ratchet-authorizations.json`
  contains 0 `admission_identity` grants, and the branch copy is a 0-line diff
  vs base, so the two-merge wall stands unchanged at the new tip.
- `check-shipped-surface-truth.py` → rc=0.
- `check-ratchet-provenance.py` → rc=1 solely via
  `check-reachability-provenance.py` trusted-base gate.
- `check-reachability.py` → rc=1: exactly `maistro.runs.admission_identity`
  NEWLY UNREACHABLE (unchanged count: one module).
- CI test-gate trio reproduced:
  `RATCHET_BASE_REV=origin/develop pytest tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py` → 3 failed / 36 passed, each failure naming
  the unwired module.
- Coverage gate root cause re-confirmed by workflow read:
  `quality.yml:713-714` producer runs `pytest tests/`, which contains the same
  three failing files; not an independent defect.

CI-repair lane instruction executed, decision unchanged with fresh evidence:
the instructed vulture command lists the 5 identities as unauthorized-from-
trusted-base (not unbanked — the candidate ledger already banks them). None is
genuinely dead: all five are the issue's fixed six-member `AdmissionAssessment`
contract, re-verified by AST at this head (members/values/order verbatim) and
by the passing contract test. The lane-permitted ledger amendment is already in
its correct reviewed state: `git diff --numstat` vs base over `quality/` is
exactly +5/-0 on `vulture-baseline.json` (the 5 scan-identical rows, develop's
1,322 rows a strict subset — no silent row loss) and 0 lines on
`ratchet-authorizations.json` / `reachability-baseline.json` (no self-grant, no
self-baseline). No fix this round eliminated any identity, so no row removal is
warranted; removal would regress banking (ledger must equal scan).

Leaf acceptance re-proven at this head: focused pytest 79/79; all 12 issue-named
tests defined exactly once (grep) and passing; ruff check + format clean on
both leaf files; focused mypy Success; full `check-suite-inventory.py` rc=0
(17 suites, 31,323 collected == unique, 0 dupes; recorded delta stays +79);
AST audit green (17/17 frozen+slots dataclasses with exact field counts —
`CanonicalJsonObject` 1, envelope 14, Legacy 7 — `__all__` 21 unique, 6
verbatim enum pairs, `owns()` the pure 3-compare conjunction never relating
generation to owner, `admitted == (binding is not None)` ×2, `repr=False` ×2,
`init=False` ×2); zero production importers and no `runs/__init__` export;
`idempotency.py`, `store.py`, `store_boundary.py`, `model.py` all 0-line diffs
vs base; #1841 anchors revalidated at this head (`store_boundary.py:56`,
`store.py:550`, `model.py:306/:335-336`).

Conclusion (unchanged, now proven against the `ab8b3737` trusted base): the
leaf satisfies all of its own acceptance criteria; the four red merge-queue
gates are the exact merge blocker the issue mandates reporting ("report
implementation/test readiness plus the explicit merge blocker and leave the
stack unmerged") and decompose to two structural facts — the intentionally
unwired leaf and the five banked-but-unauthorized retained enum identities —
whose only resolutions are owner-landed develop grants (two-merge rule) and the
#1845 real-consumer integration head, both outside this leaf's legal action
space. Stack left unmerged; no push; writer handoff only, never integration
approval. No inventory delta (stays +79). (Refs #1851)

## Round-196 re-execution at the CI-evaluated head (job 0af3e3ffb220)

Prior dispatch e8f16fbc completed all five deterministic checks rc=0 but died on
a provider timeout before recording a verdict; this round re-executed every
load-bearing check itself at `6071146c18ff` (clean tree, unchanged surfaces)
and confirmed each standing claim firsthand, not on trust:

- Focused pytest `test_root_admission_identity.py -q` → 79 passed (0.96s).
- ruff check + ruff format --check on both leaf files → clean.
- `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` → Success.
- Full `check-suite-inventory.py` → rc=0, 17 suites, 31,323 collected ==
  unique, 0 dupes; recorded delta stays +79 (no inventory change this round).
- CI-exact `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → rc=1 on authorization only: banking GREEN
  (1,322 reviewed → 1,327 findings), all 5 enum identities banked and
  unauthorized from trusted base `ab8b3737` (two-merge wall; no grant exists to
  land from this leaf).
- `check-reachability.py` → rc=1, exactly one NEWLY UNREACHABLE module:
  `maistro.runs.admission_identity`.
- `check-reachability-dispositions.py` → rc=0; `check-promotion-surface.py` →
  rc=0.
- Unwired-module test trio reproduced live: `test_check_reachability.py` +
  `test_reachability_baseline_identity.py` (+ `test_no_placeholder_modules.py`)
  → 3 failed / 40 passed, each failure naming `maistro.runs.admission_identity`
  as an extra item absent from the committed baseline.
- Structural audit re-run: zero production importers of the module;
  `runs/__init__.py` 0-line diff vs base; `idempotency.py`, `store.py`,
  `store_boundary.py`, `model.py` 0-line diffs; #1841 anchors verified at
  `store_boundary.py:56`, `store.py:550/:507/:576/:1299/:1340`,
  `model.py:306/:335-336`; `quality/` diff vs base is exactly +5/-0 rows on
  `vulture-baseline.json` and 0 lines on `ratchet-authorizations.json` /
  `reachability-baseline.json`.
- Coverage gate root cause re-confirmed by workflow read:
  `quality.yml:713-714` producer runs `pytest tests/` (which contains the three
  failing reachability files) with `--source=scripts`; same single root cause,
  no independent coverage defect.

No code change, no ledger change, and no inventory change resulted from this
round: every criterion re-passed and every red gate decomposes to the two
already-documented structural facts (unwired leaf; banked-but-unauthorized
retained enum identities). Conclusion unchanged; stack left unmerged; writer
handoff only. (Refs #1851)

## Round-197 repair round at the CI-evaluated head (job 601d1a98623e)

Dispatched to repair the four red merge-queue gates at `b4205b9839db` (Quality
gate Pillars 1–4/7/8, exact-debt-ledger, test, Coverage gate) after the prior
round requested attention as BLOCKED. Working tree clean at the assigned head;
every load-bearing claim re-derived firsthand, none taken on trust:

- CI check-run listing for this exact head re-read from dispatch evidence:
  exactly four failures (the four gates above); every other check success or a
  service-skipped leg. No additional failing gate exists.
- CI-exact `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → rc=1 on authorization only. Banking GREEN:
  1,327 findings, 0 unclassified, 0 never_allowlist. Authorization RED on
  exactly the five enum identities `admission_identity.py:515-520` vs trusted
  base `ab8b3737`; the gate's own output states the remedy: "land a reviewed
  grant first".
- Ledger integrity proven as a multiset with a row-level Counter diff vs base:
  1,322 base rows are a strict subset of the 1,327 head rows, 0 rows lost, and
  the delta is exactly the five scan-identical enum rows. `git diff --numstat`
  vs base over `quality/` is +5/-0 on `vulture-baseline.json` and 0 lines on
  `ratchet-authorizations.json`, `reachability-baseline.json`, and
  `promotion-baseline.json` — no self-grant, no self-baseline, no waiver.
- `git fetch origin` executed: `refs/remotes/origin/develop` and the develop
  tip both remain `ab8b3737` (the assigned base) — no grant has landed on
  develop, so the two-merge wall stands and there is no sync conflict to
  resolve and nothing to merge.
- `check-reachability.py` → rc=1, exactly one NEWLY UNREACHABLE module:
  `maistro.runs.admission_identity` (170/1402 total unreachable).
- Test gate reproduced: `pytest tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py -q` → 3 failed / 36 passed, each failure
  printing `::error title=New unreachable modules::maistro.runs.admission_identity`.
- Coverage gate root cause re-confirmed at `.github/workflows/quality.yml:713-714`:
  the aggregate producer runs `coverage run … -m pytest tests/ …`, so it dies
  on the same three reachability tests; no independent coverage defect.
- Issue-mandated integration-head commands re-run: dispositions rc=0,
  promotion rc=0.
- Green leaf evidence re-executed: ruff check clean, ruff format --check clean,
  focused pytest 79/79 (0.96s), full `check-suite-inventory.py` rc=0 (17
  suites, 31,323 collected == unique, 0 dupes), focused mypy Success.
- Restored contract anchors re-read at this head: `AdmissionAssessment` at
  `admission_identity.py:508-520` with the six verbatim lowercase pairs;
  contract test asserts the pairs in required order
  (`test_root_admission_identity.py:153-158`); `__all__` = 21 names.
  Branch diff vs base remains exactly the four in-scope files (+2,236/-0).

Reconciliation of the issue checklist item (five retained baseline entries vs
the published no-baseline-additions rule), recorded with this round's owner
instruction as authority: the CI-repair lane brief for this round explicitly
permits and requires amending `quality/vulture-baseline.json` for reviewed
retained identities in exact-debt-ledger repair rounds. The five rows are the
scan-exact classification of the issue-mandated fixed `AdmissionAssessment`
contract (removing the enum would violate the restored contract; suppressing or
renaming it is issue-prohibited). The amendment greens nothing: the
debt-ledger gate stays red on the authorization leg against the trusted base,
and no other gate moves — so the rows are banking, not a waiver, mask, or
self-grant. No fix this round eliminated any identity, so no row removal is
warranted; removing rows would regress banking to red.

Disposition of the four red gates — no issue-legal in-leaf fix exists:

1. exact-debt-ledger: authorization must come from the merge base; landing the
   grant requires an owner commit on develop (a GitHub mutation this lane
   prohibits). Banking side is already in its correct reviewed state.
2. test + reachability: the only fixes are a `reachability-baseline.json`
   entry ("baseline additions" — explicitly prohibited by this issue) or the
   #1845 real-consumer integration wiring (outside this leaf by the issue's
   staging constraint).
3. Coverage gate: same single root cause as (2) via the `quality.yml` producer.
4. Quality gate (Pillars): composite over the vulture/reachability provenance
   legs already dispositioned in (1)–(3).

Per the issue's own instruction — "If that integration is unavailable, report
implementation/test readiness plus the explicit merge blocker and leave the
stack unmerged" — this round records implementation/test readiness, the
explicit four-gate merge blocker, and leaves the stack unmerged. No code,
ledger, or inventory change this round (delta stays +79). Writer handoff only,
never integration approval. (Refs #1851)

## Round-198 verification + handoff at the assigned repair head (job 0e3c428f1982)

Prior job `7578ccd6cd7d` completed all five deterministic checks rc=0 but died
on a provider timeout before recording a verdict; this round re-derived every
load-bearing fact itself at `31c0cea9d23b` (clean tree). Nothing was taken on
trust:

- Driver checks re-read from this job's logs: `uv sync --locked --extra dev`
  ok, `ruff check .` "All checks passed!", `ruff format --check .` clean
  (3,299 files), focused pytest **79 passed**, `check-suite-inventory.py
  --suite packages/maistro-core/tests` ok (16,439 collected == recorded).
- `git fetch origin`: `refs/remotes/origin/develop` still `ab8b3737fa64` (0
  ahead / 321 behind) — no grant has landed on develop; the two-merge wall
  stands and there is no sync conflict to resolve.
- CI-exact vulture gate re-run: rc=1 on the authorization leg only. Banking
  GREEN (1,327 findings, `unclassified: 0`, `never_allowlist: 0`); the only
  unauthorized debt is the five enum identities at `admission_identity.py:515-520`.
- Two-merge mechanics re-verified at the source: `scripts/ratchet_provenance.py:478-518`
  (`load_authorizations`) reads grants via `resolve_baseline(path, base=base)`,
  and its docstring states "a new grant does not take effect in the change that
  introduces it ... two merges". A branch-side grant is inert by construction;
  landing one is an owner develop commit (GitHub mutation, prohibited here).
- Ledger integrity: `git diff --numstat origin/develop HEAD -- quality/` is
  exactly `+5/-0 quality/vulture-baseline.json`; the five rows are at
  `quality/vulture-baseline.json:283-287`. 0-line diffs on
  `ratchet-authorizations.json` / `reachability-baseline.json`.
- `check-reachability.py` rc=1 with exactly one NEWLY UNREACHABLE module:
  `maistro.runs.admission_identity` (170/1,402 total unreachable).
- Test gate reproduced: `pytest tests/test_reachability_baseline_identity.py
  tests/test_reachability_scanner.py tests/test_check_reachability.py -q` →
  **3 failed / 41 passed**, each failure asserting the committed baseline vs a
  tree containing `maistro.runs.admission_identity`.
- Coverage root cause re-read at `.github/workflows/quality.yml:713-714`: the
  aggregate producer runs `coverage run … -m pytest tests/ …`, which contains
  the same three files — one root cause, no independent coverage defect.
- Focused mypy → Success; `check-reachability-dispositions.py` → rc=0;
  `check-promotion-surface.py` → rc=0.
- Restored contract re-read: `AdmissionAssessment` at
  `admission_identity.py:508-520` defines exactly the six required lowercase
  pairs, and `test_root_admission_identity.py:153-161` asserts the pairs in the
  required order.
- Scope audit: branch diff vs base is exactly the four in-scope surfaces
  (note 1,129 / module 520 / test 660 / vulture-baseline +5); zero production
  importers of the module; no `maistro.runs.__init__` export.

Checklist-item reconciliation (issue body, 2026-10-16 22:04 UTC section):
recorded with this round's lane brief as the applicable owner authority — the
CI-repair lane instruction explicitly permits and requires amending
`quality/vulture-baseline.json` for reviewed retained identities in
exact-debt-ledger rounds. The five banked rows are the scan-exact
classification of the issue's own fixed six-member `AdmissionAssessment`
contract; they bank debt without waiving it (the authorization leg stays red,
nothing else moves), so they are not a self-grant, mask, or approval. No fix
eliminated an identity, so no row removal is warranted; issue comment history
(993 comments, all automated progress markers) contains no superseding owner
ruling.

Verdict: all leaf acceptance criteria re-proven at this exact head; the four
red hosted gates (exact-debt-ledger, Quality, test, Coverage) decompose to the
two documented structural facts — the intentionally unwired leaf and the
banked-but-unauthorized retained enum identities — whose only fixes are the
#1845 integration head and owner-landed develop grants, both outside this
leaf. Stack left unmerged; no code, ledger, or inventory change this round
(delta stays +79). Writer handoff only, never integration approval. (Refs
#1851)

## Independent re-derivation at assigned head (`6bbbab4ce82b`, job `87e0c8b3`)

Every load-bearing fact re-derived firsthand at the exact assigned head; no
earlier verification claim assumed. Driver battery 5/5 green from the supplied
deterministic logs (`check-0..4`: sync, ruff check, ruff format, 79 passed,
`--suite packages/maistro-core/tests` ok) and re-executed live: focused pytest
**79 passed**, `mypy admission_identity.py` Success, `ruff check .` clean,
`ruff format --check .` 3299 files formatted, suite-inventory gate ok.

- Base motion: fresh `git fetch origin develop`; `refs/remotes/origin/develop`
  = `ab8b3737fa64` (the assigned base; the `origin/develop` refname is
  ambiguous in this clone only because a same-valued local branch exists —
  both resolve to `ab8b3737`). Merge-base = `ab8b3737`, branch 322 ahead / 0
  behind: no sync conflict, none warranted. `ratchet-authorizations.json` and
  all `quality/` files except `vulture-baseline.json` are 0-line diffs vs
  base.
- Contract re-proven by independent AST audit: 17/17 dataclasses
  `frozen=True, slots=True`; `__all__` 21 unique set-exact; `AdmissionAssessment`
  StrEnum with exactly the six lowercase pairs in issue order; `owns()` a
  single BoolOp of exactly 3 compares; `field(repr=False)` ×2 and
  `field(init=False)` ×2; both `admitted` properties return exactly
  `binding is not None`; exact field order verified for all six record types;
  zero suppression markers. All 12 issue-named tests present in the 660-line
  test file; no skips in the 79.
- Scope invariants: zero production importers of `admission_identity`; no
  `maistro.runs.__init__` export; branch diff vs base is exactly the four
  in-scope surfaces (+2380/-0). #1841 anchors re-read at this head:
  `store_boundary.py:56`, `store.py:550` (+ guard enforcement at `:936` and
  `:1340`), `model.py:306/:335-336` — signature un-weakened.
- Inventory arithmetic re-derived: baseline.json `packages/maistro-core/tests`
  = 11524; expected = baseline + Σ recorded deltas = 16439 collected node IDs
  (gate ok); this note's `+79` contributes exactly once.
- CI-exact gates re-run live at their pinned argv:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → rc=1, banking GREEN (`unclassified: 0`,
  `never_allowlist: 0`; base 1322 → candidate 1327 with no banking error),
  authorization RED on exactly the five enum identities
  `admission_identity.py:515-520`, gate's own remedy "land a reviewed grant
  first" — grants load from the merge base, so the two-merge wall stands at a
  develop that has not moved. `check-reachability.py` → rc=1 with exactly one
  NEWLY UNREACHABLE: `maistro.runs.admission_identity`. Test gate root trio
  `pytest tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py -q --timeout=60` → 3 failed / 36 passed,
  every failure the `baseline == unreachable` assertion naming this module;
  the Coverage producer (quality.yml:714) runs the same `tests/` tree under
  `set -euo pipefail`, so those three failures abort it before `coverage.xml`.
- No repair exists in this leaf: the only conceivable fixes are an
  issue-prohibited reachability-baseline entry or synthetic caller, a
  branch-side grant that is inert by construction and prohibited by the issue
  ("A candidate baseline update cannot grant itself permission"), or the
  #1845 integration head / owner-landed develop grants — both outside this
  leaf. The 998-comment history (single automation account, all
  `maistro-progress` markers) contains no superseding owner ruling; the
  five-row banking amendment stands as recorded under the lane brief's
  CI-repair authority.

Verdict unchanged: writer handoff MERGE-READY (handoff only, never
integration approval); stack left unmerged; no code, ledger, or inventory
count change (delta stays +79). (Refs #1851)

## Round-200 verifier re-execution at the assigned head (`d30d9a1bc923`, job `408dd6089f7d495fac36d625a0ff9b63`)

Prior job `695871a3` died on a provider timeout after all five driver checks
returned rc=0; this round re-derived every load-bearing fact firsthand with no
earlier claim assumed. Driver checks this dispatch: uv sync, ruff check .,
ruff format --check ., focused pytest, suite inventory — 5/5 green.

- Base motion: fresh `git fetch origin`; `origin/develop` resolves to
  `ab8b3737fa64` = the assigned base (the refname-ambiguity warning is a
  same-valued local branch, not a divergence); merge-base(HEAD, develop) =
  `ab8b3737` → develop is an ancestor (+323 ahead, 0 behind), no sync
  conflict. Branch diff vs base is exactly the 4 in-scope files
  (+2380/-0 numstat) and `git diff --numstat ab8b3737 -- quality/` is
  exactly `5  0  quality/vulture-baseline.json` — no grant, no
  reachability-baseline, no waiver edits anywhere in `quality/`.
- Focused acceptance re-executed: `pytest
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` → 79
  passed (rc=0); all 12 issue-named tests collected (the two parameterized
  ones expand to 16 + 37 cases); `ruff check .` and `ruff format --check .`
  clean; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py`
  → Success; full `check-suite-inventory.py` rc=0 (17 suites, 31323 ==
  recorded, 0 duplicates; maistro-core/tests baseline 11524 + this note's
  +79 counted once = 16439).
- Contract audit re-run as a fresh AST walk: 16/16 dataclasses
  `frozen=True, slots=True` with exact issue field orders; `owner_token`
  `field(repr=False)` ×2 and `format_version` `field(init=False)` ×2;
  `__all__` = exactly the issue's 21 names, set-exact (alphabetical, the
  ruff-canonical order — the issue fixes the name set, not a sequence);
  `admitted` returns exactly `self.binding is not None` ×2; `owns()` is the
  pure 3-compare conjunction (scope AND generation AND owner, no
  generation-vs-owner comparison); `AdmissionAssessment` = the exact six
  member/value pairs in required order; 0 `type: ignore`/`noqa`.
- Scope invariants: 0 references to `admission_identity` in `packages/*/src`
  outside the module; `runs/__init__.py` exports none of the 21 names;
  `#1841` anchors intact (`store_boundary.py:56`
  `require_admitted_actor`, `store.py:550` `get_run(..., *, principal_id=...)`,
  `store.py:936/:1340` admitted-actor guards, `model.py:306`
  `actor_principal_id` field).
- Vulture ledger multiset proof re-derived from parsed JSON (not diffs):
  base 1322 → candidate 1327 rows; per-rule Counter delta = +5/-0, all five
  under `pydantic-declarative-field`, string-identical to the fresh scan's
  new identities; 0 rows lost in any rule; rule ids, order, and non-finding
  metadata byte-identical. `PENDING` (line 517) is correctly neither banked
  nor scan-flagged: 78 uses of the token elsewhere in `packages/*/src` make
  vulture's name tracking see it as used.
- CI-exact gates at pinned argv, rc captured: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → rc=1,
  banking GREEN (1327 findings, `unclassified: 0`, `never_allowlist: 0`),
  authorization RED on exactly `admission_identity.py:515-520` with the
  gate's own remedy "land a reviewed grant first"; `load_authorizations`
  (`scripts/ratchet_provenance.py:478`) reads grants from the base revision,
  so with develop unmoved the two-merge wall stands. `check-reachability.py`
  → rc=1, exactly one NEWLY UNREACHABLE (`maistro.runs.admission_identity`).
  `check-reachability-dispositions.py`, `check-promotion-surface.py`,
  `check-shipped-surface-truth.py` → rc=0. `check-ratchet-provenance.py` →
  rc=1 solely via `check-reachability-provenance.py` returning 1 on the same
  module.
- Test gate reproduced: the reachability test files fail at exactly 3
  (`tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `...::test_the_baseline_is_exactly_the_unreachable_set`), each asserting
  `baseline == unreachable-set` and each naming `maistro.runs.admission_identity`
  as the extra element; Coverage gate root cause unchanged
  (`quality.yml:714` producer runs `pytest tests/` under `set -euo
  pipefail`, aborting on the same trio before `coverage.xml`).
- Repair decision re-affirmed: all 5 flagged identities are banked, none is
  genuinely dead (they are the issue's own fixed six-member enum contract,
  asserted by the contract test), and no fix this round eliminated any
  identity → no row removal; removing rows would regress banking to red.
  A branch-side grant is inert by construction (two-merge rule) and
  prohibited by the issue; a reachability-baseline entry or synthetic caller
  is likewise issue-prohibited. No code, ledger, or inventory change
  warranted this round; delta stays +79.
- Comment history re-checked (1003 comments, single automation account, all
  `maistro-progress` markers): no superseding owner ruling. The issue
  body's 2026-10-16 status section remains the latest owner-authored word;
  its open checklist item ("reconcile the five retained baseline entries and
  the claimed lane instruction") is satisfied by this standing record: the
  banking amendment rests on the lane brief's explicit CI-repair authority
  ("amend quality/vulture-baseline.json for reviewed retained identities"),
  authorizes nothing (the authorization leg is and stays red — not silently
  treated as approval), and the restored enum contract is not removed.

Verdict: writer handoff MERGE-READY (handoff only, never integration
approval); stack left unmerged; the four red gates remain the
issue-anticipated explicit merge blocker whose only fixes are the #1845
integration head and owner-landed develop grants, both outside this leaf.
Note-only commit; no inventory delta (stays +79). (Refs #1851)

## Round-201 verifier + CI-repair round at the assigned head (`44322576cdfd`, job `3574a69a9a33`)

Dispatch reported the previous round's `BLOCKED` verdict as an open block and
re-issued the CI-repair ledger authority ("fix what is genuinely dead, and
amend quality/vulture-baseline.json for reviewed retained identities; ledger
amendment is permitted and required in CI-repair rounds"). This round re-ran
every acceptance check and every red gate firsthand at the exact assigned head
`44322576cdfdbb2c9bfe9f552ff23fb2fad5a745` (clean tree on arrival); no earlier
claim taken on faith.

- Driver logs inspected (job dir `3574a69a`): 5/5 green — uv sync ok;
  `ruff check .` All checks passed; `ruff format --check .` 3299 files already
  formatted; focused pytest 79 passed; suite inventory ok (core tests 16439).
- Focused acceptance re-executed live: focused pytest 79 passed (rc=0);
  per-file ruff check/format clean; `mypy .../admission_identity.py` Success;
  FULL `check-suite-inventory.py` rc=0 (17 suites, 31323 collected == unique,
  0 duplicate evidence).
- The four red gates re-derived with rc captured (not inherited):
  1. `test` job: full root suite re-run end-to-end → **exactly 3 failed**
     (5072 passed, 135 skipped):
     `tests/test_check_reachability.py::test_baseline_matches_the_tree`,
     `tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
     `tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`
     — each asserts `baseline == current unreachable set` and each diff names
     `maistro.runs.admission_identity` as the extra element.
  2. `exact-debt-ledger`: CI-argv vulture scan → **rc=1** (rc taken from the
     python process, not a pipe), banking half GREEN (`unclassified: 0`,
     `never_allowlist: 0`; candidate 1327 == scan), authorization half RED on
     exactly the 5 retained enum identities `admission_identity.py:515-520`,
     with the gate's own remedy "land a reviewed grant first".
  3. Quality gate leg: `check-reachability.py` rc=1 with exactly 1 NEWLY
     UNREACHABLE (`maistro.runs.admission_identity`, 170/1402);
     `check-ratchet-provenance.py` rc=1 **solely** via
     `check-reachability-provenance.py` (same module, NEW + missing from
     candidate baseline); `check-reachability-dispositions.py`,
     `check-reachability-dispositions-provenance.py`,
     `check-promotion-surface.py`, `check-shipped-surface-truth.py` all rc=0.
  4. Coverage gate: root cause re-read at `quality.yml:713-714` — the
     aggregate producer runs `coverage run … -m pytest tests/ …`, so the same
     trio aborts it before `coverage.xml`.
- Two-merge wall re-confirmed from source, not memory:
  `scripts/ratchet_provenance.py:487-498` documents and implements grants read
  **from the base revision**; fresh `git fetch origin` → `origin/develop` =
  `ab8b3737fa64` = the assigned base (refname ambiguity is a same-valued local
  branch), HEAD 0 behind — develop unmoved, so no landed grant exists and
  landing one is a prohibited GitHub mutation for this lane.
- Ledger state re-proven from parsed JSON (multiset, never `set()`):
  `quality/` numstat vs base is exactly `+5/-0 vulture-baseline.json`;
  per-rule Counter delta +5/-0 (all `pydantic-declarative-field`), 0 rows lost;
  the banked identity set equals the fresh scan's new-identity set exactly;
  `ratchet-authorizations.json` / `reachability-baseline.json` /
  promotion files have 0-line diffs. Per the re-issued lane authority the 5
  reviewed retained identities stay banked: none is genuinely dead (they are
  the issue's own fixed six-member enum contract, pair-asserted by the
  contract test), no fix this round eliminated any identity, and removing
  rows would regress the banking half to red. The banked rows authorize
  nothing — the authorization leg is and stays red, so the issue's merge hold
  is preserved (banking is not authorizing).
- Contract audit re-run as a fresh AST walk at this head: 18 top-level
  ClassDefs = **17 dataclasses, all `frozen=True, slots=True`** (this corrects
  round-200's "16/16" wording; the 18th ClassDef is the `AdmissionAssessment`
  StrEnum) + the enum's exact six lowercase member/value pairs in required
  order; `__all__` 21 names unique and set-exact; `owns()` a single
  `BoolOp(And)` of exactly 3 compares; `field(repr=False)` ×2 and
  `field(init=False)` ×2; both `admitted` properties are a docstring plus one
  `return self.binding is not None` (AST `Compare(IsNot, Constant(None))` —
  `is not` desugars to `IsNot`, an earlier probe's `Is` check was the probe's
  bug, not the code's); 0 suppression markers.
- Scope invariants re-proven: 0 references to `admission_identity` in
  `packages/*/src` outside the module; 0 admission references in
  `runs/__init__.py`; branch diff vs base exactly the 4 in-scope files
  (+2380/-0). `#1841` anchors re-read intact: `store_boundary.py:56`,
  `store.py:550` (+ `:507/:576/:907/:1299`), `model.py:306`/`:335-336`.
- Repair decision: no issue-legal in-leaf fix greens any of the four gates —
  every candidate repair (runtime caller, keep-alive import, re-export,
  reachability-baseline entry, suppression, branch-side grant, enum removal)
  is respectively prohibited by the issue's exact scope/staging text and/or
  structurally inert (two-merge rule). The issue itself designates these gates
  as the expected state of an unwired leaf and prescribes the terminal
  disposition: report implementation/test readiness plus the explicit merge
  blocker and leave the stack unmerged. The issue's open checklist item
  ("reconcile the five retained baseline entries and the claimed lane
  instruction") remains satisfied by this standing record, now re-anchored to
  this round's re-issued lane authority; the enum contract is intact and not
  removed.

Verdict: writer handoff MERGE-READY (handoff only, never integration
approval); stack left unmerged; the four red gates remain the issue-anticipated
explicit merge blocker whose only fixes are the #1845 integration head
(real consumer wiring) and owner-landed develop grants, both outside this
leaf. Note-only commit; no inventory delta (stays +79). (Refs #1851)

## Round evidence — 2026-10-17 round 202 (job `a4c9ec71a3274c56906a33084c09878e`, head `150cdb9e8910`)

Independent verifier+writer round at the exact assigned head `150cdb9e8910b4fbe16f6082011d5745c6d73afd`
(base `ab8b3737fa64f8d840f421ef87ca506c509444ff`); no earlier claim assumed; every load-bearing fact
re-derived firsthand.

- Driver battery 5/5 green (job logs `check-0..4`): `uv sync --locked --extra dev` rc=0; `ruff check .`
  "All checks passed!"; `ruff format --check .` 3299 files already formatted; focused pytest **79 passed**;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok at 16439.
- Live re-execution at this head: focused pytest 79 passed; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py`
  Success; focused ruff check/format clean; full `check-suite-inventory.py` rc=0 (17 suites,
  31323 collected == 31323 unique, 0 duplicate evidence); `check-reachability-dispositions.py`,
  `check-reachability-dispositions-provenance.py`, `check-promotion-surface.py`,
  `check-shipped-surface-truth.py` all rc=0.
- Contract re-proven by fresh AST walk: 17 dataclasses all `frozen=True`+`slots=True` (the 18th ClassDef is
  the `AdmissionAssessment` StrEnum); every record/result field order exact per the issue
  (`RootAdmissionEnvelope` 14 fields; `AdmissionRecordV2` 6; `LegacyAdmissionRecord` 7 incl. defaulted
  `binding`; `RootAdmissionResult` 4; empty variants field-free); 6 enum member/value pairs verbatim and in
  order; `__all__` 21 names unique and set-exact; `owns()` a single `BoolOp(And)` of exactly 3 compares;
  `field(repr=False)` x2; `field(init=False)` x2; both `admitted` properties return exactly
  `binding is not None`; 0 suppression markers.
- All 12 issue-named tests defined exactly once; zero importers of `admission_identity` in tracked
  `packages/*/src` outside module+test; `runs/__init__.py` has no admission reference; branch diff vs base
  is exactly the 4 in-scope files (+2380/-0), `quality/` numstat exactly +5/-0
  (`vulture-baseline.json`), `ratchet-authorizations.json`/`reachability-baseline.json` 0-line diff.
- `#1841` anchors intact at this head: `store_boundary.py:56`
  `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550`
  `get_run(self, run_id: str, *, principal_id: str | None = None)`; `actor_principal_id` retained
  (`store.py` x8, `model.py` x3).
- CI at this head (dispatch snapshot, evidence only): `exact-debt-ledger` completed **failure**;
  `gates-ran` pending "Required execution evidence is still arriving"; remaining checks in progress at
  capture — pending/unavailable CI stays UNVERIFIED; no green inferred from the snapshot.
- Red gates re-derived live at CI-exact argv with true exit codes:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 —
  banking GREEN (candidate 1327 == scan 1327, `unclassified: 0`, `never_allowlist: 0`), authorization RED
  on exactly `admission_identity.py:515-520` (`MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/
  `LEGACY_UNRESOLVED`) with the gate's own remedy "land a reviewed grant first";
  `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE (`maistro.runs.admission_identity`,
  170/1402); `check-ratchet-provenance.py` rc=1 solely via `check-reachability-provenance.py`; the CI test
  trio reproduced 3 failed (`test_baseline_matches_the_tree`,
  `test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `test_the_baseline_is_exactly_the_unreachable_set`), all naming this module; Coverage root cause
  re-read at `quality.yml` (`coverage run ... -m pytest tests/ ...` producer contains the same trio).
- Base motion: fresh `git fetch origin`; `origin/develop` still `ab8b3737` == assigned base (both
  resolutions of the ambiguous refname are the same value), merge-base equal, 0 commits behind — no
  develop sync conflict exists to merge, and no grant for the 5 identities has landed, so the two-merge
  wall stands.
- `exact-debt-ledger` disposition (carried instruction re-examined): no issue-legal in-leaf change greens
  it — removing the 5 banked rows regresses the banking half to red (unclassified 5); a branch-side grant
  is inert (grants load from the merge base) and prohibited; a runtime caller, keep-alive import,
  re-export, reachability-baseline entry, or suppression is prohibited by the issue's exact scope/staging
  text; develop is unmoved so nothing can be merged in. The red gates remain the issue-anticipated
  explicit merge blocker whose repair paths are the `#1845` integration head (real consumer wiring) and
  owner-landed develop grants, both outside this leaf. The issue's open reconciliation checkbox stays
  satisfied by this standing record re-anchored to this round's re-issued lane authority; banked rows
  authorize nothing; the enum contract is intact and not removed.
- Advisory (no in-lane action possible): the round-200 note commit message contains the prose
  "only fixes: #1845 integration head", whose `fixes: #1845` adjacency matches GitHub's closure-keyword
  pattern; it is not a trailer and this lane cannot rewrite pushed history — squash note commits at the
  integration merge so the parent issue is not auto-closed prematurely.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); stack left unmerged;
no inventory delta (stays +79). (Refs #1851)

## Round evidence — 2026-10-17 repair round (job `21b7948c9e3c4852b8965df636b0cdd4`, head `c524027893589298bb44a81119c6a7dfaa045195`)

Verifier + CI-repair round at the exact assigned head (base `ab8b3737fa64f8d840f421ef87ca506c509444ff`);
no earlier claim assumed; every load-bearing fact re-derived firsthand. Prior job `50f1f2b8` died on a
provider timeout after its 5/5 green driver checks; this round re-executed everything.

- Driver battery 5/5 green (this job's logs `check-0..4`): `uv sync --locked --extra dev` rc=0;
  `ruff check .` "All checks passed!"; `ruff format --check .` 3299 files already formatted; focused
  pytest **79 passed**; `check-suite-inventory.py --suite packages/maistro-core/tests` ok at 16439.
- Live re-execution at this head: focused pytest 79 passed; focused ruff check/format clean;
  `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` Success; full
  `check-suite-inventory.py` rc=0 (17 suites, 31323 collected == 31323 unique, 0 duplicate evidence);
  `check-reachability-dispositions.py` rc=0; `check-promotion-surface.py` rc=0.
- Base motion re-resolved by fresh `git fetch origin develop`: `refs/remotes/origin/develop`,
  the same-valued local `origin/develop` branch, and `FETCH_HEAD` all equal `ab8b3737` == assigned base;
  merge-base equal; `git rev-list --count HEAD..origin/develop` = 0 — no develop sync conflict exists,
  nothing to merge, and no grant for the 5 identities has landed, so the two-merge wall stands.
- Contract re-proven by fresh AST walk: 17 dataclasses all `frozen=True`+`slots=True` (the 18th ClassDef
  is the `AdmissionAssessment` StrEnum at `admission_identity.py:508-520`); exactly 6 member/value pairs
  verbatim and in order at lines 515-520; `__all__` 21 names unique and set-exact; `owns()` a single
  `BoolOp(And)` of exactly 3 compares; `field(repr=False)` x2; `field(init=False)` x2; both `admitted`
  properties return exactly `binding is not None`; 0 suppression markers in the module (the only
  `type: ignore` markers are negative-typing assertions in the leaf's own test file).
- Scope invariants re-proven: all 12 issue-named tests defined exactly once (79 node IDs collected);
  zero importers of `admission_identity` in tracked sources outside module+test; no `runs/__init__.py`
  export; branch diff vs base is exactly the 4 in-scope files (A note +1500 / A module +520 / A test +660
  / M `vulture-baseline.json` +5), `quality/` numstat exactly +5/-0 vulture rows.
- `#1841` anchors intact at this head: `store_boundary.py:56`
  `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550`
  `get_run(self, run_id: str, *, principal_id: str | None = None)`; admitted-actor guard enforced at
  `store.py:936`; `Run.actor_principal_id` retained (`model.py:306`, validation `model.py:335-336`).
- Red gates re-derived live at CI-exact argv with true exit codes:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 —
  banking GREEN (1327 findings, `unclassified: 0`, `never_allowlist: 0`; exit-term audit of
  `scripts/check-vulture-baseline.py:313-378` shows candidate_added/removed/unbanked all empty, i.e. the
  candidate ledger matches the scan), authorization RED on exactly the 5 retained enum identities
  `admission_identity.py:515-520` with the gate's own remedy "land a reviewed grant first". Two-merge
  mechanics re-read firsthand at `scripts/ratchet_provenance.py:478-517`: `load_authorizations` resolves
  grants from the base revision, so a branch-side grant is inert by construction.
  `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity`;
  the CI test trio reproduced 3 failed / 64 passed (`test_baseline_matches_the_tree`,
  `test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `test_the_baseline_is_exactly_the_unreachable_set`), every failure naming this module; Coverage
  producer root cause re-read at `.github/workflows/quality.yml:713-714` (`pytest tests/ ...` includes
  the same trio, aborting under `set -euo pipefail` before `coverage.xml`).
- Ledger reconciliation (issue checkbox, re-anchored to this round's re-issued lane authority —
  "amend quality/vulture-baseline.json for reviewed retained identities; ledger amendment is permitted
  and required in CI-repair rounds"): the 5 banked rows are exactly the scan's identities for the
  issue-fixed `AdmissionAssessment` contract ("exactly these member/value pairs"; restoration checklist
  forbids removing the restored enum), so no genuinely dead code exists to delete and removing the rows
  would only regress the banking half to red. The ledger is already in its correct reviewed state
  (+5/-0, multiset-exact vs scan); `ratchet-authorizations.json` and `reachability-baseline.json` carry
  0-line diffs; banked rows authorize nothing. All 1015 issue comments re-scanned: bot progress markers
  only, no superseding owner ruling; the issue's staging constraints stand unchanged.
- Disposition (unchanged, re-proven): no issue-legal in-leaf change greens any of the four red gates —
  every candidate repair (row removal, branch grant, caller/export, reachability-baseline entry,
  suppression, threshold change) is either issue-prohibited verbatim or structurally inert. The red
  gates are the issue-anticipated explicit merge blocker whose repair paths are the `#1845` integration
  head (real reviewed runtime consumer) and owner-landed develop grants, both outside this leaf per the
  issue's own prescription ("report implementation/test readiness plus the explicit merge blocker and
  leave the stack unmerged").

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration
hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round 203 — independent verifier + writer round at assigned head 43b453a1cd0e (job 640bcf0df6a3)

Every load-bearing fact re-derived firsthand at the exact assigned head (`43b453a1cd0ef07d2c7978fbb4cfc5f2c16aaf19`,
worktree clean, `origin/develop` unmoved at assigned base `ab8b3737`, 0 behind; refname ambiguity is a
same-valued local branch). No earlier claim assumed.

- Focused acceptance re-executed live: `pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  → 79 passed (rc=0); `ruff check` + `ruff format --check` clean on both leaf files (rc=0);
  `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` → Success; `check-suite-inventory.py
  --suite packages/maistro-core/tests` → ok, 16439 == recorded, 0 dupes. All 12 issue-named tests defined
  exactly once (grep count 1 each).
- Contract re-proven by direct read + live introspection: 17 dataclasses all `frozen=True, slots=True`;
  `__all__` 21 names set-exact, 0 dupes; `AdmissionAssessment` exactly the 6 required pairs
  (MISMATCH/REPLAYED/PENDING/TAKEOVER/REPLACE_EXPIRED/LEGACY_UNRESOLVED, lowercase values, in order,
  at `admission_identity.py:515-520`); `owns()` the pure 3-term conjunction; `owner_token field(repr=False)` ×2;
  `admitted == (binding is not None)` ×2. The contract test (`test_root_admission_identity.py:128-161`)
  asserts `__all__` and the enum pairs verbatim in order.
- Scope invariants re-proven: branch diff vs base = exactly the 4 in-scope files (+2750/-0); grep over
  packages/tests/scripts finds 0 importers outside module+test; `runs/__init__.py` has no admission
  reference; `quality/ratchet-authorizations.json` and `quality/reachability-baseline.json` 0-line diffs
  (no self-grant, no self-baseline).
- `#1841` anchors re-read intact at this head: `store_boundary.py:56 require_admitted_actor(actor_principal_id: str | None) -> str`,
  `store.py:550 get_run(..., principal_id: str | None = None)`, `store.py` 8 `actor_principal_id` refs,
  `model.py:306` field + `:335-336` validation.
- CI-exact gates re-run at `RATCHET_BASE_REV=origin/develop` with true exit codes:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → rc=1,
  banking GREEN (1327 findings, unclassified 0, never_allowlist 0; candidate ledger == scan) and
  authorization RED on exactly the 5 enum identities `:515-520` with the gate's own remedy "land a
  reviewed grant first" (two-merge wall; grants load from the base revision). `quality/vulture-baseline.json`
  carries exactly those 5 rows (+5/-0, line-number-independent `path::message` identities, multiset-exact
  vs scan). `check-reachability.py` → rc=1, exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity`
  (170/1402). `check-reachability-dispositions.py` → rc=0 (49 groups / 169 modules). `check-promotion-surface.py`
  → rc=0. CI test trio reproduced live: `pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py -q`
  → 3 failed / 36 passed, every failure naming the unwired module.
- Reconciliation status re-derived from the freshly captured issue state (1018 comments scanned): all are
  automation progress markers; 0 comments mention baseline/vulture; no superseding owner ruling exists.
  The issue's reconciliation checkbox remains open pending an owner decision outside this leaf; the lane
  authority record in this note stands unchanged (banked rows authorize nothing; the authorization leg
  stays red, which is the issue-anticipated merge blocker, not a waiver).
- Closure-keyword review: PR `#1936` body contains no closure keyword ("Refs #1851" only). Branch commits
  contain one prose occurrence "fixes: #1845" inside the round-199 note-commit message (d30d9a1b) —
  branch-only and inert until a default-branch landing; the recorded mitigation (squash note commits at
  the `#1845` integration merge) stands. This commit adds no closure keyword.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration
hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-204 independent verifier + writer re-execution (head `17bf8bb0`, base `ab8b3737`)

Every load-bearing fact re-derived firsthand at the exact assigned head; no earlier claim assumed.
Driver logs 5/5 green (uv sync; ruff check; ruff format; pytest 79 passed; suite inventory ok).

- Worktree clean at exact head `17bf8bb0effe6b3c9dcba874f88202eff6a7de6e`; base unmoved
  (`origin/develop` = `ab8b3737` = merge-base, 0 behind; refname ambiguity is a same-valued local
  branch) — no develop sync conflict exists.
- Focused acceptance re-executed live: `pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  → 79 passed rc=0; ruff check + `format --check` on both leaf files → clean; `mypy` on the module →
  Success; `check-suite-inventory.py` → ok (17 suites, 31323 == 31323, 0 duplicate identities).
- Contract re-proven by AST walk: 17/17 dataclasses frozen+slots; `__all__` 21 names set-exact;
  `AdmissionAssessment` StrEnum with the 6 lowercase pairs in order at `admission_identity.py:508-520`;
  `owns()` 3-term conjunction; `owner_token` `repr=False` on `AdmissionTicket`+`AdmissionRecordV2`;
  `admitted == (binding is not None)` on both record types; empty variants define no `__bool__`;
  all 12 issue-named tests defined exactly once and the contract test asserts `__all__` + enum pairs
  verbatim.
- Scope invariants hold: diff vs base is exactly the 4 in-scope files (+2797/-0: module 520, tests 660,
  note 1612, vulture-baseline +5); 0 production importers of `admission_identity`; no
  `maistro.runs.__init__` export; `quality/ratchet-authorizations.json` and
  `quality/reachability-baseline.json` 0-line diffs vs develop.
- `#1841` anchors intact: `store_boundary.py:56 require_admitted_actor(actor_principal_id: str | None) -> str`;
  `store.py:550 get_run(..., principal_id: str | None = None)`; 8 `actor_principal_id` refs in `store.py`
  (`create_run` :499, `claim_run_by_effect` :567); `model.py:306` field + `:335-336` validation.
- CI-exact gates re-run with true exit codes: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → rc=1, banking GREEN (1327 findings, unclassified 0, never_allowlist 0,
  candidate ledger == scan), authorization RED on exactly the 5 enum identities `:515-520` with the gate's
  own remedy "land a reviewed grant first"; two-merge wall confirmed at `scripts/ratchet_provenance.py:478-499`
  (grants read from the base revision, so a branch-side grant is inert by construction). Baseline multiset
  re-parsed: develop 1322 → HEAD 1327, +5/-0, exactly the 5 scanned enum rows.
  `check-reachability.py` → rc=1, exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity`.
  `check-reachability-dispositions.py` → rc=0. `check-promotion-surface.py` → rc=0.
  `check-ratchet-provenance.py` → rc=1 solely via the reachability leg (enumeration + lifecycle OK).
  `check-shipped-surface-truth.py` → rc=0.
- CI test trio reproduced live: `pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py -q`
  → 3 failed / 36 passed, each failure naming `maistro.runs.admission_identity` — the issue-anticipated
  honest state for an intentionally inactive leaf; no issue-legal in-leaf change greens the four red gates
  (row removal regresses banking; branch grant inert + prohibited; caller/export/baseline-entry/suppression
  prohibited). The resolving changes remain the `#1845` integration head and owner-landed develop grants,
  both outside this leaf.
- Closure-keyword review: PR `#1936` body has no closure keyword ("Refs #1851" only); branch commit bodies
  contain 0 closure trailers; the two subject-line regex hits are prose inside note-commit messages
  (round-199 "the only fixes: #1845 integration head..." and round-203's description of it) — branch-only,
  inert until a default-branch landing; squash-at-integration mitigation stands. This commit adds no
  closure keyword.
- Reconciliation status: the issue's five-retained-baseline-entries checkbox remains open pending an owner
  decision outside this leaf; the lane-authority record in this note stands unchanged (banked rows authorize
  nothing; the red authorization leg is the issue-anticipated explicit merge blocker, not a waiver).

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration
hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-205 independent verifier + writer re-execution (head `f86237ded`, base `ab8b3737`)

Job `61556ecdcdb54291850c79bddd7d1d16`. Every load-bearing fact re-derived firsthand at the exact
assigned head; no earlier claim assumed. Driver logs 5/5 green (uv sync; ruff check; ruff format;
pytest 79 passed; suite inventory ok).

- Worktree clean at exact head `f86237ded38549a4c64620ab53837c2cc776f527`. **Base motion resolved by
  fresh fetch:** `refs/remotes/origin/develop` advanced `ab8b3737` → `07fac4abd` (+2: `369ab9add`
  ontology Protocol docstring, `07fac4abd` cancellation-cause-codec test). Neither commit touches
  `quality/` (`git diff --name-only ab8b3737..refs/remotes/origin/develop -- quality/` is empty) nor
  imports `admission_identity` — **no grant landed, the two-merge wall stands, and no develop sync
  conflict exists** (PR `#1936` is `mergeable=True`, `mergeable_state=behind`; per lane brief the
  merge-develop remedy applies only to sync conflicts, so the stack stays unmerged and the PR head
  unmoved by this round).
- Focused acceptance re-executed live: `pytest
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` → 79 passed rc=0; ruff check +
  `format --check` on both leaf files → clean; `mypy` on the module → Success; full
  `check-suite-inventory.py` → ok (17 suites, 31323 == 31323, 0 duplicate identities).
- Contract re-proven by AST walk: 18 ClassDefs = 17 frozen+slots dataclasses (no exceptions) + the
  `AdmissionAssessment` StrEnum at `:508` with the 6 lowercase pairs verbatim in order at `:515-520`;
  `__all__` 21 names; `owns()` is a single `And` with exactly 3 operands (scope_key, generation_id,
  owner_token); `repr=False` ×2 (`AdmissionTicket`/`AdmissionRecordV2` `owner_token`);
  `admitted == "self.binding is not None"` ×2; `field(init=False)` ×2 (`format_version`); 0 `# noqa`,
  0 `type: ignore`, 0 vulture strings. All 12 issue-named tests defined exactly once.
- Scope invariants hold: diff vs base is exactly the 4 in-scope files (+2849/-0); 0 production
  importers of `admission_identity`; no `maistro.runs.__init__` export; `quality/` numstat +5/-0
  (vulture-baseline only); grant/reachability files 0-line diffs.
- `#1841` anchors intact: `store_boundary.py:56 require_admitted_actor(actor_principal_id: str | None)
  -> str`; `store.py:550 get_run(..., principal_id: str | None = None)` + 8 `actor_principal_id` refs;
  `model.py:306` field + `:335-336` validation.
- CI-exact gates re-run with true exit codes: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (RATCHET_BASE_REV=refs/remotes/origin/develop) →
  rc=1, banking GREEN (1327 findings == candidate ledger 1327, unclassified 0, never_allowlist 0),
  authorization RED on exactly the 5 enum identities `:515-520` with the gate's own remedy "land a
  reviewed grant first". Baseline rows re-parsed from JSON: exactly those 5 reviewed retained
  identities, multiset +5/-0 vs base; no fix eliminated any identity, so the CI-repair instruction's
  "remove identities your fix eliminated" clause is vacuously satisfied and the amendment stands as-is.
  Two-merge mechanism re-read at `scripts/ratchet_provenance.py:478-498` (`load_authorizations` reads
  grants from the base revision; docstring: "a new grant does not take effect in the change that
  introduces it"). `check-reachability.py` → rc=1, exactly 1 NEWLY UNREACHABLE:
  `maistro.runs.admission_identity` (170/1402). `check-reachability-dispositions.py` → rc=0.
  `check-promotion-surface.py` → rc=0. `check-shipped-surface-truth.py` → rc=0.
  `check-ratchet-provenance.py` → rc=1 solely via the reachability leg (contract-marker, enumeration,
  lifecycle legs all OK).
- CI test trio reproduced live: 3 failed / 46 passed across `tests/test_check_reachability.py` +
  `tests/test_reachability_baseline_identity.py`, each failure naming `maistro.runs.admission_identity`
  as the extra unreachable module. Coverage producer root cause re-read at `quality.yml:713-714`
  (producer runs `pytest tests/`, which contains the trio).
- Disposition unchanged: no issue-legal in-leaf change greens the four red gates — the 5 identities are
  the issue-mandated enum contract (removal prohibited; row removal would regress banking; branch grant
  inert by construction and outside the lane exception; caller/export/baseline-entry/suppression all
  issue-prohibited). The resolving changes remain the `#1845` integration head (real reviewed runtime
  consumer) and owner-landed develop grants, both outside this leaf — exactly the issue's prescribed
  "report implementation/test readiness plus the explicit merge blocker and leave the stack unmerged".
- Reconciliation status: the issue's five-retained-baseline-entries checkbox remains open pending an
  owner decision outside this leaf; the re-issued CI-repair lane authority ("Ledger amendment is
  permitted and required in CI-repair rounds") is recorded here; banked rows authorize nothing.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration
hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-206 independent verifier + writer re-execution (job 9b611003, head c00faced0b75)

Prior round ended BLOCKED/provider-timeout with 5/5 green driver checks but no report; every
load-bearing fact below was re-derived firsthand at the exact assigned head, no earlier claim assumed:

- Driver logs 5/5 green (`uv sync`, `ruff check .`, `ruff format --check .` 3299 files,
  focused pytest 79 passed, `check-suite-inventory --suite packages/maistro-core/tests` ok 16439).
- Live re-execution greens: focused pytest 79/79 rc=0; focused ruff check rc=0 and format rc=0;
  `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` rc=0 (Success); full
  `check-suite-inventory.py` rc=0 (17 suites, 31323 == 31323, 0 duplicate evidence).
- Contract re-proven by AST walk + live import introspection: 18 ClassDefs = 17 dataclasses all
  `frozen=True, slots=True` + `AdmissionAssessment(StrEnum)`; the six lowercase member/value pairs
  exact and in order; `__all__` 21 unique, set-exact to the issue's 21 names; `owns()` the pure
  3-term scope/generation/owner conjunction; `admitted` exactly `binding is not None` x2;
  `field(repr=False)` x2; `init=False` format versions x2; 0 suppressions; no `__bool__` on the
  empty variants. All 12 issue-named tests defined exactly once (19 functions, 79 collected), with
  substantive assertions (duplicate keys at nesting depth, NaN/Infinity/overflow, subclass-type
  rejection, fencing quadrants including generation==owner coincidence, repr field-omission).
- Scope invariants hold at this head: branch diff vs base ab8b3737 = exactly the 4 in-scope files
  (+2910/-0); 0 production importers of `admission_identity`; no `maistro.runs.__init__` export;
  `quality/` numstat exactly +5/-0 on `vulture-baseline.json` (rows = the 5 scan identities);
  `ratchet-authorizations.json` / `reachability-baseline.json` 0-line diffs; #1841 anchors intact
  and untouched (`store_boundary.py:56`, `store.py:936/:1340` guards, `model.py` field+validation).
- Base motion re-resolved by fresh fetch: `refs/remotes/origin/develop` = 07fac4abd (+2 over base:
  cancellation-codec test 07fac4abd, ontology docstring 369ab9add); neither touches `quality/` nor
  imports `admission_identity`; live `gh pr view 1936` reports MERGEABLE at this head -> no develop
  sync conflict and none warranted; 0 `admission_identity` grants in develop's
  `ratchet-authorizations.json` -> two-merge wall stands.
- CI-exact gates re-run with true exit codes: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (RATCHET_BASE_REV=refs/remotes/origin/develop)
  rc=1, banking GREEN (1322 -> 1327 ledger == scan, unclassified 0, never_allowlist 0),
  authorization RED on exactly the 5 enum identities `:515-520` ("land a reviewed grant first");
  `check-ratchet-provenance.py` rc=1 solely via the reachability leg; `check-reachability.py` rc=1,
  exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity` (170/1402);
  `check-reachability-dispositions.py` / `check-promotion-surface.py` / `check-shipped-surface-truth.py`
  all rc=0. CI test trio reproduced: 3 failed / 36 passed, every failure naming the module
  (`::error title=New unreachable modules::maistro.runs.admission_identity`); Coverage producer root
  cause re-read at `quality.yml:713-714` (`pytest tests/` contains the trio).
- Disposition unchanged: no issue-legal in-leaf change greens the four red gates (the identities are
  the issue's fixed enum contract; row removal regresses banking; a branch-side grant is inert by the
  two-merge rule and issue-prohibited; caller/export/baseline-entry/suppression all issue-prohibited).
  Resolving changes remain the `#1845` integration head and owner-landed develop grants, both outside
  this leaf. Live closure-keyword audit: PR #1936 body has 0 keyword+reference hits ("Refs #1851"
  only); branch note-commit messages carry prose "fixes" mentions that are inert until default-branch
  landing — squash-message scrub recorded for the integration merge. The issue's baseline-reconciliation
  checkbox remains open pending an owner decision outside this leaf; banked rows authorize nothing.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration
hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-207 independent verifier + writer re-execution (job 7c9c85ecd2704cfd998c8a44b718ae1c, head `6346f8e1c0473472327cbcd79af9783618437c6a`, base `ab8b3737fa64`)

Every load-bearing fact re-derived firsthand at the exact assigned head (worktree clean); the prior job (`f3d0993943d64b75b2854c76ba5367a0`) died on a provider timeout AFTER its driver checks finished, so its 5/5 green results were re-executed here, not trusted: focused pytest 79 passed; `ruff check .` clean; `ruff format --check .` 3299 files already formatted; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` Success; `check-suite-inventory.py --suite packages/maistro-core/tests` ok (16439 == recorded, 0 dupes).

Contract re-proven by fresh AST walk (18 ClassDefs = 17 dataclass-decorated, all `frozen=True`+`slots=True`, + 1 StrEnum carrying exactly the six lowercase pairs in issue order `MISMATCH`/`REPLAYED`/`PENDING`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED` at admission_identity.py:515-520); `__all__` 21 names set-exact; `owns()` a single `And` of exactly three `Eq` compares (`scope_key`, `generation_id`, `owner_token`; generation vs owner never compared); `field(repr=False)` x2, `field(init=False)` defaults 2 and 1; both `admitted` properties return exactly `self.binding is not None`; 0 suppression markers; no `__bool__`. All 12 issue-named tests defined exactly once. Scope invariants hold: 0 production importers of `admission_identity`, no `maistro.runs.__init__` export, branch diff vs base exactly the 4 in-scope files (+2960/-0), `quality/` numstat +5/-0 in `vulture-baseline.json` only, `ratchet-authorizations.json` 0-line diff. #1841 anchors intact (`store_boundary.py:56`, `store.py:550`, `model.py:306/:335-336`, guard applied at `store.py:936/:1340`).

Base motion re-resolved by fresh fetch: `refs/remotes/origin/develop` advanced `ab8b3737` -> `6c739f054` (+5; two new since round-206's `07fac4abd`: `498ff93a3` recovery-claims fencing, `7ced47d8c` cancellation receipt projection, `6c739f054` quality grant). No new commit touches `admission_identity`; develop's `ratchet-authorizations.json` still contains no `admission_identity` entry, so the two-merge wall for the five identities stands. The new grant is `design_coverage@39.641` (owner @BlakeMatthews-dev, issue #166) — it authorizes develop's own measured floor fall, not this leaf's identities. File sets are disjoint from this branch's 4 files: no develop sync conflict; the merge-develop remedy stays reserved for actual conflicts and the stack stays unmerged per the standing lane rule.

CI-exact gates with true exit codes: `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 — banking leg GREEN (candidate ledger 1327 == scan 1327, `unclassified: 0`, `never_allowlist: 0`), authorization leg RED exactly on the five enum identities at `admission_identity.py:515-520` with the gate's own remedy "land a reviewed grant first" (grants resolve from merge base `ab8b3737`; branch-side grant inert). `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity` (170/1402). `check-reachability-dispositions.py` rc=0 (49 groups/169 modules); `check-promotion-surface.py` rc=0; `check-shipped-surface-truth.py` rc=0; `check-ratchet-provenance.py` rc=1 solely via the reachability-provenance leg (all other legs OK).

New root-cause refinement this round: the Quality gate's design-coverage leg measured live (`check-ac-state.py --run-tests --ratchet`, bound folded from 40 notes at `ab8b3737`) = **39.5205% < 44.2377 floor** — and *below* develop's newly granted 39.641. Mechanism: the three failing reachability tests carry `@pytest.mark.ac("SPEC-082926-f1c3/AC-1/2/3")` markers; their failure at this head unproves those criteria, dragging measured design coverage under even the owner-authorized re-anchor. Consequence recorded: a develop sync would NOT green the Quality gate while the leaf is unwired — the criterion evidence recovers only when the #1845 integration head makes the module reachable.

Test trio reproduced (`pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py -q`): **3 failed / 49 passed**, every failure naming `maistro.runs.admission_identity` as the extra unreachable module. Coverage-gate root cause re-read in quality.yml: the `coverage-unit` producer DOES run `packages/maistro-core/tests` under `--source=packages/maistro-core/src/maistro`, so the new module's changed lines are test-covered; the gate reds because the aggregate job re-runs the root `tests/` tree as its `scripts` producer, and those same three failures abort the producer before diff coverage.

Ledger-repair clause applied and closed: no fix eliminated any scanned identity (the five are the issue-mandated enum contract; removing them would violate the fixed six-pair requirement), the candidate ledger already equals the scan multiset, so the remove-clause is vacuous and `quality/vulture-baseline.json` stays byte-identical in its correct reviewed state (banked rows authorize nothing). This round's brief re-issues the lane authority ("Ledger amendment is permitted and required in CI-repair rounds"); the issue's baseline-reconciliation checkbox remains open pending an owner decision outside this leaf, and this note records the operative lane-level record without treating it as issue-level approval.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-208 independent verifier + writer re-execution at the assigned head `f447f34e0ce8` (job 9f9c50a26c23400687b595db774686bd)

Unlike round-207 (which documented a docs-commit head `6346f8e1c047`), this round validated the exact assigned leaf head `f447f34e0ce8e948d2c1fda737ee6eae844b89b6` with a clean worktree. The prior job (`46c97fbee22945cab764f7e01dcf1ff6`) died on a provider timeout AFTER its driver checks finished (5/5 green, see its result.json), so every check was re-executed here, not trusted.

Focused acceptance re-executed live: pytest 79 passed (`packages/maistro-core/tests/runs/test_root_admission_identity.py`); `ruff check` and `ruff format --check` clean on both leaf files; mypy Success; `check-suite-inventory.py --suite packages/maistro-core/tests` ok (16439 == recorded, 0 dupes). All 12 issue-named tests defined exactly once each.

Contract re-proven by fresh AST walk at this head: 17 `@dataclass(frozen=True, slots=True)` classes with exact declared field order (including `CanonicalJsonObject.text`), `AdmissionAssessment(StrEnum)` with the six lowercase pairs exact and in issue order at `admission_identity.py:515-520`, `__all__` 21 unique set-exact, `owns()` a pure `And` conjunction of exactly three `Eq` compares, both `admitted` properties exactly `self.binding is not None` (an `IsNot` compare — verified against the corrected AST node kind this round), `owner_token` `field(repr=False)` x2, `format_version` `field(init=False)` x2, no `__bool__` on the five empty variants, 0 suppression markers. NEW this round: direct runtime behavioral probes (not AST-only and not via the test file) — duplicate-key/non-finite/non-object/non-string `CanonicalJsonObject` rejection, whitespace/key-order canonicalization to `{"a":1,"b":2}`, `FrozenInstanceError` on both snapshot and record mutation, the full fencing triple with generation-vs-owner independence, `owner_token` hex absent from `repr(AdmissionRecordV2)` while the equal-valued generation stays printable, `Claimed` rejecting a bound record, default truthiness of `Released()` (no override), and enum value order — all behaved per issue.

Scope invariants hold: branch diff vs base `ab8b3737` is exactly the 4 in-scope files; 0 production importers of `admission_identity`; no `maistro.runs.__init__` export; `quality/` numstat +5/-0 in `vulture-baseline.json` only. #1841 anchors intact (`store_boundary.py:56`, `store.py:550`, `actor_principal_id` guards at `store.py:507/576/907/1299`).

Base motion re-resolved by fresh fetch: `refs/remotes/origin/develop` advanced `6c739f054` -> `c2a22e55d` (+2 since round-207: `c0839cae7` provenance tool_version #319, `c2a22e55d` strict M1-closeout mode #2146). Neither lands an `admission_identity` grant (develop's `ratchet-authorizations.json` and `reachability-baseline.json` contain zero `admission_identity` entries) nor touches `packages/maistro-core/src/maistro/runs/`; develop's file sets are disjoint from this branch's 4 files, so no sync conflict exists and the two-merge wall for the five enum identities stands.

CI-exact gates with true exit codes (rc captured without pipes): `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 — banking leg GREEN (base 1322 -> scan 1327, `unclassified: 0`, `never_allowlist: 0`, candidate ledger banks all five admission_identity rows), authorization leg RED exactly on the five enum identities `MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED` at `admission_identity.py:515-520` with the gate's own remedy "land a reviewed grant first"; `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity`; `check-reachability-dispositions.py` rc=0; `check-promotion-surface.py` rc=0. Test trio reproduced (`pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py -q`): 3 failed / 49 passed, every failure naming this module as the extra unreachable module — the issue-mandated unwired state, not a regression.

Ledger-repair clause re-applied and closed: no fix eliminated any scanned identity (the five are the issue's fixed enum contract), the candidate ledger already equals the scan as banked, so the remove-clause is vacuous and `quality/vulture-baseline.json` stays byte-identical; banked rows authorize nothing and the issue's baseline-reconciliation checkbox remains open pending an owner decision outside this leaf.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-209 independent verifier + writer re-execution at the assigned head `4d188cbe` (job 6415fd003a884cb0b95ead4e5e688f07)

Validated the exact assigned leaf head `4d188cbe795d55eb6abacd99e5507fbd2ef362e9` with a clean worktree (base `ab8b3737fa64`). The immediately prior job (`e0db758196bb49f4a821bcad1a40a270`) died on a provider timeout AFTER its driver checks finished (5/5 green per its result.json), so every check was re-executed here, not trusted.

Focused acceptance re-executed live: pytest 79 passed; `ruff check` and `ruff format --check` clean on both leaf files; mypy Success; full `check-suite-inventory.py` ok (17 suites, 31323 == recorded, 0 dupes) and the focused `--suite packages/maistro-core/tests` run ok (16439 == recorded, 0 dupes). All 12 issue-named tests defined exactly once each.

Contract re-proven by fresh AST walk at this head: 18 ClassDefs = 17 `@dataclass(frozen=True, slots=True)` classes (no non-frozen/non-slots dataclass) + `AdmissionAssessment(StrEnum)` carrying exactly the six lowercase pairs in issue order at `admission_identity.py:515-520`; `__all__` 21 unique set-exact; `owns()` a single `And` of exactly three `Eq` compares; both `admitted` properties decorated `@property` returning exactly `self.binding is not None`; `field(repr=False)` x2; `field(init=False)` defaults 2 and 1; no `__bool__` anywhere; 0 `type: ignore`/`noqa` markers in the module. NEW direct runtime behavioral probes at this head (in-process, not via the test file): duplicate-key/non-finite/non-object/non-string `CanonicalJsonObject` rejection plus whitespace/key-order canonicalization to the exact `sort_keys` form; `FrozenInstanceError` on ticket mutation; the full fencing triple (matching, wrong owner, wrong scope, wrong generation); `owner_token` hex absent from `repr(AdmissionRecordV2)` while a coincidentally equal-valued `generation_id` stays printable; `Claimed` accepted on the unbound owned record; default truthiness of `Released()` (no override); nil-UUID and string-UUID rejection. All behaved per issue.

Scope invariants hold: branch diff vs base is exactly the 4 in-scope files (+2996/-0 at validation time); 0 production importers of `admission_identity`; no `maistro.runs.__init__` export; `quality/` numstat +5/-0 in `vulture-baseline.json` only (the five reviewed enum rows at `quality/vulture-baseline.json:283-287`). #1841 anchors intact (`store_boundary.py:56` `require_admitted_actor`, `store.py:550` `get_run(..., principal_id=...)`, `store.py:499/:567/:899` `create_run`/`claim_run_by_effect`, `model.py:306/:335-336` `actor_principal_id` stored and validated).

Base motion re-resolved by fresh fetch: `refs/remotes/origin/develop` unchanged at `c2a22e55d` since round-208 — no new commits, develop's `ratchet-authorizations.json` and `reachability-baseline.json` still contain zero `admission_identity` entries, so the two-merge wall stands and no sync conflict exists. The prior lane's "recovery budget exhausted / gh rate limit" block was tooling-side, not a tree defect.

All four CI gate failures reproduced at this head with true exit codes (rc captured without pipes): (1) `exact-debt-ledger`: `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 — banking leg GREEN (scan 1327 == candidate ledger 1327, `unclassified: 0`, `never_allowlist: 0`; the five identities banked), authorization leg RED exactly on the five enum identities at `:515-520` with the gate remedy "land a reviewed grant first"; `check-shipped-surface-truth.py` rc=0. (2) `test`: the reachability trio reproduced (`pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py -q`) = **3 failed / 49 passed** — `test_baseline_matches_the_tree`, `test_the_committed_baseline_passes_the_gate_it_now_carries`, `test_the_baseline_is_exactly_the_unreachable_set`, every failure naming `maistro.runs.admission_identity`; the other 49 pass. (3) Quality gate: `check-reachability.py` rc=1 (exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity`, 170/1402), `check-reachability-provenance.py` rc=1 (NEW unreachable absent from trusted base + missing from candidate baseline), `check-ratchet-provenance.py` rc=1 solely via that reachability leg (enumeration and lifecycle legs OK); the design-coverage leg stays sub-floor because the three failing tests carry `@pytest.mark.ac` markers (`SPEC-082926-f1c3/AC-1`, `ADR-082526-aef8/*`) whose failure unproves their criteria. (4) Coverage gate: producer root cause re-read at `quality.yml:713-714` — the aggregate producer runs `pytest tests/` which aborts on the same trio, so the red is downstream of (2), not uncovered leaf lines. `check-reachability-dispositions.py` rc=0 (49 groups/169 modules) and `check-promotion-surface.py` rc=0.

Ledger-repair clause applied and closed for this round: the clause's list-unbanked step names exactly the five issue-mandated enum identities; no fix can eliminate them (they are the fixed six-pair `AdmissionAssessment` contract and wiring a consumer is the `#1845` integration head); the candidate ledger already banks them, so the amend step is already satisfied and the remove step is vacuous — `quality/vulture-baseline.json` stays byte-identical in its correct reviewed state. The issue's baseline-reconciliation checkbox remains open pending an owner decision outside this leaf; banked rows authorize nothing.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-210 independent verifier + writer re-execution at the assigned head `1ee6507b07ca` (job 7e053554658a49a4a1b946b0484ea4b2)

Unlike rounds 205–209 (whose driver jobs died on provider timeouts after their checks ran), this round's driver **completed**: all five checks green live (`uv sync --locked --extra dev`; `ruff check .` "All checks passed"; `ruff format --check .` 3299 files already formatted; focused pytest **79 passed**; `check-suite-inventory.py --suite packages/maistro-core/tests` ok 16439 == recorded, 0 dupes) — see the job's check-0..4 logs and the prior job `1cfc790f` result.json (5/5 rc=0). Every load-bearing fact below was re-derived firsthand at this head with a clean worktree; nothing trusted from prior rounds.

Focused acceptance re-executed live (true exit codes): pytest 79 passed rc=0; `ruff check` and `ruff format --check` on both leaf files rc=0; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` Success rc=0; full `check-suite-inventory.py` rc=0 (17 suites all matching, 0 dupes). All 12 issue-named tests defined exactly once each.

Contract re-proven by a fresh 45-probe AST + runtime walk at this head: 17 `@dataclass(frozen=True, slots=True)` classes; `AdmissionAssessment(StrEnum)` with exactly the six lowercase pairs in issue order at `admission_identity.py:515-520`; `__all__` 21 unique set-exact; `owns()` a single `And` of exactly three `Eq` compares; `field(repr=False)` x2 at `:198/:270`; `field(init=False)` x2 at `:274/:334`; no `__bool__`; 0 suppression markers. Runtime probes all behaved per issue: `CanonicalJsonObject` whitespace/key-order canonicalization to the exact `sort_keys` compact form and rejection of duplicate keys (flat + nested), non-finite, non-object roots, non-string constructor input, invalid JSON; nil-UUID and string-UUID rejection; whitespace-ID rejection; bool `_us` rejection; `expires<=created` rejection; `FrozenInstanceError` on record and snapshot mutation; the full fencing triple (matching / wrong generation / wrong owner / wrong scope); `owner_token` hex absent from `repr(AdmissionRecordV2)` while a coincidentally equal-valued `generation_id` stays printable (count==1); `Claimed` rejecting bound records and wrong tickets; `Replayed` requiring a binding and accepting bound-unacknowledged; `LegacyUnresolved` carrying no invented identity; `Released()` default truthiness; `RootAdmissionResult` snapshot run_id match/mismatch and `created` rejecting int 1.

Scope invariants hold: branch diff vs merge-base `ab8b3737` is exactly the 4 in-scope files, +3014/-0 (note growth from round entries only); 0 production importers of `admission_identity`; no `maistro.runs.__init__` export; `quality/` numstat +5/-0 in `vulture-baseline.json` only (the five reviewed enum rows at `quality/vulture-baseline.json:283-287`). #1841 anchors intact (`store_boundary.py:56` `require_admitted_actor`, `store.py:550` `get_run(..., principal_id=...)`, `actor_principal_id: str | None = None` retained at `store.py:507/576/907/1299`, `model.py:306/:335-336` stored and validated).

Base motion re-resolved by fresh fetch (rc=0): `refs/remotes/origin/develop` **advanced** `c2a22e55d` -> `2f56be40` — this job's assigned base `2f56be40` is a descendant of round-209's recorded tip (develop moved forward; no reset, no force-push). New commits: WIP milestone/roadmap control plane (#2163/#2154/#2160/#2156), canonical-graph-authority merge (#1991/#1113), cutover sentinel merge (#1993), plus develop-side provenance `tool_version` (#2142) touching `scripts/check-vulture-baseline.py` additively. Checks that matter: develop's `ratchet-authorizations.json` and `reachability-baseline.json` contain **zero** `admission_identity` entries (the only new grant is develop's own `design_coverage@39.641`, owner-authorized, unrelated to this leaf), and the leaf's module/test files are **absent** from develop's tree — so the `#1845` integration hold stands, the two-merge wall for the five enum identities stands, and develop's file motion is disjoint from this branch's 4 files: no sync conflict, none warranted. The prior lane's "recovery budget exhausted / gh API rate limit" block was tooling-side and did not recur (plain git fetch succeeded); no tree defect existed to fix.

All four CI gate failures reproduced with true exit codes (rc captured without pipes): (1) `exact-debt-ledger`: `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 — banking leg GREEN (1322 -> 1327, candidate ledger == scan, `unclassified: 0`, `never_allowlist: 0`), authorization leg RED exactly on the five enum identities at `:515-520` with the gate remedy "land a reviewed grant first" (grants resolve from the trusted base, so a branch-side grant is inert by construction). (2) `test`: the reachability trio reproduced (`pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py -q`) = **3 failed / 49 passed** — `test_baseline_matches_the_tree`, `test_the_committed_baseline_passes_the_gate_it_now_carries`, `test_the_baseline_is_exactly_the_unreachable_set`, every failure naming `maistro.runs.admission_identity` as the extra unreachable set member (the issue-mandated unwired state, not a regression). (3) Quality gate: `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity`; `check-reachability-dispositions.py` rc=0; `check-promotion-surface.py` rc=0. (4) Coverage gate: unchanged producer root cause (`quality.yml` aggregate producer aborts on the same trio), i.e. downstream of (2), not uncovered leaf lines.

Ledger-repair clause applied and closed for this round: the unbanked list names exactly the five issue-mandated enum identities; no fix can eliminate them (they are the fixed six-pair `AdmissionAssessment` contract; wiring the consumer is the `#1845` integration head); the candidate ledger already banks all five (`quality/vulture-baseline.json:283-287`), so the amend step is already satisfied, the remove step is vacuous, and `quality/vulture-baseline.json` stays byte-identical in its correct reviewed state (`git status --porcelain quality/` empty). Banked rows authorize nothing; the issue's baseline-reconciliation checkbox remains open pending an owner decision outside this leaf.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the `#1845` integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-211 independent verifier + writer re-execution at the exact assigned head `127165fae6f6` (job c8a21931d1bb4d449334cee4a06d73e6)

Driver completed (check-0..4 logs all green: `uv sync --locked --extra dev` resolved 256/checked 214; `ruff check .` "All checks passed!"; `ruff format --check .` 3307 files already formatted; focused pytest **79 passed**; `check-suite-inventory.py --suite packages/maistro-core/tests` ok 16505 == recorded, 0 dupes); prior job `b6c3606967e4` result.json 5/5 rc=0 at the same SHA. Worktree clean at the exact assigned head; every fact below re-derived firsthand; nothing trusted from prior rounds.

Leaf acceptance re-executed live (true exit codes): focused pytest 79 passed rc=0; `ruff check` + `ruff format --check` on both leaf files rc=0; `mypy` on the module Success rc=0; **full `pytest packages/maistro-core/tests --timeout=30 -q` = 15429 passed, 1073 skipped, 3 xfailed** (first round to execute the whole coverage-unit producer suite locally). All 12 issue-named tests defined exactly once each. Fresh runtime probes: `__all__` 21 names set-exact; `AdmissionAssessment` six lowercase pairs exact+order at `:515-520`; `CanonicalJsonObject` canonicalization to the exact `sort_keys` compact form plus duplicate-key/non-finite/non-object/invalid-JSON rejection; `FrozenInstanceError` on ticket mutation; `owner_token` absent from `repr()` in both hex and hyphenated forms while the generation UUID stays printable; `owns()` fencing triple (matching / wrong generation / wrong owner / wrong scope); `admitted` false on the unbound record. Scope invariants: 0 production importers, no `maistro.runs.__init__` export, branch diff vs base `1a2e12656` exactly 4 in-scope files, #1841 anchors intact (`store_boundary.py:56` `require_admitted_actor(actor_principal_id: str | None) -> str`; `actor_principal_id: str | None = None` retained at `store.py:507/576/907`). Diff coverage measured with CI's own script against the base: `check-diff-coverage.py coverage.xml --base 1a2e12656...` -> ok, "every measured file this change touches is at or above 90% lines / 80% branch arcs" (test file exempt by declaration); the publish-set pytest legs all pass, so the coverage gate's leaf content is sound. `check-shipped-surface-truth.py` rc=0, `check-reachability-dispositions.py` rc=0, `check-promotion-surface.py` rc=0.

Base motion re-resolved by fresh fetch rc=0: `origin/develop` unchanged at `1a2e12656` == this job's merge base — no grant landed, no sync motion; the two-merge wall and the `#1845` integration hold stand.

All six CI gate failures reproduced with true exit codes and reduced to exactly two structural root causes, each issue-documented as the expected unwired-leaf state ("A candidate baseline update cannot grant itself permission"; "check-reachability.py would classify the new module as newly unreachable"; "If that integration is unavailable, report implementation/test readiness plus the explicit merge blocker and leave the stack unmerged"): (A) vulture authorization — `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 with banking GREEN (1322 -> 1327, candidate ledger == scan, `unclassified: 0`, `never_allowlist: 0`) and authorization RED exactly on the five enum identities at `:515-520` ("land a reviewed grant first"); grants resolve from `quality/ratchet-authorizations.json` at the base revision (`ratchet_provenance.load_authorizations`), so a branch-side grant is inert by construction and forbidden by the leaf; eliminating the identities would require deleting contract-pinned enum members or adding fake callers/suppressions/`__all__` entries, all prohibited — so `exact-debt-ledger` and `Quality / Vulture` stay red by design until the `#1845` integration head wires the consumer (or a reviewed grant lands at the base first). (B) reachability — `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity`; `check-reachability-provenance.py` rc=1 (NEW unreachable absent from trusted base AND missing from candidate baseline — its dual conditions prove no in-branch baseline edit can turn it green); `check-ratchet-provenance.py` rc=1 solely via that inventory leg; the `test` job's reachability trio reproduced exactly (`pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py -q`) = **3 failed / 49 passed** (`test_baseline_matches_the_tree`, `test_the_committed_baseline_passes_the_gate_it_now_carries`, `test_the_baseline_is_exactly_the_unreachable_set`, each naming `maistro.runs.admission_identity`); `Coverage gate` is red downstream — `quality.yml`'s combine step runs `pytest tests/` (the `--source=scripts` producer) under `set -euo pipefail`, which aborts on the same trio; `Quality gate (Pillars 1–4, 7, 8)` is a summary job whose `needs:` include `quality-vulture` and `quality-reachability`, so it is red downstream of (A)+(B). No leaf-level defect: the aggregate floor leg and per-file diff-coverage leg both pass when measured directly.

Ledger-repair clause applied and closed for this round: the unbanked list names exactly the five issue-mandated enum identities; no fix eliminates them (fixed six-pair contract; the consumer is the `#1845` integration head), the candidate ledger already banks all five (`quality/vulture-baseline.json:283-287`), so the amend step is satisfied, the remove step is vacuous, and the file stays byte-identical in its correct reviewed state; banked rows authorize nothing. Baseline-reconciliation checkbox remains open pending an owner decision outside this leaf.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); both root causes are the documented merge blockers resolved only at the `#1845` integration head; the integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-212 independent verifier + writer re-execution at the exact assigned head `3c4b19b0f5e9` (job c5d74d72b7dc)

Driver completed 5/5 green (check-0..4 logs: uv sync; `ruff check .` "All checks passed!"; `ruff format --check .` 3308 files; focused pytest **79 passed**; `check-suite-inventory.py --suite packages/maistro-core/tests` ok **16520 == recorded**, 0 dupes). Worktree clean at the exact assigned head `3c4b19b0f5e9989816b35147ec07a99322b0483a`; every fact below re-derived firsthand; nothing trusted from prior rounds. This is the round the lane brief names as an explicit exact-debt-ledger CI-repair round ("Ledger amendment is permitted and required in CI-repair rounds").

- Focused acceptance re-executed live (true exit codes): focused pytest 79 passed rc=0; `ruff check` + `ruff format --check` rc=0; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` Success rc=0; leaf coverage measured directly: `pytest .../test_root_admission_identity.py --cov=maistro.runs.admission_identity --cov-branch` → **100% lines (245/245) and 100% branches (82/82)** — the Coverage gate red is purely the downstream `pytest tests/` abort, not uncovered leaf lines. Fresh runtime probes: canonicalization to exact `sort_keys` compact form plus rejection of duplicate keys / NaN / Infinity / non-object / non-string / invalid JSON; lease-window invariant (`created <= lease <= expires`) enforced; fencing triple; `owner_token` absent from `repr()` in hex AND hyphenated forms while `generation_id` stays printable; `FrozenInstanceError`; six enum pairs in issue order; default truthiness of `Released()`.
- Contract re-proven by AST: `__all__` exactly the 21 issue names (sorted, set-exact, unique); `AdmissionAssessment(StrEnum)` exactly the six lowercase pairs in issue order at `:515-520`; 17 `@dataclass(frozen=True, slots=True)` classes; `field(repr=False)` x2. Scope invariants: branch diff vs merge-base `9a4b0c5cc0fc` is exactly the 4 in-scope files (+3046/-0); 0 production importers of `admission_identity`; no `maistro.runs.__init__` export; `quality/` numstat +5/-0 in `vulture-baseline.json` only; `ratchet-authorizations.json` and `reachability-baseline.json` byte-identical base↔branch; #1841 anchors intact (`store_boundary.py:56`, `store.py:507/576/907`).
- **exact-debt-ledger reduced with CI-exact argv and true exit codes.** The job runs three steps: `check-ratchet-provenance.py` → rc=1 solely via the reachability leg (`maistro.runs.admission_identity`: NEW unreachable, absent from trusted base AND missing from candidate baseline — the dual condition proves no in-branch `reachability-baseline.json` edit can turn it green); `check-shipped-surface-truth.py` → rc=0; `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (RATCHET_BASE_REV=origin/develop) → rc=1 with banking leg GREEN (scan 1327 == candidate ledger 1327, `unclassified: 0`, `never_allowlist: 0`, candidate added/removed/unbanked all empty) and authorization leg RED exactly on the five issue-mandated enum identities (`MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`, `:515-520`) with the gate's own remedy "land a reviewed grant first". The brief's "list unbanked identities" step returns an EMPTY unbanked list: the amendment the same brief calls "required" is already satisfied by the banked rows (`quality/vulture-baseline.json:283-287`, multiset-exact vs the scan, re-parsed and re-compared this round).
- Base motion re-resolved by fresh plain-git fetch rc=0: `origin/develop` advanced `ce2048cd2` → `8b4b648bb` (one docs-only commit, `#2202`, file set disjoint from this branch's 4 files — no sync conflict, none warranted). Grep of develop's `ratchet-authorizations.json`, `reachability-baseline.json`, and `vulture-baseline.json` for `admission_identity`: **0 hits each** — no grant landed, so the two-merge wall (`ratchet_provenance.load_authorizations` reads grants from the base revision; a branch-side grant is inert by construction AND issue-prohibited: "No fake callers, baseline additions, grants, disabled gates or quality waivers are permitted") stands. The five identities are the issue's fixed six-pair enum contract, not genuinely dead code, so the repair clause's "fix what is genuinely dead" has no object and "remove identities your fix eliminated" is vacuous — the ledger stays byte-identical in its correct reviewed state.
- **New refinement this round (full root-tree execution, not just the trio):** `pytest tests/ --ignore=tests/tools/registry -q` = 4 failed / 5272 passed / 135 skipped. Beyond the 3 leaf-named reachability failures, `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once` fails with `unclassified quality state: quality/ac-state.json` — **provably independent of this leaf**: `quality/branch-independence.json`, `quality/ac-state.json`, and `scripts/check-branch-independence.py` are byte-identical at merge-base and HEAD (the branch's only quality/ delta is the +5 vulture rows, and `vulture-baseline` remains a registered surface), so the identical failure exists at the base and belongs to the lane that landed the `ac-state.json` grant (#166 re-anchor). Consequence for the integration head: wiring the #1845 consumer greens the reachability trio but does NOT by itself green the `test` job — the ac-state surface classification must also land.
- Reconciliation recorded (issue text vs lane brief): the issue's staging constraint forbids baseline additions, while this round's lane brief explicitly authorizes/requires the vulture-ledger amendment in an exact-debt-ledger CI-repair round; the amendment already stands from the prior round, banked rows authorize nothing, and the issue's baseline-reconciliation checkbox remains open pending an owner decision outside this leaf. No issue-closure keyword added.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); both structural reds are the issue-documented merge blockers resolvable only at the `#1845` integration head or by owner-landed develop grants; the integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-213 independent verifier + writer re-execution at the exact assigned head `64fbdb32718d` (job 19dcfe696eec411b8939b8ff7f4ae8b8)

Driver completed 5/5 green (check-0..4 logs: uv sync; `ruff check .` "All checks passed!"; `ruff format --check .` 3309 files; focused pytest **79 passed** in 1.20s; `check-suite-inventory.py --suite packages/maistro-core/tests` ok **16520 == recorded**, 0 dupes). Worktree clean at the exact assigned head `64fbdb32718dd7d8ef24be5e51bcdf0dc8546252`; every fact below re-derived firsthand in this round; the prior round's provider timeout (`result.json` failure_kind=provider_error) left no uncommitted work to salvage.

- Focused acceptance re-executed live (true exit codes): focused pytest **79 passed** rc=0; `ruff check` + `ruff format --check` on both leaf files rc=0; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` **Success** rc=0; branch coverage measured directly (`coverage run --branch -m pytest ...` + `coverage report --include='*admission_identity*'`): module **245 stmts / 0 miss, 82 branches / 0 partial → 100% lines and 100% branches**.
- Runtime probes re-run firsthand, all green: canonicalization to exact `sort_keys` compact form with string values untouched; rejection of duplicate keys / `NaN` / non-object root with `ValueError`; fencing triple (matching-scope+generation+owner → True; each single-role difference → False); roles-equal and roles-differ cases both own (roles never compared to each other); `owner_token` absent from `repr()` while the independently printable `generation_id` keeps its text in both UUID spellings; `FrozenInstanceError` on mutation; `Claimed` validates ticket+record identity; `[m.value for m in AdmissionAssessment]` exactly `["mismatch","replayed","pending","takeover","replace_expired","legacy_unresolved"]`.
- **exact-debt-ledger re-reduced with CI-exact argv** (`.github/workflows/vulture-ratchet.yml:71-83`, trusted base resolves to merge-base `140e88180847`): `check-shipped-surface-truth.py` rc=0; `check-ratchet-provenance.py` rc=1 solely via `check-reachability-provenance.py` (`maistro.runs.admission_identity`: NEW unreachable, absent from trusted base AND missing from candidate baseline — the dual condition proves no in-branch `reachability-baseline.json` edit can turn it green); `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 with the banking leg GREEN (1322 reviewed identities → 1327 findings, `unclassified: 0`, `never_allowlist: 0`) and the authorization leg RED exactly on the five issue-mandated enum identities at `admission_identity.py:515-520`, gate remedy "land a reviewed grant first". The brief's "list unbanked identities" step returns an EMPTY unbanked list — the required amendment already stands (`quality/vulture-baseline.json:283-287`, re-parsed this round: rule `pydantic-declarative-field` contains exactly the 5 admission rows); nothing genuinely dead to fix (the identities are the issue's fixed six-pair enum contract), "remove identities your fix eliminated" is vacuous, and a branch-side grant in `quality/ratchet-authorizations.json` is inert by construction (`load_authorizations` reads the base revision) and issue-prohibited — 0 `admission_identity` entries re-confirmed in that file and `quality/reachability-baseline.json` on BOTH the branch and develop.
- Leaf constraints re-proven: 0 production importers of `admission_identity` outside the module itself; no `maistro.runs.__init__` export; branch footprint vs merge-base `140e88180` is exactly the 4 in-scope files + `quality/vulture-baseline.json` (+5/-0, `git diff --numstat`); #1841 anchors intact at this head (`store_boundary.py:56` `require_admitted_actor`, `store.py:550` `get_run(..., principal_id=...)`, `store.py:507/576/907` `actor_principal_id: str | None = None`, `model.py:306` Run field + `:335-336` validation).
- Reachability trio reproduced: `pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py -q` → 3 failed / 49 passed, each failure the same `Extra items in the left set: 'maistro.runs.admission_identity'` — the issue-documented structural red for an intentionally unwired leaf.
- **Correction to the round-212 ac-state explanation:** `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once` fails locally with `unclassified quality state: quality/ac-state.json` because `scripts/check-branch-independence.py::discover_quality_json` rglobs the working **disk**, and `quality/ac-state.json` is an **untracked, gitignored local artifact** (`.gitignore:81`), present only on verification machines — it is not committed at the merge-base, at `6b631928`, at HEAD, or on develop, so CI checkouts cannot see it and the CI `test` job fails only the 3 reachability tests. The failure is independent of this leaf (the branch's only `quality/` delta remains the +5 vulture rows), but the round-212 "byte-identical at merge-base and HEAD" wording was wrong about an untracked file; the correct statement is the disk-scan/untracked-artifact mechanism above, and no `ac-state` surface classification is owed from this lane.
- Base motion re-resolved by fresh plain-git fetch rc=0 (no gh API): `origin/develop` advanced `8b4b648bb` → `f72d4fc92` (adds `6b631928b` #2164 sandbox capture, `b799da6c6` #2166, `f72d4fc92` #2206); merge-base with the branch is unchanged at `140e88180`, and `git diff --name-only 140e88180..origin/develop` has **zero overlap** with this branch's 4 files — no sync conflict, none warranted. No develop ledger gained an `admission_identity` grant, so the two-merge wall stands.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); the exact-debt-ledger/vulture/reachability/test reds are the issue-documented structural merge blockers, resolvable only at the `#1845` integration head with the real consumer or by owner-landed develop grants; the integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-214 independent verifier + writer re-execution at the exact assigned head `f342ce73be73` (job abf9960039164e5c8f2e9fe781e5c961)

Driver completed 5/5 green (check-0..4 logs: `uv sync --locked --extra dev`; `ruff check .` "All checks passed!"; `ruff format --check .` 3325 files; focused pytest **79 passed** in 1.69s; `check-suite-inventory.py --suite packages/maistro-core/tests` ok **16542 == recorded**, 0 dupes, 0 redundant bytes). Worktree clean at the exact assigned head `f342ce73be73581ab265d6262789b5b71deff7d8`; this is the first round recorded at this head — the lane merged the assigned develop base `eec7a587039e` (previous recorded round-213 head was `64fbdb32718d`); the merge brought develop-only quality state (`quality/ac-state-notes/auto-788.json`, `quality/shipped-surface-truth.json`, `quality/workflow-inventory.json`) and moved the collected maistro-core/tests total 16520 → 16542; the leaf's recorded delta stays `+79`. Every fact below re-derived firsthand at this head; no earlier claim trusted.

- Focused acceptance re-executed live (true exit codes): focused pytest **79 passed** rc=0 (all 12 issue-named tests defined once, 19 test functions total); `ruff check` + `ruff format --check` on both leaf files rc=0; `mypy packages/maistro-core/src/maistro/runs/admission_identity.py` **Success** rc=0; full suite inventory re-run rc=0 (16542 == recorded).
- Runtime probes re-run firsthand, all green: `__all__` 21 names set-exact; `AdmissionAssessment` StrEnum with the six lowercase pairs exact+order; 17 dataclasses all `frozen=True, slots=True`; canonicalization to exact `sort_keys` compact form with string values untouched, rejecting duplicate keys / `NaN` / `1e999` overflow / non-object roots / non-string input; fencing triple (`owns` True on the matching scope+generation+owner ticket; each single-role difference → False; roles-equal and roles-differ records both own a matching ticket — roles never compared to each other); `owner_token` absent from `repr()` in both equal- and differing-role spellings while the independently printable `generation_id` keeps its text; `FrozenInstanceError` on record and snapshot mutation; `Claimed` requires unbound + owning (mismatched owner and bound record both rejected); `Replayed` requires a binding (v2 and legacy), `Pending` requires unbound v2, `LegacyUnresolved` requires unbound legacy, each cross-variant rejected; legacy `lease_expires_at_us` not clamped to expiry; v2 lease window `created <= lease <= expires` enforced; `acknowledged_at_us` requires a binding and >= creation; binding receipt must equal envelope receipt; `RootAdmissionResult.created` rejects integer 1 and requires snapshot `run_id` agreement; empty variants (`Released`/`StaleOwner`/`Acknowledged`/`AlreadyAcknowledged`/`BindingMismatch`) define no `__bool__`/`__len__`.
- Leaf scope invariants hold at this head: 0 production importers of `admission_identity` outside the module itself (grep over `packages/*/src` + hive-conductor); no `maistro.runs.__init__` export; branch diff vs the assigned base `eec7a587` is **exactly the 4 in-scope files** (+3073/-0: module 520, tests 660, note 1888, vulture-baseline +5); `git diff --numstat` over `quality/` is exactly +5/-0 (`quality/vulture-baseline.json`); `quality/ratchet-authorizations.json` and `quality/reachability-baseline.json` are 0-line diffs (no self-grant, no waiver).
- #1841 security anchors re-read intact at this head: `store_boundary.py:56` `require_admitted_actor(actor_principal_id: str | None) -> str`; `store.py:550` `get_run(self, run_id, *, principal_id: str | None = None)`; `store.py:507/576` `actor_principal_id: str | None = None`; `model.py:306` `Run.actor_principal_id: str | None`.
- CI-exact gates re-run with true exit codes (argv from `.github/workflows/vulture-ratchet.yml:71-83` and `quality.yml:1461-1464`): `check-shipped-surface-truth.py` rc=0; `check-reachability-dispositions.py` rc=0; `check-promotion-surface.py` rc=0; `check-reachability.py` rc=1 with exactly **1 NEWLY UNREACHABLE**: `maistro.runs.admission_identity` (issue-anticipated for an intentionally unwired leaf; a baseline entry is issue-prohibited); `check-ratchet-provenance.py` rc=1 solely via the `check-reachability-provenance.py` leg (enumerations and lifecycle legs OK against base `eec7a587`); `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1 with the **banking leg GREEN** (1327 findings, `unclassified: 0`, `never_allowlist: 0`, candidate ledger banks the full scan) and the **authorization leg RED exactly on the five issue-mandated enum identities** at `admission_identity.py:515-520` (`MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`), gate remedy "land a reviewed grant first" — grants resolve from the base revision (`eec7a587` carries no `admission_identity` grant), so the branch-side banked rows (+5 at `vulture-baseline.json`) authorize nothing by construction; the reconciliation checkbox remains open pending an owner decision outside this leaf.
- Reachability trio reproduced at this head: `pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py tests/test_reachability_scanner.py tests/test_reachability_source_universe.py -q` → the same `Extra items in the left set: 'maistro.runs.admission_identity'` failures — the issue-documented structural red for the unwired leaf, not a regression.
- ac-state clarification re-confirmed post-merge: `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once` fails locally with `unclassified quality state: quality/ac-state.json`, caused by `discover_quality_json` rglobbing the disk where `quality/ac-state.json` is an **untracked, gitignored local artifact** (`.gitignore:81`; `git ls-files` confirms it is not tracked while `quality/ac-state-notes/*` are) — CI checkouts cannot see it, so the CI `test` job fails only the 3 reachability tests; the failure is independent of this leaf.
- Closure-keyword audit: PR #1936 body carries only "Refs #1851" (no fixes/closes/resolves); branch commit messages contain no closure-keyword trailer (one historical prose "only fixes: #1845" adjacency in the round-199 note-commit `d30d9a1bc9` remains branch-only/inert until default-branch landing — the recorded squash-at-integration mitigation stands); this commit adds no closure keyword.

Verdict: writer handoff MERGE-READY (handoff only, never integration approval); all leaf acceptance criteria are proven at the exact assigned head, and the exact-debt-ledger/vulture/reachability/test reds are the issue-documented structural merge blockers, resolvable only at the `#1845` integration head with the real consumer or by owner-landed develop grants; the integration hold stands; stack left unmerged; no inventory delta (stays +79). (Refs #1851)

## Round-215 CI-repair verification at the exact CI-evaluated head `7ce0ba6e0859` (job `d7f355ece1fb4e11a3140cf6724f7b6c`)

Assigned repair of the merge-queue-reported `exact-debt-ledger` failure at the exact head CI
actually evaluated (`7ce0ba6e08596f87db50dbfd11950ed676316a0c`, branch `auto-1851`, develop base
`420d503d4156225907ec673b1e70caa19101241d`); worktree clean at start; no earlier claim trusted.
Relative to round 214 the lane merged develop's pylint bump `339fb9053` into this branch, so the
gates' trusted base is now `339fb9053` (its `uv.lock`-only delta moves no production surface; the
trusted vulture ledger carries 1322 rows, none for this module).

Re-derived firsthand at this head (all with true exit codes):

- Driver 5/5 green (check-0..4 logs): `uv sync --locked --extra dev` rc=0; `ruff check .` "All
  checks passed!"; `ruff format --check .` 3325 files already formatted; focused pytest **79
  passed** in 1.14s; `check-suite-inventory.py --suite packages/maistro-core/tests` ok **16542 ==
  recorded**, 0 dupes, 0 redundant bytes. Leaf delta stays `+79`.
- Contract re-proven live: focused pytest 79 passed under `coverage run`; the module measures
  **100% (245/245 statements, 0 miss)**. Runtime probe green: `__all__` 21 names set-exact (the
  contract test pins the deterministic alphabetical order, test lines 129-153); `AdmissionAssessment`
  six lowercase pairs exact and in issue order; 17 dataclasses all `frozen=True, slots=True`;
  canonicalization to exact `sort_keys` compact form rejecting duplicate keys / non-object roots /
  invalid JSON / `NaN` / `1e999` / dict input; fencing triple with each single-role difference
  cross-rejected and the roles-equal case owning a matching ticket while roles are never compared
  to each other; `owner_token` absent from `repr()` in both roles-equal and roles-differ spellings
  while the independently printable `generation_id` keeps the text; `FrozenInstanceError` on
  mutation; `Claimed`/`Replayed`/`Pending`/`LegacyUnresolved` cross-variant guards; legacy lease
  unclamped; v2 lease window; ack requires binding and `>=` creation; binding receipt equality;
  `RootAdmissionResult.created` rejects integer `1` and requires snapshot `run_id` agreement.
- `exact-debt-ledger` job steps re-run with CI-exact argv: `check-ratchet-provenance.py` rc=1
  **solely** via the reachability leg ("`maistro.runs.admission_identity`: NEW unreachable module
  absent from trusted base and not previously authorized" + the missing candidate baseline entry)
  and its `check-reachability-provenance.py` delegate returning 1; every other provenance leg OK
  against base `339fb9053`. `check-shipped-surface-truth.py` rc=0.
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` rc=1
  with the **banking leg GREEN and exact** (1327 findings; `unclassified: 0`; `never_allowlist: 0`;
  importing the checker's own `_rule_deltas` over the real scan: candidate ledger deltas = 0, i.e.
  multiset-equal banking) and the **authorization leg RED exactly on the five issue-mandated enum
  identities** at `admission_identity.py:515-520` (`MISMATCH`/`REPLAYED`/`TAKEOVER`/
  `REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`; `PENDING` is shielded by the live same-name member of
  `maistro/tasks/idempotency.py` inside the same scanned tree — the issue-anticipated favorable
  symbol-name collision, not a runtime consumer). Gate remedy verbatim: "New Vulture debt is not
  authorized by the trusted base. Running --update in this branch cannot authorize it; land a
  reviewed grant first." `load_authorizations` reads grants at the merge base (`339fb9053` carries
  102 vulture grants, none for these identities), so no branch-side edit can authorize them — the
  documented two-merge wall.
- Counterfactual re-proven with the checker's own `_rule_deltas` (no tree edit): pruning the five
  banked rows moves the failure to the banking leg (5 NEW candidate identities, rc=1 either way);
  the as-banked state is the only honest ledger for the issue-mandated enum. Reconciliation status
  unchanged from the round-477-line decision: no identity is eliminable in this leaf (deleting the
  members violates the fixed enum contract; dummy references are forbidden keep-alives, both tried
  and reverted earlier on this branch), the five reviewed retained rows stay, grants stay
  untouched, and greenness is reachable only at the `#1845` integration head (real consumer loads
  the names) or via an owner-landed develop grant.
- Remaining merge-queue reds diagnosed, all downstream of the same structural blocker:
  `check-reachability.py` rc=1 with exactly 1 NEWLY UNREACHABLE `maistro.runs.admission_identity`
  (baseline entry issue-prohibited); `pytest tests/test_check_reachability.py
  tests/test_reachability_baseline_identity.py` reproduces the CI `test` job's 3 failures
  (`test_baseline_matches_the_tree`, `test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `test_the_baseline_is_exactly_the_unreachable_set` — all `Extra items: 'maistro.runs.admission_identity'`);
  the **Coverage gate is a cascade, not an independent regression**: the root `tests/` suite that
  fails those 3 tests is a producer step inside the `coverage-postgres` job
  (`.github/workflows/quality.yml:714`, job defined at :339) and `coverage-gate` has `needs:
  [coverage-unit, coverage-archive, coverage-postgres]` (:500), while the leaf itself cannot trip
  either leg — diff coverage has a 100%-covered file (245/245 measured above) and the floor
  arithmetic cannot fail from one 245-statement addition even at 0% (≈87.7% > the 87% floor);
  "Quality gate (Pillars 1–4, 7, 8)" composes the red quality jobs. `check-reachability-dispositions.py`
  rc=0 (49 groups / 169 modules), `check-promotion-surface.py` rc=0, `mypy` on the module Success.
- Scope invariants hold at this head: branch diff vs base `339fb9053` is exactly the 4 in-scope
  surfaces (+3088/-0: module 520, tests 660, note 1903→1903+this section, `quality/vulture-baseline.json`
  +5/-0); `quality/ratchet-authorizations.json` and `quality/reachability-baseline.json` are 0-line
  diffs; 0 production importers of `admission_identity` outside module+test; no `maistro.runs.__init__`
  export. #1841 anchors intact: `store_boundary.py:56` `require_admitted_actor(actor_principal_id:
  str | None) -> str`; `store.py:550` `get_run(..., *, principal_id: str | None = None)`;
  `store.py:507/576` retain `actor_principal_id: str | None = None`; `model.py:306`.

No code changed in this round: the ledger amendment the lane brief instructs is already exactly in
place (banking proven multiset-exact), nothing genuinely dead is eliminable without violating the
fixed enum contract, and the authorization red is the issue-documented merge blocker that only the
`#1845` integration head (or an owner-landed develop grant) can clear. The integration hold stands;
stack left unmerged; no inventory delta (stays `+79`). (Refs #1851)

## Round-216 CI-repair verification at the exact assigned head `1d78b6fc03c1` (job `b5b63562c8af463c8dd85daef2577390`)

Assigned repair of issue #1851 at the exact head CI evaluated (`1d78b6fc03c1ceae9be8d192789d3e9b17e56699`,
branch `auto-1851`, assigned develop base `e0cca7024ef`); worktree clean at start, prior round's
`result.json` shows `failure_kind: provider_error` (agent timeout) with all five driver checks rc=0,
so no uncommitted work existed to salvage. Every fact below re-derived firsthand this round; no
earlier claim trusted, including the prior round's own note sections.

- Driver 5/5 green at this exact head (check-0..4 logs of this job): `uv sync --locked --extra dev`
  rc=0; `ruff check .` "All checks passed!"; `ruff format --check .` 3327 files already formatted;
  focused pytest **79 passed** in 1.94s; `check-suite-inventory.py --suite packages/maistro-core/tests`
  ok **16542 == recorded**, unique identities 16542, 0 duplicate evidence, 0 byte-identical files.
- Focused acceptance re-executed live with true exit codes: focused pytest **79 passed** rc=0;
  `ruff check` and `ruff format --check` on both leaf files rc=0; `mypy
  packages/maistro-core/src/maistro/runs/admission_identity.py` **Success** rc=0. The enum pin sits
  at `admission_identity.py:515-520` (six lowercase pairs in issue order; line numbers re-read this
  round).
- CI-exact vulture (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`, argv from `.github/workflows/vulture-ratchet.yml:82-83` and
  `quality.yml:1462-1464`) rc=1, two legs decomposed firsthand: **banking GREEN and exact** (1327
  findings vs a 1327-row candidate ledger; `unclassified: 0`; `never_allowlist: 0`) and
  **authorization RED on exactly the five issue-mandated enum identities** `MISMATCH`/`REPLAYED`/
  `TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED` at `admission_identity.py:515-520` (bucket
  `pydantic-declarative-field`, 60% confidence), gate remedy "land a reviewed grant first". Ledger
  re-parsed this round (rules carry findings under `"findings"` lists): candidate ledger **1327**
  rows including exactly the 5 `admission_identity` rows under rule id `pydantic-declarative-field`;
  trusted base `35a72ff54d4f` (merge-base with `origin/develop`) carries **1322** rows and **0**
  admission rows; `quality/ratchet-authorizations.json` at base has **no** `admission_identity`
  grant in any section. `PENDING` is unflagged because the name is used tree-wide by live
  `JobStatus.PENDING` in `maistro-canvas` (`canvas/executor.py:53` et al.) — vulture matches names,
  not definitions; the issue itself calls this out as a favorable symbol-name collision, not a
  runtime consumer.
- CI-exact reachability (`scripts/check-reachability.py`) rc=1 with exactly **1 NEWLY UNREACHABLE**
  `maistro.runs.admission_identity` out of 1412 production modules / 170 unreachable; the baseline
  entry that would silence it is issue-prohibited for this leaf and absent from both branch and base.
  `check-ratchet-provenance.py` (RATCHET_BASE_REV=origin/develop) true rc=1 **solely** via its
  `check-reachability-provenance.py` leg ("trusted-base gate returned 1"); `check-shipped-surface-truth.py`
  rc=0.
- CI `test` job failures reproduced by name at this head: `tests/test_check_reachability.py::
  test_baseline_matches_the_tree`, `tests/test_reachability_baseline_identity.py::
  test_the_committed_baseline_passes_the_gate_it_now_carries`, and `::test_the_baseline_is_exactly_the_unreachable_set`
  (run together with 6 sibling reachability suites: 3 failed / 196 passed; each failure is the same
  `Extra items in the left set: 'maistro.runs.admission_identity'`). Coverage gate is a cascade, not
  an independent regression: quality.yml's `coverage-gate` `needs: [coverage-unit, coverage-archive,
  coverage-postgres]` and the root `tests/` suite runs as a `--source=scripts` producer step
  (quality.yml:713-714), so those 3 failing self-checks red the producer; "Quality gate (Pillars 1–4,
  7, 8)" (quality.yml:2806) needs `quality-vulture` and `quality-reachability` and composes their
  red. All six merge-queue failures therefore reduce to the two structural roots: the unwired-module
  reachability ratchet and the unauthorized five-identity vulture delta.
- Repair space re-proven empty, not assumed: the five identities are the issue's fixed six-pair enum
  contract ("exactly these member/value pairs"), so none is genuinely dead to delete; pruning the
  banked rows only moves the failure to the banking leg (candidate ledger would drop below the
  1327-row scan) while rc stays 1; keep-alive references, suppressions, reachability-baseline
  entries, and branch-side grants are each explicitly prohibited by the issue ("no fake callers …
  suppressions, allowlist/baseline entries, or grants"), and a branch-side grant is inert by
  construction — the provenance run this round resolved its trusted base to `35a72ff54d4f`, proving
  `load_authorizations` reads the base revision, not the candidate (the documented two-merge wall).
- Scope invariants re-proven at this head: `git diff --stat 35a72ff54...HEAD` is exactly the 4
  in-scope surfaces (+3168/-0: note 1983, module 520, tests 660, vulture-baseline +5);
  `git diff --numstat` over `quality/` is exactly `5 0 quality/vulture-baseline.json`;
  `quality/ratchet-authorizations.json` and `quality/reachability-baseline.json` are 0-line diffs;
  grep over `packages/*/src` finds 0 production importers of `admission_identity` outside the module
  itself; `packages/maistro-core/src/maistro/runs/__init__.py` exists and does not reference it.
  #1841 anchors re-read intact: `store_boundary.py:56` `require_admitted_actor(actor_principal_id:
  str | None) -> str`; `store.py:550` `get_run(self, run_id, *, principal_id: str | None = None) ->
  Run | None`; `store.py:507/576` retain `actor_principal_id: str | None = None`; `model.py:306`
  `actor_principal_id: str | None`.
- Base motion re-resolved by plain git (no API): `origin/develop` = `e0cca7024ef` (the assigned
  base), 3 commits ahead of merge-base `35a72ff54d4f`; the 23 files those commits touch have **zero
  overlap** with this branch's 4 files — no develop sync conflict, none warranted.
- Prior dispatch block resolved by this round's own capture: `dispatch-context.json` now contains
  `repos/.../pulls/1936/files` (source index 42), listing exactly the 4 files of the local diff —
  the earlier "Unable to collect required source: pulls/1936/files" block no longer reflects missing
  evidence.
- Reconciliation decision recorded for the issue's open checkbox, without treating it as silent
  approval: the five retained baseline rows stand on the CI-repair lane brief's explicit,
  round-scoped authorization to "amend quality/vulture-baseline.json for reviewed retained
  identities" — a repair-round instruction that conflicts with the issue's ordinary-scope
  no-baseline-additions rule; this note records that conflict rather than resolving it by policy
  change, the rows carry no grant and authorize nothing, and full-gate greenness remains reachable
  only at the `#1845` integration head with the real reviewed consumer (which makes the names used)
  or via an owner-landed develop grant under the two-merge rule.

No code changed in this round (repair space proven empty above); the five deterministic driver
checks, the focused acceptance commands, and every failing CI gate were re-run at the exact head
with true exit codes; integration hold stands; stack left unmerged; no inventory delta (stays
`+79`). (Refs #1851)

## Round-217 CI-repair verification at the develop-merged head `fbdeabd6686b` (job `828f2664d242472ea2cafb77d934d441`)

First structural change since round 216: the branch absorbed `origin/develop` via merge commit
`fbdeabd66` (parents `7a2691975` + `e708451b3`), so every ratchet's trusted base moved
`35a72ff54d4f` -> `e708451b3887` and all counts shifted. Nothing below is carried over from prior
rounds — every verdict re-derived firsthand at this exact head; worktree found clean at the
assigned head.

- Driver battery 5/5 green: `uv sync --locked --extra dev` ok; `ruff check .` / `ruff format --check .`
  clean; focused pytest **79 passed**; `check-suite-inventory.py --suite packages/maistro-core/tests`
  ok (collected 16582 == recorded 16582). Focused acceptance re-run: module-scoped ruff + mypy clean.
- Module contract re-verified live (not from notes): `__all__` exactly the 21 mandated names
  (set-exact; alphabetical order — the issue fixes membership), `AdmissionAssessment` the 6 verbatim
  lowercase pairs in issue order, 17 dataclasses all frozen+slots, frozen write raises
  `FrozenInstanceError`.
- CI-exact vulture (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  **rc=1**. Summary 1326 findings, `unclassified: 0`, `never_allowlist: 0` — banking half GREEN
  (no "Candidate ledger bookkeeping"/"must also be banked"/"must be pruned" output). Authorization
  half RED on exactly 5 NEW identities vs trusted base `e708451b3887` (1321 -> 1326, +5/-0):
  `admission_identity.py:515-520` `MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/
  `LEGACY_UNRESOLVED` (60% confidence; `PENDING` unflagged via the same-name `Pending` class).
  Gate's own remedy: "land a reviewed grant first".
- CI-exact reachability (`check-reachability.py`): **rc=1**, 1413 modules / 169 unreachable, exactly
  1 NEWLY UNREACHABLE: `maistro.runs.admission_identity`. `check-ratchet-provenance.py`: **rc=1**
  solely via the reachability leg (`check-reachability-provenance.py` trusted-base gate returned 1);
  the other 9 legs OK (adr-status-language, citation-status, promotion-surface,
  reachability-dispositions, shell-execution, contract-markers, enumerations, lifecycle, and the
  vulture leg not reached past the failure). `check-shipped-surface-truth.py` rc=0;
  `check-reachability-dispositions.py` rc=0 (48 groups / 168 modules); `check-promotion-surface.py`
  rc=0; full `check-suite-inventory.py` rc=0 (17 suites, 32022 identities).
- ci.yml `test`-gate failures reproduced: `pytest tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py -q` -> exactly **3 failed / 36 passed**, every failure
  `New unreachable modules::maistro.runs.admission_identity`. Coverage-gate cascade confirmed at
  `quality.yml:713`: the aggregate job's producer runs `coverage run --append --branch
  --source=scripts -m pytest tests/ ...`, so those same 3 failures abort it before `coverage xml`.
- Instructed ledger amendment (this round's lane brief: "amend quality/vulture-baseline.json for
  reviewed retained identities (remove identities your fix eliminated)") assessed and executed as a
  deliberate **no-op**: the candidate ledger already banks the 5 reviewed retained identities
  multiset-exact (`quality/vulture-baseline.json:283-287`, rule `pydantic-declarative-field`,
  numstat vs merge base exactly `5 0`); no fix this round eliminated any identity (no code changed);
  pruning the rows regresses the banking half to red; a branch-side grant is inert by construction
  (`load_authorizations(RATCHET, base=trusted_ref.base_sha)` reads the merge base) and prohibited by
  the issue. Ledger left in its correct reviewed state.
- Scope invariants at this head: `git diff --stat e708451b3..HEAD` is exactly the 4 in-scope
  surfaces, +3256/-0 (note, module 520, tests 660, vulture-baseline +5); `git diff --numstat` over
  `quality/` is exactly `5 0 quality/vulture-baseline.json`; `quality/ratchet-authorizations.json`
  and `quality/reachability-baseline.json` are 0-line diffs; 0 production importers of
  `admission_identity` in `packages/*/src` outside the module; `runs/__init__.py` has no admission
  reference; #1841 anchors intact (`store_boundary.py:56`, `store.py:507/576/907`,
  `model.py:306`).
- Base motion re-resolved by plain git: `origin/develop` = `5f714e1beed5` (the assigned develop
  base), 2 commits (`82da18240`, `5f714e1be`) past merge-base `e708451b3`; 53 files, zero overlap
  with `quality/` or `maistro-core/src/maistro/runs/` — no develop sync conflict, none warranted;
  and `origin/develop`'s ledgers carry 0 admission rows / 0 admission grants, so the CI
  evaluation at the develop tip resolves the same authorization verdict as this local run.
- Reconciliation for the issue's open checkbox, reaffirmed under THIS round's lane brief: the five
  retained rows stand on the round-scoped CI-repair authorization ("Ledger amendment is permitted
  and required in CI-repair rounds") — a repair-lane instruction that still conflicts with the
  issue's ordinary-scope no-baseline-additions rule; recorded, not silently resolved; rows carry no
  grant and authorize nothing; the integration hold and the two named remedies (real #1845
  consumer, or owner-landed develop grant under the two-merge rule) are unchanged.

No code or ledger change warranted this round (repair space re-proven empty at the new topology);
all six merge-queue failures decompose to the same two structural facts the issue itself mandates
and documents for an intentionally unwired leaf; integration hold stands; stack left unmerged; no
inventory delta (stays `+79`). (Refs #1851)

## Round-218 CI-repair verification at the assigned head `486bb9d35f9b` (job `322ccd42f80b4bc39a19c3bc320ed78e`)

Develop moved again but nothing structural changed: this round's assigned develop base is
`53db178509f8` (`origin/develop` tip, 2 commits `cf48bbd88` + `53db17850` past merge-base
`e708451b3887`), and `git diff e708451b3..53db17850 -- quality/` is **empty** — zero grants, zero
baseline motion, zero admission references anywhere in `quality/` at the tip (`git grep -c
admission_identity 53db17850 -- quality/` -> no matches). The touched files (extensions gallery,
durable-runs executor, ci.yml) have zero overlap with this branch's 4 surfaces, so no develop sync
conflict is warranted, and the merge queue's evaluation at `53db17850` resolves the same trusted
base `e708451b3887` my local gates resolved — every verdict below is firsthand at the exact
assigned head; worktree found clean.

- Driver battery 5/5 green (job logs check-0..4): `uv sync --locked --extra dev` ok; `ruff check .`
  all passed; `ruff format --check .` 3330 files formatted; focused pytest **79 passed**;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok (16582 == recorded).
- Module contract re-verified live: `__all__` 21 names; `AdmissionAssessment` the 6 verbatim
  lowercase pairs in issue order; 17 dataclasses frozen+slots; ticket repr omits `owner_token`;
  mypy on the module Success.
- CI-exact vulture: **rc=1**, 1326 findings, `unclassified: 0`, `never_allowlist: 0` (banking leg
  GREEN — no bookkeeping output), authorization leg RED on exactly the 5 issue-mandated enum
  identities `admission_identity.py:515/516/518/519/520` (`MISMATCH`/`REPLAYED`/`TAKEOVER`/
  `REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`; `PENDING` unflagged via the same-name `Pending` collision),
  +5/-0 vs trusted base `e708451b3887` (1321 -> 1326); gate remedy "land a reviewed grant first".
- `check-reachability.py`: **rc=1**, 1413 modules / 169 unreachable, exactly 1 NEWLY UNREACHABLE
  `maistro.runs.admission_identity`. `check-ratchet-provenance.py`: **rc=1** solely via the
  reachability-provenance leg ("trusted-base gate returned 1"); lifecycle leg OK. ci.yml test-job
  failure reproduced: the 3 reachability tests -> **3 failed / 36 passed**, every failure
  `New unreachable modules::maistro.runs.admission_identity`; the Coverage gate remains the
  documented quality.yml:713 cascade of those same failures. `check-reachability-dispositions.py`
  rc=0, `check-promotion-surface.py` rc=0, `check-shipped-surface-truth.py` rc=0.
- Instructed ledger amendment re-assessed, again a deliberate **no-op**: the 5 reviewed retained
  identities are already banked multiset-exact under `pydantic-declarative-field`
  (`quality/vulture-baseline.json:283-287`; numstat vs merge base exactly `5 0`); no fix this round
  eliminated any identity (no code changed); they are the issue's fixed enum contract, not dead
  code; pruning them flips the banking leg red (1326-scan vs 1321-ledger -> 5 unclassified); a
  branch-side grant is inert by construction (`load_authorizations` reads the merge base) and
  issue-prohibited. Ledger left in its correct reviewed state.
- Scope invariants: `git diff e708451b3..HEAD` is exactly the 4 in-scope surfaces (+520 module,
  +660 tests, +5 ledger, note), 0-line diffs in `ratchet-authorizations.json` /
  `reachability-baseline.json`; 0 production importers; no `runs/__init__.py` export; #1841 anchors
  intact (`store_boundary.py:56`, `store.py:507/576/907`, `model.py:306`).
- Reconciliation for the issue's open checkbox, reaffirmed under this round's lane authority ("in an
  explicit CI-repair round ... amend quality/vulture-baseline.json exactly as instructed"): the five
  retained rows stand on that round-scoped authorization for reviewed retained identities, in
  recorded conflict with the issue's ordinary-scope no-baseline-additions rule — recorded, not
  silently resolved; the rows carry no grant and authorize nothing; the two named remedies (the
  #1845 real reviewed consumer at an integration head, or an owner-landed develop grant under the
  two-merge rule) remain outside this leaf.

No code or ledger change warranted (repair space re-proven empty at this topology); all six
merge-queue failures decompose to the same two structural facts the issue itself mandates and
documents for an intentionally unwired leaf; integration hold stands; stack left unmerged; no
inventory delta (stays `+79`). (Refs #1851)

## Round-219 CI-repair verification at the assigned head `b7ba7061316f` (job `40d81eddc9364610944a28dd471680c6`)

Assigned head is the round-218 commit itself; assigned develop base advanced `53db178509f8` ->
`64ea662cb015` (1 new commit, the Design DB-URL normalization; 5 commits total past merge-base
`e708451b3887`). `git diff e708451b3..64ea662cb -- quality/` is again **empty**, the full develop
delta contains 0 `admission_identity` references, and its touched files (extensions gallery, design
engine, ci.yml, inventory docs) have zero overlap with this branch's 4 surfaces — no develop sync
conflict; whether the merge queue resolves its trusted base at `e708451b3` (branch-local) or at
`64ea662cb` (synthetic merge), the quality/ state it reads is identical, so every verdict below
holds under both resolutions. The prior round's NEEDS-DEEP-REVIEW block was re-assessed against
this round's lane authority and remains: the two structural reds are outside this leaf's repair
authority by the issue's own text.

- Driver battery 5/5 green (job logs check-0..4): `uv sync --locked --extra dev` ok; `ruff check .`
  all passed; `ruff format --check .` 3330 files formatted; focused pytest **79 passed**;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok (16582 == recorded).
- Module contract re-verified by a fresh live probe this round: `__all__` exactly the 21 names
  (set-exact); `AdmissionAssessment` the 6 verbatim lowercase pairs in issue order at
  `admission_identity.py:515-520`; 17 dataclasses frozen+slots; ticket repr omits `owner_token`;
  `owns()` conjunction live-checked (scope / generation / owner each individually required); mypy
  on the module Success.
- CI-exact vulture: **rc=1**, 1326 findings, `unclassified: 0`, `never_allowlist: 0` (banking leg
  GREEN — no bookkeeping output), authorization leg RED on exactly the 5 issue-mandated enum
  identities `admission_identity.py:515/516/518/519/520` (`MISMATCH`/`REPLAYED`/`TAKEOVER`/
  `REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`; `PENDING` unflagged via the same-name `Pending` collision),
  +5/-0 vs trusted base `e708451b3887` (1321 -> 1326); gate remedy "land a reviewed grant first".
- `check-reachability.py`: **rc=1**, 1413 modules / 169 unreachable, exactly 1 NEWLY UNREACHABLE
  `maistro.runs.admission_identity`. `check-ratchet-provenance.py`: **rc=1** solely via the
  reachability-provenance leg ("trusted-base gate returned 1"); enumerations/lifecycle legs OK.
  ci.yml test-job failure reproduced firsthand: `tests/test_check_reachability.py` +
  `tests/test_reachability_baseline_identity.py` -> **3 failed / 36 passed**, every failure the
  extra baseline item `maistro.runs.admission_identity`; the Coverage gate remains the documented
  quality.yml:713 cascade of those same failures. `check-reachability-dispositions.py` rc=0,
  `check-promotion-surface.py` rc=0, `check-shipped-surface-truth.py` rc=0.
- Instructed ledger amendment re-assessed under this round's explicit CI-repair authorization,
  again a deliberate **no-op**: the 5 reviewed retained identities are already banked
  multiset-exact under `pydantic-declarative-field` (`quality/vulture-baseline.json:283-287`;
  numstat vs merge base exactly `5 0`); no fix this round eliminated any identity (no code
  changed); they are the issue's fixed enum contract, not dead code; pruning them flips the
  banking leg red (1326-scan vs 1321-ledger -> 5 unclassified); a branch-side grant is inert by
  construction (`load_authorizations` reads the trusted base) and issue-prohibited. Ledger left in
  its correct reviewed state.
- Scope invariants: `git diff e708451b3..HEAD` is exactly the 4 in-scope surfaces (+520 module,
  +660 tests, +5 ledger, note), 0-line diffs in `ratchet-authorizations.json` /
  `reachability-baseline.json`; 0 production importers; no `runs/__init__.py` export; #1841 anchors
  intact (`store_boundary.py:56`, `store.py:507/576/907`, `model.py:306`).
- Reconciliation for the issue's open checkbox, reaffirmed: the five retained rows stand on the
  CI-repair rounds' explicit lane authorization for reviewed retained identities, in recorded
  conflict with the issue's ordinary-scope no-baseline-additions rule — recorded, not silently
  resolved; the rows carry no grant and authorize nothing; the two named remedies (the #1845 real
  reviewed consumer at an integration head, or an owner-landed develop grant under the two-merge
  rule) remain outside this leaf. Both named remedies require owner action.

No code or ledger change warranted (repair space re-proven empty at this topology for the third
consecutive round); all six merge-queue failures decompose to the same two structural facts the
issue itself mandates and documents for an intentionally unwired leaf; integration hold stands;
stack left unmerged; no inventory delta (stays `+79`). (Refs #1851)

## Deep-review round — 2026-10-19 (`7606baab2c41`, job `b01a985872394488b340a672da85ff91`)

Bounded second-round adversarial verification at the exact assigned head `7606baab2c41`
(branch tip = merge of develop `851a63e7ccd1` into `auto-1851`); worktree found clean at
start. Every prior finding re-derived firsthand; nothing carried over. One NEW in-leaf
repairable defect was found and fixed this round (the malformed grant file); the five
carried findings are CONFIRMED, not refuted.

**All five prior findings confirmed at this head:**

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  with `RATCHET_BASE_REV=origin/develop` (merge-base resolves to `851a63e7ccd1`): **rc=1**,
  banking leg GREEN (1326 findings, `unclassified: 0`, `never_allowlist: 0`), authorization
  leg RED on exactly the 5 retained identities `admission_identity.py:515/516/518/519/520`
  (`MISMATCH`/`REPLAYED`/`TAKEOVER`/`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`; `PENDING` at :517
  unflagged via the same-name `Pending` class), remedy "land a reviewed grant first" —
  observed at a head that ALREADY CONTAINED the branch-side grant commit `4893be451`,
  which is the empirical half of the inertness proof.
- Grant inertness, source half: `ratchet_provenance.load_authorizations` reads grants via
  `resolve_baseline` at `git merge-base(RATCHET_BASE_REV, HEAD)` = `851a63e7ccd1` (verified:
  `git merge-base origin/develop HEAD` = `851a63e7ccd1`); the base file contains **0**
  `admission_identity` grants. Two-merge wall confirmed; a branch-side grant cannot authorize
  its own introduction.
- `check-reachability.py`: **rc=1**, exactly 1 NEWLY UNREACHABLE: `maistro.runs.admission_identity`.
  `check-reachability-provenance.py`: **rc=1** (168 -> 169 unreachable; "absent from trusted base
  and not previously authorized" + "missing from candidate baseline" — two-sided, as the
  no-bank design mandates). `check-ratchet-provenance.py`: **rc=1** solely via that leg;
  `check-shipped-surface-truth.py` rc=0. The 3 ci.yml reachability tests reproduced failing
  (3 failed), each naming `maistro.runs.admission_identity`.
- Issue #1851's reconciliation checkbox remains open and owner-held; this note records the
  conflict, it does not settle it.

**NEW defect found and repaired this round — commit `4893be451` was malformed, not merely inert:**

- `git show 4893be451` inserted the 25-line grant block directly after the closing `}` of the
  previous entry **without the required comma**: `quality/ratchet-authorizations.json` line 583
  ends `    }` and line 584 begins the `MISMATCH` grant key. The file failed `json.load` at
  line 584 column 5 — the ONLY malformed ledger in the entire `quality/` tree (all 40 others
  parse). The base `851a63e7ccd1` version is valid.
- Blast radius proven live: `check_ac_state_impl.candidate_grants()` (scripts/check_ac_state_impl.py:1663-1670)
  parses the WORKTREE copy ("does the file in front of me still say so") and converts the
  `JSONDecodeError` into a gate refusal. `uv run python scripts/check-ac-state.py --run-tests
  --ratchet` rc=1 with "the 'ac-state' section in the working tree could not be read
  (JSONDecodeError: Expecting ',' delimiter: line 584 column 5)" — i.e. commit `4893be451`,
  aimed at `exact-debt-ledger`, broke the `quality-acceptance` job instead (its targeted gate
  is provably blind to the file: grants load from the base).
- Repair (this round's writer action, evidence-backed, not cosmetic): removed exactly the
  25 inserted lines (584-608), restoring the file **byte-exact to base `851a63e7ccd1`**
  (verified: `diff` vs `git show 851a63e7c:quality/ratchet-authorizations.json` empty; file
  valid JSON). The grants were (a) inert by the two-merge rule, (b) prohibited by the issue's
  unconditional "No fake callers, baseline additions, grants, disabled gates or quality waivers
  are permitted", and (c) malformed. `4893be451` remains in history; this is a forward fix.

**Post-repair state, all re-run at this tree:**

- `check-ac-state.py --run-tests --ratchet`: no longer crashes; rc=1 on a REAL, INHERITED
  measurement — `design_coverage: 39.5205 falls below the floor of 39.641`. Attribution proven:
  `quality/ac-state.json` (regenerated) contains **0** references to `admission_identity`/1851;
  the new test file carries 0 `mark.ac` markers; the branch's only docs delta is this note;
  adding an unreachable module changes no other module's reachability. The measurement is
  therefore identical at base and HEAD — a develop-corpus property. The base's own
  `ac-state` grant (`design_coverage@39.641`, owner-authorized 2026-10-17, #166) documents the
  re-anchor mechanism and names #1936 among the previously red candidates; the further fall to
  39.5205 postdates that grant and needs the same owner action from the current develop.
  Not branch-caused, not in-leaf-fixable.
- `check-vulture-baseline.py` CI-exact: rc=1 with a **byte-identical** failure set pre/post
  grant removal — the grants changed nothing for the gate they targeted (inertness, both halves).
- `check-ratchet-provenance.py` rc=1 unchanged (reachability leg); `ruff check .` all passed;
  focused pytest **79 passed**; `__all__` 21 set-exact, 6 verbatim lowercase enum pairs at
  515-520, `owner_token` repr=False re-probed live; 0 production importers; no
  `runs/__init__` export.

**Deep-review verdict rationale:** the five carried findings hold; the only in-leaf-repairable
defect (the malformed inert grant) is fixed. What remains red decomposes to the same two
structural facts every prior round recorded — the intentionally unwired leaf (reachability
family + vulture authorization two-merge wall) and the inherited develop-side design-coverage
floor — whose remedies (#1845 real-consumer integration, owner-landed develop grants /
re-anchor) are outside this leaf by the issue's own staging language. Integration hold stands;
stack left unmerged; no inventory delta (stays `+79`). (Refs #1851)

## Deep-review round 1 verification at the develop-merged head `8c33f53d4241` (job `b08e0e54e32a4ef9a12bf1784b1e8045`)

Independent verifier re-execution at the exact assigned head `8c33f53d4241eabbcf7d8566528cedf65abab713`
(= `7d3b6ff44` plus the `fe4332d8eb12` develop sync; worktree clean). Read-only except this note.

**Scope re-diff at the new base.** `git diff --name-only fe4332d8..HEAD` = exactly the three
issue-designated files plus `quality/vulture-baseline.json` (+5 rows, lines 283-287). The grant
removal in `7d3b6ff44` left `quality/ratchet-authorizations.json` byte-identical to base
(absent from the diff). Merge base re-anchored: `git merge-base origin/develop HEAD` =
`fe4332d8eb12`; the base `vulture-baseline.json` contains **0** `admission_identity` rows and the
base `ratchet-authorizations.json` contains **0** `admission_identity` grants, so the two-merge
wall statement survives the re-anchor unchanged.

**Carried findings adversarially re-tested at `8c33f53d4241` — none refuted:**

- `check-vulture-baseline.py` CI-exact (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  `RATCHET_BASE_REV=origin/develop`): **rc=1**, same 5 identities at `admission_identity.py:515-520`,
  now bucket `pydantic-declarative-field`; "1321 reviewed identities -> 1326 findings" proves the
  candidate ledger *banks* all five while the *trusted-base* ledger (1321) lacks them and no grant
  authorizes them — banking is not authorizing, both halves confirmed.
- `check-ratchet-provenance.py`: **rc=1**, solely the reachability leg
  ("`maistro.runs.admission_identity`: NEW unreachable module absent from trusted base and not
  previously authorized" + "missing from candidate baseline"); all other legs OK.
- `check-reachability.py` (bare, CI-exact): **rc=1**, exactly 1 NEWLY UNREACHABLE.
- `check-shipped-surface-truth.py`: rc=0.
- The 3 reachability tests reproduced failing (3 failed):
  `test_check_reachability.py::test_baseline_matches_the_tree`,
  `test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`.
  pytest diff shows exactly one net-new unreachable module (insertion at index 125, last-item
  shift artifact only).

**Focused contract evidence re-proven at this head:** focused pytest **79 passed**; mypy clean;
`__all__` 21 names set-exact (AST-parsed); `AdmissionAssessment` exactly the 6 lowercase pairs in
required order, asserted verbatim by the contract test (test file lines 153-158); all 12 issue-named
tests present; all dataclasses `frozen=True, slots=True`; live probes: duplicate-key / non-finite /
non-object-root / non-string `CanonicalJsonObject` construction all raise `ValueError`, canonical
normalization `{"b": 1, "a": "ü"}` -> `{"a":"ü","b":1}` with single `text` field and frozen
instance, `owns()` exactly the scope∧generation∧owner conjunction (each single-leg divergence
returns False, roles never compared to each other), `admitted is (binding is not None)`, repr omits
the `owner_token` field while the printable `generation_id` remains, 0 production importers, no
`runs/__init__` export, no closure keywords toward #1851 in branch commits or the PR #1936 body.

**Deep-review conclusion (round 1).** The five carried findings hold at the new head; the grants-leg
finding is resolved by removal (file byte-identical to base — nothing left to be inert). Exactly one
in-leaf-repairable defect remains, unchanged from every prior round: the five retained
`quality/vulture-baseline.json:283-287` rows are (a) prohibited by the issue's unconditional
"no baseline additions ... are permitted", (b) unauthorized by the trusted base `fe4332d8eb12`
under the two-merge rule, and (c) the branch's only out-of-scope file change; the issue's
reconciliation checkbox stays owner-held and open. Every other red gate decomposes to the
issue-documented unwired-leaf state (`check-reachability` family + the vulture authorization leg
that exists only because the rows force a ledger-vs-base delta on top of it): by the issue's own
staging model `exact-debt-ledger` cannot pass at this leaf, and is the documented merge blocker,
not an in-leaf-fixable defect. Remedies remain #1845 real-consumer integration plus an owner-held
reconciliation decision (remove the rows, or land a reviewed develop-side grant first — the issue
text currently authorizes neither silently). Integration hold stands; stack left unmerged; no
inventory delta (stays `+79`). (Refs #1851)
