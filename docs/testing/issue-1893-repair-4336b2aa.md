# Issue #1893 repair — job 4336b2aa

## Frozen scope and entry evidence

- Sole item: #1893 in `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Verified clean starting HEAD: `29962eadf97ce02907771269055dbd428b072879`.
- Supplied trusted base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Evidence snapshot: supplied job dispatch-context.json and check-0 through
  check-4 logs; supplied prior result 6f300fabce6e491795e3347c277f0cff.
  No remote refresh, PR processing or GitHub mutation is planned.
- Review files: repository instructions/docs index, applicable execution and
  quality ADRs, CI workflows and gate scripts, admission codec/identity modules,
  their tests, and existing atomic-admission inventory notes.
- Write scope: this report; codec/identity/tests and an inventory delta only if
  a defect is reproduced. Vulture ledger amendment only for actually reported
  retained identities. No reachability, authorization or gate changes.

The driver logs pass dependency sync, Ruff, format, focused tests (346 passed,
3 skipped), and suite inventory (16567 nodes). They contain no failing test
traceback. Prior result is BLOCKED on trusted-base reachability, not Vulture.
These are supplied evidence, not fresh validation. Ambiguity: `test: failure`
does not identify a SHA/node/traceback; reproduce focused checks without
inventing a repair. Existing implementation/history is preserved.

## Fresh validation

Fresh exact Vulture gate passed: 1322 reviewed identities / 1322 findings,
zero unclassified or never-allowlist findings. No Vulture amendment is justified.
Fresh trusted-base provenance gate failed (exit 1): both
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new
unauthorized unreachable modules and new unauthorized dispositions (169 -> 171).
Logs: `.pytest_cache/repair-4336b2aa/{vulture,provenance}.log`.

The supplied base resolves and is the actual merge base with HEAD. No merge
conflict exists. Read accepted ADRs 081226-a66b, 082526-7f02, 082826-b601 and
083126-5e62: preserve the canonical execution spine, immutable admission
provenance, opt-in consumer and trusted-base authority. Reconciliation: do not
activate this staged codec or introduce fake runtime imports to bypass the
reachability failure. The Vulture-only exception cannot authorize reachability
policy edits. This confirmed blocker cannot be repaired within this lane.

No source or test edits; no test inventory delta. Fresh results at the starting
source SHA (all validation commands given 1800-second timeouts; log prefix
`.pytest_cache/repair-4336b2aa/`):

| Command | Result / log |
| --- | --- |
| `uv run ruff check .` | PASS (`ruff.log`) |
| `uv run ruff format --check .` | PASS, 3301 files (`format.log`) |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files (`mypy.log`) |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 346 passed, 3 skipped, 349 nodes (`focused.log`); no PG DSNs for this run |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1919 passed, 310 skipped, 2229 nodes, 6 aiosqlite closed-event-loop thread warnings (`adjacent.log`); no PG DSNs for this run |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16567 nodes, no duplicate evidence (`inventory.log`) |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS (`shipped.log`) |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger, 1403 modules / 171 unreachable (`reachability.log`); NOT trusted-base authorization |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger, 50 groups / 171 modules (`dispositions.log`); NOT trusted-base authorization |

The exact required Vulture command was `uv run python
scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'`. The failing command was
`RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python
scripts/check-ratchet-provenance.py`. All its other subchecks passed.

## Dedicated real PostgreSQL validation

Confirmed `maistro_1893_4336b2aa` absent before `createdb`; server reports
PostgreSQL 18.6. Ran `DATABASE_URL=postgresql:///maistro_1893_4336b2aa uv run
alembic upgrade head`: PASS through the real chain to 063, including 055
(`migration.log`). No shared database was migrated or truncated.

With **both** `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
`postgresql:///maistro_1893_4336b2aa` and `MAISTRO_REQUIRE_PG_LEGS=1`, executed:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=.pytest_cache/repair-4336b2aa/focused-pg.xml
```

**204 passed, zero skipped** (`focused-pg.log`, 204 collected nodes). The three
real pool cases require non-null pg_pool, independently connected raw and
production JSON-codec sessions on the same server/database, and actual SQL
INSERT/SELECT with one persisted admission row per case. They also exercise
escaped-surrogate corruption in each TEXT snapshot column.

Session IDs (production/raw): unbound 485766/485776; bound 485788/485799;
acknowledged 485800/485801. All report database `maistro_1893_4336b2aa` over
the local Unix socket. Final direct SQL (`final-sql.log`) confirms revision
063 and **0 admission rows, 0 distinct generations, 0 distinct Run identities**.
The disposable database is retained for inspection.

Mutation control (`mutation.log`): a separate `uv run python` process replaced
only the in-memory encoder with a wrapper setting `task_id=None`, then invoked
pytest on `test_v2_round_trip_preserves_all_snapshot_bytes[bound]`. Expected
pytest exit 1: assertion at `test_admission_codec.py:134` fails (`None !=
'rcpt-1'`). The wrapper asserted that exit code and exited successfully. No
on-disk source was modified. This catches the previously repaired binding-pair
regression independently of encoder/decoder agreement; it is not a current
source failure.

## Acceptance accounting

All codec/identity tests below ran in the 204-pass real-PG command above.
Library contract evidence is not production activation or authorization proof.

| Criterion | Executed evidence / boundary |
| --- | --- |
| Frozen/slotted `AdmissionRowHeader`, named columns, strict supported format, signed timestamps, fingerprint and scope hash | Source `admission_codec.py:157-233`; invalid-scalar, unknown-format, missing-column and scope-hygiene tests passed. |
| Supplied header must match all row scalar fields | Scalar-mismatch and supported/unsupported-format tests passed; full decode re-derives the header. |
| Exact immutable V2 DTOs, fresh flat mapping, storage UUID `.hex` only | Three-state byte round trips, owner-token/generation tests, fresh-mapping tests and actual bound SQL INSERT passed; migration 055 lines 206-210 enforce the paired identity. |
| Legacy bound/unresolved/partial distinct; never guess receipt, Run or task identity | Bound/unbound/partial, receipt-only, missing-receipt, unreadable and whitespace-evidence tests passed. `completed_at` grants no authority. |
| Minimal header remains available despite expired/partial/malformed full record | Expired-header and both header-preservation tests passed. Source takes no clock or incoming request fingerprint and performs no expiry/mismatch/claim decision. |
| Six typed decode codes; no raw snapshots/tokens in diagnostics or exposed parsing chains | JSON/nesting/numeric/Unicode corruption and token/scope tests passed; codec suppresses parsing exception chains. |
| Reject duplicate keys, nonobjects, bare nonfinite values; preserve tagged and permitted evidence | Strict JSON, tagged-nonfinite, exact numeric and Unicode tests passed. Stored fingerprint passed through without recalculation. |
| Raw and production pool codecs read the same TEXT snapshots against real migration chain | All three live pool cases passed, with independent session IDs, one SQL row per case and final zero residue above. No skipped/fake/SQLite leg counted as durability proof. |
| Existing evidence-json / model_of materialization; original-model fingerprint before tagging | UNVERIFIED end-to-end: codec preserves canonical tagged TEXT but fixtures use synthetic snapshots and a predetermined fingerprint, not real TaskResponse/Run materialization. |
| Authorized explicit principals, Workspace/Project, registered Graph; Run payload JSONB object rather than doubly encoded string | UNVERIFIED: these tests insert admission rows directly and do not create an authorized canonical Run. |
| Pure representation leaf; no SQL mutation/HTTP mapping/queue, scheduler, scope utility, legacy/deletion policy or live assessment changes | Inspected production codec is Mapping/DTO conversion only. This repair changes this report only; canonical Goal -> Graph -> Run -> NodeRun -> Attempt is untouched. |
| Inventory, lint, format, scoped mypy and relevant gates | PASS as listed, except trusted-base reachability provenance FAIL. No test additions: inventory delta zero; existing notes remain unchanged. |
| Runtime reachability, full unchanged integration CI, consumer expiry/409 precedence, activation and coordinated integration readiness | UNVERIFIED / BLOCKED. Production import search finds only codec-to-identity and Vulture-whitelist imports; `admission_codec.py:50-53` explicitly has no production consumer. No fake import/export added. Full hosted `test` job covers additional suites/frontends not run here. |

## Disposition and next action

**BLOCKED**, not merge-ready. Fresh provenance evidence rejects
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` against the supplied trusted
base. Candidate-ledger scan success is not authorization. Do not repeatedly
redispatch this as a Vulture identity repair: Vulture is already green and its
exception cannot authorize a reachability/grant/gate edit.

The reported hosted `test: failure` remains **UNRESOLVED**: the supplied five
check logs have no failing traceback, fresh focused/adjacent tests pass, and
no assigned-head failing node is supplied. Existing historical notes and
captured comments are not current-head full-CI proof. No speculative source
repair, fetch, merge, policy edit or GitHub mutation was performed.

Next input: authorized integration owner resolves the trusted-base dependency
outside this lane, and supplies the exact failing `test` SHA/node/traceback if
that separate failure persists. No issue/parent closure or rollout is claimed.

Changed file: `docs/testing/issue-1893-repair-4336b2aa.md` only. `git diff
--check` passed before staging. Local documentation commit is an evidence
handoff, not integration approval. Progress: checked 1, done 0 repairs, skipped
0 items, errors/blockers 1 (confirmed provenance failure); validation completed.
