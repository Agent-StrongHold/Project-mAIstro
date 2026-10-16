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
- **`RootAdmissionEnvelope`**: Immutable root admission decision snapshot with 18+ fields (IDs, timestamps, canonical snapshots of request/receipt/provenance)
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