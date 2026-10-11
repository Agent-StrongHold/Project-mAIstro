# Issue #1893 repair checkpoint — 61c1d1e4

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `a2345d45454277c0e444903dc55559cb7c574491`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Existing worktree was clean; no incoming edits to salvage.
- Inspect the existing admission codec/identity types and their two test files,
  relevant ADRs, existing CI definitions, supplied dispatch and driver logs.
- Only planned edit is this validation report unless reproduced evidence warrants
  a scoped code repair (with an inventory note for any added tests).
- No activation, alternate authority, GitHub mutation, reachability grant/ledger
  edit, or develop sync is assumed authorized. The dispatch's vulture-ledger
  exception is applicable only if the named gate reports actual retained debt.

## Initial evidence

Driver `check-0.log` reports dependency sync success; `check-1.log` reports ruff
success; `check-2.log` reports 3277 formatted files; `check-3.log` reports 201
passed and 3 skipped; `check-4.log` reports inventory 16466 and no duplicates.
These are supplied results, not fresh execution by this worker. In particular,
skipped PostgreSQL tests do not prove durability.

Ambiguity: dispatch names a generic `test: failure` without a failing test or
traceback and repeats an earlier reachability-provenance blocker. Proceed by
running the named gates and focused acceptance tests; do not guess a repair.

## Results

Fresh exact Vulture gate passed (1323 reviewed identities, zero unclassified).
Fresh `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`
failed (exit 1): both admission modules are new unreachable modules and new
dispositions absent from trusted-base authorization. Logs:
`/tmp/1893-61c1-vulture.log`, `/tmp/1893-61c1-provenance.log`.
The resolved `origin/develop` equals the dispatch base. There is no reported
merge conflict. Source import search confirms no production consumer; a
whitelist import is not runtime reachability. This is not Vulture debt and the
Vulture-only ledger exception cannot fix it. No policy/ledger edits warranted.

Fresh focused validation passed: 201 passed, 3 PostgreSQL cases skipped because
MAISTRO_TEST_PG_DSN / MAISTRO_TEST_DATABASE_URL were not configured. All 204
cases collected. Ruff check and format passed (3277 files); targeted mypy
passed (2 source files); suite inventory passed (16466 nodes, no duplicates).
No database was touched. Prior live-PG results are not reasserted as fresh proof.

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (Attempt
lease ownership), and ADR-082226-5104 (PostgreSQL authority). Reconciliation:
admission DTO comparisons are not execution authority or permission; staged
codec validation does not prove production behavior. No alternate authority
or runtime activation is introduced.

Candidate shipped-surface, reachability (1396 modules / 171 unreachable),
dispositions (50 groups), and promotion (74 tolerated modules) gates passed.
These do not override the trusted-base provenance failure. `git diff --check`
passed. The CI `test` job explicitly excludes core tests (ci.yml:574-588);
its reported failure has no supplied failing step/node/traceback. Focused codec
success cannot establish that unrelated job is green.

## Executed commands

All source validation used unchanged starting SHA recorded above.

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py
uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py
uv run python scripts/check-shipped-surface-truth.py
uv run python scripts/check-reachability.py
uv run python scripts/check-reachability-dispositions.py
uv run python scripts/check-promotion-surface.py
git diff --check
```

Only provenance failed (exit 1). No tests added or modified, so no inventory
delta is required. No pre-fix/mutation failure claimed; no source repair made.

## Acceptance evidence and limitations

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Shared frozen/slotted header, typed errors and record interfaces | Source inspected; focused header/scalar mismatch and DTO validation cases passed. |
| Named SQL columns, strict UUID hex, signed timestamps, #1851 constructors | Source inspected; owner/generation and scalar rejection tests passed. Physical request column maps to request_snapshot DTO field. |
| Fresh flat mapping, v2 binding and snapshot fidelity | Three-state unit round trip and fresh-mapping tests passed; independent assertions require task_id=receipt_id alongside run_id. |
| Legacy binding distinctions, receipt-only/partial failures, no guessed identity | Named legacy tests passed. Reconciliation: #1851 binding also requires receipt evidence; a pair without receipt remains partial rather than inventing receipt identity. |
| Header/full-decode separation and unknown formats | Named expiry/fingerprint preservation and unsupported-format tests passed; no clock or request fingerprint accepted by codec. Consumer expiry/409 ordering is C/F2 and UNVERIFIED here. |
| Strict JSON and safe decode errors | Duplicate/nonobject/bare nonfinite, lossy-number, excessive-nesting and surrogate-corruption tests passed with safe error assertions. |
| Tagged evidence and unchanged fingerprint | Tagged fixtures and exact numeric/Unicode preservation tests passed. Real original-model fingerprinting, encode_evidence and model_of/model_of_json materialization remain UNVERIFIED; fixtures hand-construct tags. |
| Migrated disposable PG, raw/production codec contrast, durability | UNVERIFIED this round: three PG cases skipped; no DB sessions or row counts obtained. No fake/SQLite result counted as durability. |
| Explicit authorized principals/Workspace/Project/Graph, Run JSONB object | UNVERIFIED: low-level fixtures are not authorization/admission or Run-persistence tests. |
| No SQL mutation, HTTP mapping, queue, scope utility, live _assess or policy changes | Complete codec inspected: mapping/DTO conversion only. This round changes only this report; canonical execution model preserved. |
| Reachable production behavior | Absent by source import search and reachability scan. Tests and whitelist imports are not runtime wiring. Staged leaf readiness is not activation or parent closeout. |
| Required unchanged CI and prohibition on policy bypass | BLOCKED by reproduced provenance failure at quality/reachability-baseline.json:131,147 and quality/reachability-dispositions.json:612-613. Full CI and generic reported test failure remain UNVERIFIED. |

## Handoff

Only changed file: `docs/testing/issue-1893-repair-61c1d1e4.md`; commit locally.
No source, tests, whitelist, gates, grants or ledgers changed. No push, merge,
GitHub mutation, issue closure or activation performed.

**BLOCKED.** The reproduced defect is not a Vulture mismatch. Resolving it
requires an external, already-landed reachability authorization prerequisite
or separately authorized genuine consumer integration. Neither is authorized
by this repair; adding an import or editing a ledger would bypass the contract.
Request the actual failing CI step/node/traceback before another test repair.
Repeated green codec checks and documentation-only reruns cannot resolve this
blocker. Stop redispatching this unchanged scope until that input changes.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1
required gate. Next: external prerequisite decision and CI failure evidence.

## Repair revalidation — job dd2cf245

Frozen item: #1893 only, assigned worktree `auto-1893`, clean starting HEAD
`fd3eaf9f9b43caf8cb5f8c9ae1bdfe3fb713e20d`, unchanged dispatch base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. This appended handoff is the
only repository edit. No source, tests, inventory counts, grants, ledgers or
workflow changes are justified by the reproduced evidence.

Read the repository instructions, documentation authority map, quality-gate
policy, accepted lifecycle/fencing/storage ADRs named above, both source
modules, both adjacent test files, CI definitions, supplied prior result and
all five driver logs. Reconciliation remains unchanged: admission identity
comparisons grant no execution authority; Goal -> Graph -> Run -> NodeRun ->
Attempt is preserved. A legacy pair without receipt evidence remains a typed
partial binding because the DTO requires receipt identity, not an invented ID.

### Fresh commands and results

The commands in the preceding **Executed commands** block were rerun against
this starting HEAD, except `git diff --check` is run after this report edit.

- Focused pytest: **201 passed, 3 skipped**, 204 cases exercised/collected.
  All skips are the real PostgreSQL contrast cases at
  `packages/maistro-core/tests/tasks/test_admission_codec.py:470`, because both
  database environment variables are unset. No database was touched; there
  are no fresh session identities, migration results or SQL residue counts.
- Ruff check and format: pass, 3277 files formatted; targeted mypy: pass,
  two source files.
- Exact Vulture: pass, 1323 reviewed identities, zero unclassified. The
  vulture-ledger exception therefore supplies no evidenced repair to make.
- Suite inventory: pass, 16466 core nodes, no duplicate test evidence.
- Shipped surface, candidate reachability (1396 modules / 171 unreachable),
  dispositions (50 groups), promotion (74 tolerated modules): pass.
- Trusted-base provenance: **exit 1**, two new unreachable modules and two
  new dispositions not authorized by the trusted base. Exact locations:
  `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:612-613`.

Fresh logs are in
`/home/dev/maistro/jobs/dd2cf245df0e42be8cec6c4b93cfaea6/worker-{focused,vulture,provenance,inventory}.log`.
No pre-fix or mutation failure is claimed; no test was added, so no inventory
note delta is needed. Source import search finds only the codec importing the
identity module and a Vulture whitelist reference, not a production consumer.

### New dispatch evidence and acceptance limits

The frozen dispatch's check-runs data for
`fcc8b437f209a35aa68a61d6f0a5387414938355` records `test: success`
(check 114501824961) and `exact-debt-ledger: failure` (114501824966).
Neither has diagnostic output text in that snapshot. This contradicts the
unqualified `test: failure` repair label, but does **not** establish full CI
success at the current HEAD. The actual failing test step/node/traceback is
**UNRESOLVED**; no guessed test repair or unrelated suite changes were made.

The acceptance table above applies to these fresh focused results: shared
interfaces, strict scalar/UUID/JSON handling, binding rejection, header/full
separation, flat mapping and fixture snapshot fidelity pass. Real-model
fingerprinting/materialization, migrated PostgreSQL round trips, Run JSONB
object persistence, authorized production admission and full required CI
remain **UNVERIFIED** this round. Low-level fixtures do not prove those
claims. Production reachability is absent, not established by unit tests.

**BLOCKED**, not merge-ready. No merge conflict was present. A previously
landed authorization prerequisite or separately authorized genuine consumer
integration is required; neither can be fabricated by this repair. Do not
repeat this unchanged dispatch without that prerequisite or the actual failed
CI diagnostic. Progress: checked 1, done 0 code repairs, skipped 0 issues,
errors 1 required gate; next: external prerequisite and failure evidence.
