# #1893 repair handoff — 4e5c0025

## Frozen scope and disposition

Writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Verified clean starting HEAD: `d680d35a0f2953cb852b4348b0126b471c6c5548`.
Verified supplied integration base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Only issue #1893 was processed. Evidence was the supplied job snapshot
`/home/dev/maistro/jobs/4e5c002535924be8999dd2713224aa93/dispatch-context.json`,
check-0.log through check-4.log, and prior result 42f6e260. Prior results are
historical, not measurements from this execution. No remote operation, refetch,
merge, GitHub mutation, or work discard occurred; no sync conflict was present.

**BLOCKED.** The exact Vulture scan passes with no unbanked identities. The
mandatory trusted-base provenance gate independently fails for the same two
unreachable modules/dispositions. The Vulture-only ledger exception does not
permit changing reachability policy. No evidence justifies a speculative source
or test change. This report is the sole changed file and is committed as a
blocked handoff, not a repair completion or integration approval.

## Architecture and production boundary

Read repository AGENTS.md, docs/README.md, codec/identity implementation and
adjacent tests, and accepted ADRs:

- ADR-081226-69ee: preserve Goal -> Graph -> Run -> NodeRun -> Attempt ownership.
- ADR-082526-7f02: admission provenance is immutable; execution identity belongs
  to the Attempt, not a rewritten admission history.
- ADR-083026-aba1: an absent production caller must be stated explicitly.
- ADR-083126-5e62: candidate quality bookkeeping cannot approve its own debt.

`git grep -n -E 'admission_codec|admission_identity' -- 'packages/*/src/*.py'`
found only the codec's identity import/docstring and the Vulture whitelist
import. The provenance scanner independently finds both modules unreachable.
`admission_codec.py:50-54` explicitly describes the absent consumer. The issue
forbids activating C in B2: adding fake imports, a new execution/authorization
path, or a candidate grant is not a valid reconciliation. Staged type correctness
is not reachable production admission behavior.

The physical `request` TEXT column maps to DTO `request_snapshot`; the encoder
uses named fields. A legacy bound pair without explicit receipt evidence is
partial rather than inventing the receipt required by AdmissionBinding. No new
legacy-response, expiry, deletion, authorization, or rollout policy was selected.

## Executed validation at starting HEAD

All additional command logs below are in the supplied job directory, prefixed
`worker-`. Commands used long timeouts (1800 seconds).

| Command | Actual result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1322 reviewed identities/findings, zero unclassified (`worker-vulture.log`). No ledger amendment warranted. |
| `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` | Exit 1 (`worker-provenance.log`): 169 -> 171 unreachable modules and dispositions; `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` lack trusted-base authorization. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q` | Exit 0; 349 nodes: **346 passed, 3 skipped** in 2.88s (`worker-focused.log`). Skips are the real-PG codec cases, not durability proof. |
| `uv run ruff check .` | Exit 0 (`worker-ruff.log`). |
| `uv run ruff format --check .` | Exit 0 (`worker-format.log`). |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0; two files (`worker-mypy.log`). |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0; 16567 unique collected identities; no duplicate evidence (`worker-inventory.log`). |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 (`worker-surface.log`). |

The supplied driver logs also pass dependency sync, Ruff, formatting, the same
focused tests (346/3), and inventory (16567). They contain no failing pytest
node. Snapshot check-runs for PR #1945 are qualified by head
`973772507c94428dba24fad7d9530490688d59e2`, not this starting HEAD, and include
coverage/exact-debt-ledger failures with null summary/text. The snapshot's
`test` failure on #1855 is qualified by another head,
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`. No current failing pytest traceback
was established. After two bounded inspections, generic `test: failure` remains
**UNRESOLVED**, not proof of a codec defect. Obtain the actual failing test log
before further test repairs; do not repeatedly edit unrelated tests.

## Acceptance audit

| #1893 requirement | Evidence / remaining boundary |
| --- | --- |
| Exact public interfaces, frozen/slotted header and six typed error codes | Source review plus focused rejection/DTO tests pass. Header takes no clock or incoming fingerprint. |
| Header scalar agreement, strict storage UUID `.hex`, signed timestamps, unknown formats fail closed | Focused mismatch, UUID, scalar and unknown-format tests pass. |
| Validated-hash-only scope and safe diagnostics | Focused invalid JSON, UUID, nesting, numeric and Unicode tests pass; unsafe parser chains are suppressed. |
| Canonical JSON object snapshots reject duplicates/nonobjects/bare nonfinite values | Focused codec and CanonicalJsonObject tests pass, including nested duplicate-key cases. |
| Snapshot/tag/context preservation and no fingerprint recomputation | `test_v2_round_trip_preserves_all_snapshot_bytes` and `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` pass. Tests use synthetic pre-tagged snapshots. Actual model_of/model_of_json materialization and production fingerprint-before-tagging are **UNVERIFIED**. |
| Owner token hex only at storage | `test_owner_token_is_hex_at_storage_only` and identity repr tests pass. |
| Legacy bound/unbound/partial/receipt-only distinctions without inferred identity | Named legacy distinction tests and bound-pair-without-receipt rejection pass. |
| Header retains expiry/fingerprint despite full-decode failure | All three named header-separation/expired-legacy tests pass. Inclusive expiry replacement/409 precedence is C/F2 behavior, not B2 evidence. |
| Fresh flat named SQL mapping; binding emits task_id and run_id together | Existing independent assertions at test_admission_codec.py:134-137 and encode tests pass. No pre-fix or mutation run performed this round; earlier mutation claims not adopted. |
| Raw/production pool contrast on the same disposable migrated DB | **UNVERIFIED this round**: three tests skipped. No DB was created or migrated; no backend session identities or final SQL row counts are claimed. |
| Explicit authorized principals, Workspace/Project, registered Graph and object-valued Run JSONB | **UNVERIFIED**: synthetic fixtures are not authorized admission or canonical Run persistence evidence. |
| No SQL/HTTP/queue/assessment/scope/decision changes or new execution authority | Reviewed codec remains mapping-only and inactive; no source changes this round. |
| Truthful inventory, focused tests, Ruff/format/mypy | Independently pass above. No tests added/removed; inventory delta zero, no new inventory note required. |
| Unchanged integration gates, no gate/baseline/grant workaround | Vulture and shipped-surface pass; trusted-base reachability/disposition provenance **FAILS**. Full integration CI, promotion validation, external coordination release and rollout authorization remain **UNVERIFIED**. No quality files changed. |

## Required next action

Actual blocker: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`, inherited at starting HEAD.
The CI job `.github/workflows/vulture-ratchet.yml:30,77` requires the provenance
gate that rejects these entries. The campaign owner must arrange separately
reviewed protected-base authorization or coordinated genuine runtime integration
before this leaf can be independently mergeable. Neither is authorized in this
writer round. No automatic issue closure or activation follows from type tests.

Progress: **checked 1, done 0, skipped 0, errors 1** (provenance blocker).
Next: resolve governance/coordination externally and supply the exact failing CI
test log; do not redispatch the unchanged blocked head as a generic codec repair.
