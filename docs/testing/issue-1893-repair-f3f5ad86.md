# #1893 bounded repair handoff at f3f5ad86

## Frozen scope

Only issue #1893, branch `auto-1893`, assigned worktree
`/home/dev/Git/wt/auto-1893`. Verified starting source SHA:
`f3f5ad860cd8419fdfc9b65362e2c228e75c8f6d`; verified supplied trusted base:
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Initial tree clean.
This round changes only this evidence note; no source, tests, inventory counts,
whitelists, ledgers, grants, gates, or runtime activation changed.

Read repository instructions, codec/identity implementations and adjacent tests,
and accepted ADR-081226-a66b (canonical lifecycle), ADR-082526-7f02 (immutable
admission provenance), ADR-083126-5e62 (trusted-base quality authority).
Constructing a DTO is not admission authority. The representation-only scope
preserves `Goal -> Graph -> Run -> NodeRun -> Attempt`; a fake caller or a new
runtime integration solely to clear reachability would violate this stage.

## Executed validation

Logs are in job `/home/dev/maistro/jobs/92ca255755a74c16bd8bfd5f6592c074/`.
Commands below used 1200-second timeouts against the starting source SHA.

| Command | Actual result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1323 reviewed identities, zero unclassified; `worker-vulture.log` |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | **Exit 1**; two unauthorized unreachable modules and two unauthorized dispositions; `worker-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: **201 passed, 3 skipped**; `worker-focused.log` |
| `uv run ruff check .` | Exit 0; `worker-ruff.log` |
| `uv run ruff format --check .` | Exit 0; 3277 files formatted; `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0; two files; `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0; 16466 nodes, zero copied-file duplicate evidence; `worker-inventory.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0; `worker-shipped.log` |

Inspected driver `check-0.log` through `check-4.log`: dependency sync, lint,
format, focused tests and inventory succeeded (driver tests also skipped three
PG cases). These are not adopted as database durability evidence.

## Failure attribution and repair boundary

The provenance failure names `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec`. Candidate entries at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` have no already-landed
reachability authorization in the supplied base. This gate is required by
`.github/workflows/vulture-ratchet.yml:77-85`. Vulture has no unbanked identities,
so its explicit ledger-repair exception supplies no applicable repair.
The existing reachability rows are preserved, not removed or self-authorized.

A source search for `admission_codec|admission_identity` in `packages/*/src`
found only the codec-to-DTO import and a Vulture whitelist import, not a
production caller. Passing DTO tests cannot establish reachable admission.

The dispatch reports `test: failure` without a current-head failing node.
Inspection of captured check-run objects found the sole failed `test` on
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (linked #1855), with null output
text/summary; captured #1945 head `9922f395daa39249991f18210a6d4da68a3a76cb`
has `test: success`. Neither establishes this assigned head's CI result.
Extraction: `worker-captured-test-checks.json`. Attribution is **UNRESOLVED**;
no speculative test edit is justified. `.github/workflows/ci.yml:496-612`
shows that the CI `test` job is broader than these core tests and delegates
core to the coverage producer. This round did not reproduce the full job.

## Acceptance audit

| Criterion | Evidence and limits |
| --- | --- |
| Required signatures, frozen/slotted scalar header, six decode codes | Source inspected; unsupported-format/schema, scalar mismatch and invalid-header tests passed. |
| Exact v2 DTO and fresh flat named SQL parameters | Three round-trip states and fresh-mapping test passed; independent assertions require both binding columns and `task_id == receipt_id`. |
| Storage-only UUID hex, signed timestamps, #1851 constructors | Owner/generation validation, DTO immutability and invalid timestamp tests passed. |
| Legacy bound/unbound/partial distinctions, receipt-only and announced-without-Run | Legacy pair/receipt/whitespace tests passed; missing receipt stays partial, no identity invented. |
| Header/full-decode separation | Expiry and fingerprint preservation tests passed despite malformed snapshot or partial binding; no clock or incoming fingerprint accepted. |
| Strict TEXT/object JSON, duplicates, bare nonfinite and corrupt original evidence | Invalid/duplicate JSON, numeric-loss, nested corruption and invalid Unicode tests passed; predecoded objects rejected. |
| Safe errors and validated scope only | Redaction, suppressed-chain and invalid-scope assertions passed. |
| Tagged nonfinite/context evidence, stored fingerprint unchanged | Tagged and Unicode/exact-number representation tests passed. Production `encode_evidence`, `model_of`/`model_of_json`, original-model fingerprinting, and Run JSONB object insertion remain **UNVERIFIED** by these fixtures. |
| Raw and production pools, real migrated disposable DB, non-None pool | **UNVERIFIED**: all three database cases skipped for missing DSNs. No fresh migration, session identities, SQL row counts or durability proof claimed. |
| Real principals, authorized Workspace/Project, registered Graph kinds | **UNVERIFIED**: fixture identifiers are representation evidence, not authorized admission. |
| No mutation/HTTP/queue/assessor/scope-policy/decision changes | Source inspection confirms codec-only operations; this round changes documentation only. |
| Expired replacement and mismatch/409 precedence | **UNVERIFIED**, intentionally future consumer C/F2 evidence, not a B2 decision. |
| Focused tests, lint, format, types, inventory and full integration CI | Focused checks passed as above; full unchanged CI **UNVERIFIED**, required provenance gate **FAILED**. No new tests or inventory delta this round. |
| Coordinated ownership and activation | Assigned repair worktree only; broader stack ownership/activation remains **UNVERIFIED/BLOCKED**. |

## Required next action

Blocked handoff, not integration approval. An owner must coordinate an
independently landed reachability authorization under the two-merge rule (or
separately authorize the actual consumer integration). Supply the failing
current-head CI job traceback before another test-repair dispatch. Repeating
unchanged-source validation cannot resolve either missing input.
No new regression/mutation proof is claimed because no code/test repair was made.

Progress: checked 1 item; repaired 0; skipped 0; errors 1 reproduced gate blocker.
No GitHub mutation, fetch, merge, or destructive Git operation performed.
