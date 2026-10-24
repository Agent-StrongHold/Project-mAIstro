# Issue #1893 bounded repair checkpoint

Snapshot: issue #1893 only; assigned branch `auto-1893`, starting HEAD
`0c40580712dbe5c9516405816a88077930cc2737`, supplied develop base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Initial worktree clean.

Scope: inspect existing admission codec/identity types, adjacent tests and their
inventory notes, relevant ADRs, supplied job check logs and CI workflow. Repair
only reproduced #1893 defects; vulture ledger only if the explicitly requested
scan identifies reviewed retained debt. No reachability grants, activation,
HTTP/queue changes or unrelated CI repairs. This report is the checkpoint file.

Ambiguity: generic prompt contains verifier and writer instructions; explicit
assigned repair and commit requirement select writer mode. Existing BLOCKED
reachability finding is evidence to reproduce, not permission to alter grants.
No remote refs or GitHub lists will be refreshed.

## Reproduced results

- Supplied check-0 through check-4 logs: sync, lint, format, focused tests
  (324 passed, 3 skipped), suite inventory (16543 nodes) pass. No failing test
  traceback is supplied. Prior result artifact independently inspected; it
  reports the same unresolved provenance block, not a repaired integration.
- Executed requested Vulture scan: PASS, 1322 findings, zero unclassified and
  zero never-allowlist. No ledger amendment justified.
- Executed `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py`: FAIL, exit 1, both admission modules
  introduce unauthorized unreachable-module and disposition entries. Ref
  `origin/develop` resolves to the supplied base; gate uses merge-base
  `2154f845347c`. No unresolved ref or merge conflict exists.
- This is an authorization boundary, not a Vulture identity failure. No fake
  production caller, baseline removal or grant edit will be used to hide it.

- Independent lint and format pass (3301 files); scoped mypy passes (2 source
  files). Independent four-file focused pytest: 324 passed, 3 PostgreSQL skips
  in 1.61s. Skips explicitly require both PostgreSQL DSNs; not durability proof.
- Accepted ADR-081226-a66b preserves sole Run/NodeRun/Attempt authority;
  ADR-083126-5e62 forbids candidate-controlled authorization. Reconciliation:
  staged codec contracts cannot justify activating another authority or
  authorizing their own unreachable debt.
- Attempted prose-derived ADR filename `ADR-082526-7f02-immutable-admission-provenance.md`
  was not found; skipped. Exact filename discovery is needed before reading.
- Initial production-import glob returned no matches (inconclusive); replace
  it with an explicit source-tree search rather than claiming absence.

- Full scoped core suite executed with `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`:
  15470 passed, 1070 skipped, 3 xfailed, 54 warnings in 231.54s. Output:
  `/tmp/1893-7027ef63-core.log`. Warnings include aiosqlite thread shutdown on
  closed event loops and an unawaited fake-process coroutine. No failing test
  reproduced; skips/xfails are not positive acceptance evidence.
- Corrected explicit `packages/*/src` search finds only codec -> identity and
  whitelist -> identity imports. No production codec reader found; module
  docstrings explicitly state inactive contracts. This is not changed here.
- Suite inventory passes (16543 unique nodes, zero duplicate evidence);
  shipped-surface truth and `git diff --check` pass.

Job artifacts:
`/home/dev/maistro/jobs/7027ef63ced241308c431dd44688d137/`.

## Executed command record

All checks below ran against the starting source SHA (only this report changed):

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py
uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -q -x -rs
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
uv run python scripts/check-shipped-surface-truth.py
git diff --check
```

All exit 0 except provenance (exit 1). Full integration CI beyond core was not
executed. No new tests or inventory delta: existing tests rerun unchanged.
The existing B2 inventory note was inspected for the contract and storage
boundary; historical results there are not counted as this round's evidence.

## Acceptance audit

| #1893 criterion | Evidence and limit |
| --- | --- |
| Frozen/slotted scalar header; strict format, hash and signed timestamps | `admission_codec.py:158-232` inspected; focused header mismatch, unknown format and invalid scalar tests pass. |
| Named columns, exact immutable v2 DTO, fresh flat mapping, UUID hex at storage only | `admission_codec.py:235-294` inspected; three binding-state round trips and strict UUID/fresh-map tests pass. Storage binding independently asserts paired task/run and receipt agreement at `test_admission_codec.py:134-137`. |
| Legacy unbound/bound/partial distinctions without invented identities | Focused partial-pair, receipt-only, missing receipt, whitespace evidence, expired header and ignored completed-at tests pass. |
| Typed safe failures; strict TEXT object parsing | Duplicate/nonobject/nonfinite, excessive nesting, precision loss, UTF-8 and suppressed-exception tests pass. No raw snapshot or token is quoted by these tested error paths. |
| Header evidence survives malformed snapshot/partial binding; no clock, decision, mutation or HTTP/queue change | Focused expiry/fingerprint preservation tests pass; inspected codec accepts no clock/incoming fingerprint and performs no SQL/HTTP/queue work. Consumer replacement/409 precedence is outside B2, not claimed. |
| Preserve tagged context/fingerprint | Pure tagged snapshot round trips pass. Actual model materialization through evidence-json/model_of and production fingerprint computation remains UNVERIFIED: fixtures use prepared dictionaries and fixed hashes. |
| Raw and production pools on the same migrated disposable PG; Run JSONB object | UNVERIFIED this round: three PG legs skipped for missing DSNs. No migrations, sessions, DB row counts or Run JSONB proof claimed. Did not provision a DB for a round already blocked on independent authorization. |
| Positive tests use authorized principals, Workspace/Project and registered Graph | UNVERIFIED at admission level: codec tests construct strings (`ws-1`, `proj-1`, etc.), not authorized production admissions. They establish representation only. |
| Required unchanged gates and reachable production behavior | Lint/format/mypy/Vulture/inventory/shipped-surface/core suite pass; provenance FAILS. Source-tree import search confirms codec is inactive; tests and whitelist are not production reachability. Full integration CI UNVERIFIED. |
| Scoped staged implementation, no new authority | Only this report changed. Accepted ADR-081226-a66b, ADR-082526-7f02 (exact discovered filename), ADR-082526-1899 and ADR-083126-5e62 read. No execution, Goal, event, scheduler, authorization, metadata or activation changes. |

No new regression test or mutation result is claimed because no source repair
was justified by the executed evidence. Prior binding-repair claims are not
substituted for current live database validation.

## Handoff

**BLOCKED.** `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614` retain unauthorized additions
for the two inactive admission modules. The unchanged exact-debt-ledger workflow
runs the failing provenance gate at `.github/workflows/vulture-ratchet.yml:77`.
The explicitly permitted Vulture amendment does not cover reachability grants;
its scan is already green. This round cannot self-authorize these entries.
A separately reviewed trusted-base authorization or explicitly authorized real
consumer integration must precede another readiness attempt. No merge conflict
was found, so the conditional develop-sync repair does not apply.

The reported generic `test: failure` remains unattributed: supplied logs contain
no failed node, and focused plus full core execution pass. Obtain the actual
failing CI traceback/head before requesting another test repair; do not cycle
this lane solely on the same unresolved authorization failure.

Changed file: this report only. No source/test/gate/ledger/grant changes, no
GitHub mutations. Commit locally as a blocked checkpoint, not integration
approval. Residual risks are the inactive consumer, unavailable original failing
CI node and unverified PG/model-materialization/full-integration acceptance.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base authorization decision and actual failing CI traceback}`.

## Independent repair recheck — job 88b944800354419e919218abfac54a52

Starting source SHA: `5c7a8dd288c9b5627258237adc32db0af5fbeea1`.
Assigned item remains #1893 only. Initial tree clean; no salvage required.
`origin/develop` resolves to the supplied `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`;
no unresolved ref or merge conflict was found. No remote enumeration or fetch.

Read repository instructions, the supplied dispatch issue body, previous result,
all five driver logs, codec/identity implementation, codec tests, existing B2
inventory contract and accepted ADRs 081226-a66b, 082526-7f02 and 083126-5e62.
Those ADRs preserve canonical lifecycle, immutable admission provenance and
trusted-base authority; nothing here warrants overriding them or activating the
staged consumer. Driver logs contain no failed test or traceback.

Independently executed against this source SHA:

| Command | Observed result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 findings, zero unclassified, zero never-allowlist. No amendment justified. |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | FAIL: trusted base `2154f845347c`; both admission modules are unauthorized new unreachable modules and unauthorized new dispositions. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3301 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files. |
| Four-file focused pytest command recorded above, with `-x -q -rs` | 324 passed, 3 skipped in 1.68s; skips explicitly require both PG DSNs. |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q` | Exit 0: 15470 passed, 1070 skipped, 3 xfailed, 53 warnings in 228.41s. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16543 unique nodes, zero duplicate evidence. |

Focused and full-core logs are `worker-focused.log` and `worker-core.log` under
`/home/dev/maistro/jobs/88b944800354419e919218abfac54a52/`. Warnings include
aiosqlite closed-event-loop thread shutdowns and an unawaited fake-process
coroutine; neither caused a failure. No full integration CI result is claimed.

The acceptance table above remains accurate for this round: the executed pure
tests cover strict scalar/header agreement, immutable records, UUID storage,
legacy dispositions, safe JSON failures, fresh mappings and preserved tagged
snapshots/fingerprints. Inspection confirms no clock, SQL mutation, HTTP or
queue behavior in the codec. The tag tests use prepared dictionaries and a
fixed fingerprint, so production model materialization and original-model
fingerprinting remain **UNVERIFIED**, not inferred from passing round trips.
Live PostgreSQL durability, raw/production pool agreement, Run JSONB object
storage and authorized Workspace/Project/Graph admission remain **UNVERIFIED**.
No disposable DB was provisioned in this already authorization-blocked round.
No mutation experiment or new regression test is claimed without a source fix.

An explicit `rg` search across `packages/*/src` finds only codec-to-identity and
whitelist-to-identity imports; no production codec reader. The module itself
states this at `admission_codec.py:50-53`. Tests/whitelist imports do not establish
runtime reachability. The exact-debt-ledger workflow still invokes the failing
provenance checker at `.github/workflows/vulture-ratchet.yml:77`.

**BLOCKED, not repaired.** The permitted Vulture amendment cannot authorize the
reachability/disposition additions at `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:604-614`. Do not manufacture a caller,
delete retained contracts or weaken a gate to hide this. The actual failing CI
node/head/traceback is still required to repair the reported `test: failure`.
A separately reviewed trusted-base authorization or authorized real consumer
integration is still required for the existing provenance block. Neither is
within this repair lane's authority.

Changed file: this checkpoint only; previous evidence preserved. No source,
test, inventory-count, ledger, grant or gate changes. No GitHub mutation.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: authorization decision and failing CI traceback}`.
