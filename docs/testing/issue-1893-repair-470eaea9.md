# #1893 repair handoff — job 470eaea9

## Scope and decision

Checked only assigned issue #1893 in `auto-1893`, starting at clean
`52eeec19bbcff5657b54a2d67ac83c40ec7a8ea4`. The supplied base and local
`origin/develop` both resolve to `3c761d14db944a727fa0744444bc67cfe36d49f7`.
No merge conflict or uncommitted work was present. Frozen inspection scope:
admission codec, identity DTOs, adjacent tests, governing ADRs and relevant CI
checks. This report is the only edit; no code, tests, inventory counts, ledgers,
grants or gates changed. No GitHub mutations.

**BLOCKED**, not repaired. The reproduced failure is a reachability authorization
failure, not unbanked Vulture identities. The explicit Vulture-ledger exception
does not authorize reachability ledger edits. ADR-083126-5e62 preserves trusted
base authority; ADR-081226-a66b preserves Run/NodeRun/Attempt lifecycle ownership.
Adding a fake import or activating an unreviewed consumer would violate the
issue's staged, representation-only scope. No such workaround was attempted.

## Executed evidence

All commands below ran independently against the starting source with
1200-second command timeouts. Logs are `worker-*.log` in
`/home/dev/maistro/jobs/470eaea9e25e4e3f917445b39ea58683/`.
Driver `check-0.log` through `check-4.log` were also read; their passing results
are not substituted for the independent runs below.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed findings, zero unclassified. No ledger amendment justified. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL: two unauthorized unreachable modules and two unauthorized dispositions, naming `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`. Other subgates pass. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped in 1.36s. PostgreSQL DSNs absent; no live DB proof. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: 2 files |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes; zero duplicate evidence |

The supplied dispatch JSON was inspected locally, without re-fetching. Its only
failed `test` check names dependency head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output title, summary and
text. It is not an assigned-head traceback. Extracted evidence is retained as
`worker-supplied-test-checks.json`. CI's `test` job excludes the core unit suite
(`.github/workflows/ci.yml:574` onward); focused codec passes do not prove that
job repaired. Full integration CI remains UNVERIFIED.

## Acceptance audit

Both implementation modules and both focused test files were read. A production
source reference search finds only the codec-to-DTO import and Vulture whitelist
import (`worker-references.log`). The trusted-base gate independently reports
both modules unreachable. No runtime admission behavior is proven by these DTO
tests.

| Criterion | Evidence and limits |
| --- | --- |
| Frozen/slotted header, required signatures and six typed failure codes | Source inspected; scalar, mismatch, unknown-format and constructor cases pass. |
| Named columns, signed timestamps, strict storage UUID `.hex`, #1851 constructors | Focused schema/UUID/range tests pass; encode returns a fresh flat mapping. |
| Safe decode errors with validated hash only | Invalid scope, malformed snapshot and owner-token cases pass, including suppressed parsing chains. |
| Immutable snapshots, unchanged fingerprint, arbitrary permitted evidence | Round-trip, nonfinite tags, Unicode and exact-number cases pass; fingerprints/tags are supplied fixtures, not production model serialization proof. |
| Strict TEXT JSON | Duplicate keys, nonobject roots, bare nonfinite values, lossy numbers, excessive nesting and lone-surrogate rejection cases pass with storage-text injection. |
| Legacy bound/unbound/partial/receipt-only evidence without invented identity | Focused cases pass. A pair without a receipt is partial because the DTO requires receipt identity; no-invention takes precedence over the issue's shorthand that both IDs are bound. |
| Header evidence survives full decode errors; unknown formats fail closed | Both named header-separation cases and unsupported-format cases pass. No clock, incoming fingerprint, assessment or claim API exists. |
| SQL mapping and acknowledgement | Independent encoder assertions check paired task_id/run_id and task_id=receipt_id; DTO receipt mismatch is rejected. completed_at grants no authority. Live constraint execution UNVERIFIED this round. |
| Original-model fingerprinting, evidence-json encoding and model_of/model_of_json materialization | UNVERIFIED: no production consumer; fixtures do not establish these integration behaviors. |
| Migrated disposable PostgreSQL, raw/production pools and session/row counts | UNVERIFIED: all three DB cases skipped at test_admission_codec.py:470 for absent DSNs. No session identities or final row counts claimed. |
| Run JSONB object INSERT, explicit authorized principals, Workspace/Project and registered Graph | UNVERIFIED: no runtime admission or Run INSERT executed. |
| No SQL mutation, HTTP/queue/scope/classifier or policy change | Source is mapping-to-DTO only; this round changes documentation only. Consumer expiry/replacement/409 behavior is outside B2 and UNVERIFIED. |
| Meaningful tests, inventory, pre-fix evidence | Existing tests inject malformed storage rather than mocked claims. Inventory passes unchanged. No new tests or mutation/pre-fix experiment; no inventory delta required. |
| Required CI, production reachability, coordinated activation | NOT established: provenance gate fails; no production consumer. Local lane ownership is not external stack coordination, merge approval or rollout authorization. |

## Required next action

The blocked identities remain in `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:612-613`, rejected by the mandatory
check at `.github/workflows/vulture-ratchet.yml:77`. An owner must arrange
separate trusted-base authorization or the properly scoped consumer integration;
this worker cannot self-authorize it. Obtain an assigned-head failing test step
and traceback before requesting another test repair. Repeating this unchanged
repair dispatch cannot resolve that authority boundary.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate.
Only this blocked handoff is committed. Residual risks: inactive runtime surface,
unverified live PostgreSQL and model/auth integration, and unverified full CI.

## Follow-up repair dispatch c086aadcf95d4540a77949ef3ac42921

Independently checked clean starting HEAD
`f65a237279b114a6eb935792def9640039dc91c3` against the same verified supplied
base `3c761d14db944a727fa0744444bc67cfe36d49f7`. Read the current issue body,
supplied driver `check-0.log` through `check-4.log`, both implementation modules,
codec tests, CI workflows, and accepted ADRs 081226-a66b, 082526-7f02 and
083126-5e62. No source repair is justified by the supplied `test: failure` label.
This appendix is the only repository change; no tests or inventory delta.

Re-executed every command in the evidence table above with 1200-second timeouts
(the Vulture command used 600 seconds). Results: Vulture **PASS**, 1323 reviewed
identities and zero unclassified; provenance **FAIL**, the same two unauthorized
modules and two dispositions; focused pytest **201 passed, 3 skipped in 1.31s**;
ruff check/format, scoped mypy, shipped-surface and suite inventory **PASS**
(3277 formatted files; 16466 core test nodes). Logs are `repair-*.log` under
`/home/dev/maistro/jobs/c086aadcf95d4540a77949ef3ac42921/`. The acceptance table
above remains accurate for this execution, including its explicit UNVERIFIED
items: the skipped PostgreSQL cases are not durability evidence, fixture tags
are not production model integration, and no runtime consumer was found.

Locally extracted all supplied `test` check records once into
`repair-supplied-test-checks.json` in that job directory. The sole failed check
still names dependency head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this
assigned head, and carries no output title, summary or traceback. Other captured
heads' successful checks do not validate this head. Full CI is UNVERIFIED;
focused core tests do not reproduce the separate CI `test` job.

**Still BLOCKED.** No Vulture ledger amendment is needed or justified; that
exception cannot authorize reachability policy changes. There is no sync
conflict to resolve. Required next action remains owner-mediated trusted-base
reachability authorization or separately scoped consumer integration, plus an
assigned-head failing test step/traceback. Do not redispatch this unchanged
source as a test repair without new evidence or authority. No activation, fake
imports, grant/gate edits, GitHub mutations or closure actions were performed.
Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 required
gate; local handoff updated for commit.

## Follow-up repair dispatch 8b2f9d3f6dc64bd881525a2d6e251343

Starting HEAD: `5df212baae38ac7d03648fbbc85f055c147f3a65`, clean worktree.
Verified supplied base and local `origin/develop` both resolve to
`3c761d14db944a727fa0744444bc67cfe36d49f7`. There is no sync conflict.
Frozen scope remains #1893 only; no remote issue/PR refresh or mutation.
Read the current captured issue body, driver check-0 through check-4, prior
result, complete codec/identity sources and both adjacent test files, workflow,
and accepted ADRs 081226-a66b, 082526-7f02 and 083126-5e62. Reconciliation:
immutable admission facts are not execution authority; an inactive B2 contract
cannot acquire a fake consumer or authorize its own reachability debt.

Independent execution (1200-second validation timeouts; logs `repair-*.log`
in `/home/dev/maistro/jobs/8b2f9d3f6dc64bd881525a2d6e251343/`):

- `uv sync --locked --extra dev`: PASS.
- Re-executed all eight commands in the original evidence table above.
  Vulture PASS: 1323 reviewed identities, zero unclassified. Provenance FAIL:
  `repair-provenance.log:20-29` rejects the two new admission modules and their
  dispositions against the verified base. No Vulture amendment is warranted.
- Focused pytest: **201 passed, 3 skipped in 1.28s**, 204 nodes. The three
  PostgreSQL cases skip at `test_admission_codec.py:470` for missing DSNs.
- Ruff check/format, scoped mypy, shipped-surface and suite inventory PASS:
  3277 formatted files, two typed source files, 16466 unique core test nodes.
- `rg -n 'admission_codec|admission_identity' packages/maistro-core/src` finds
  only the defining codec's references and the Vulture whitelist import.
  The provenance gate independently confirms both modules remain unreachable.

The acceptance audit above remains applicable to this independently executed
head: strict decoding, immutable representation, header separation and legacy
fail-closed tests pass, but no reachable production admission is proven.
Live migrated PostgreSQL/raw-versus-production pools, DB identities/row counts,
actual-model evidence-json materialization and fingerprinting, Run JSONB object
insertion, authorized principals/Workspace/Project/Graph, and full integration
CI are **UNVERIFIED** this round. No mutation experiment or new regression test
was performed; no tests changed, so there is no inventory delta. Existing work,
including historical inventory notes and all ledgers, is preserved.

Extracted captured `test` checks once into `repair-supplied-test-checks.json`.
The only failed check is still for dependency SHA
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`; its output title, summary and text
are null. No assigned-head traceback was supplied. CI's separate `test` job
excludes core tests (`.github/workflows/ci.yml:574-589`), so this focused run
cannot be reported as repairing that job.

**BLOCKED; no source repair justified.** Required next action is unchanged:
owner-mediated trusted-base authorization or separately scoped consumer
integration, and an assigned-head failing test step/traceback. The permitted
Vulture-ledger exception does not extend to reachability policy. Do not repeat
this unchanged dispatch expecting a different outcome. Only this evidence
appendix is changed for local commit; no source, test, gate, grant, activation
or closure changes. Progress: checked 1, done 0 repairs, skipped 0 issues,
errors 1 mandatory gate; next: owner resolution of the authorization blocker.
