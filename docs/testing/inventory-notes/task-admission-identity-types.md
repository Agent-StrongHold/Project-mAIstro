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