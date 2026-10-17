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
