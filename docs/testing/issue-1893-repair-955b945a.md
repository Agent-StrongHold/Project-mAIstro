# Issue #1893 repair verification — job 955b945a

## Frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `14b3f0d3f6405419b2305b7ae3214fe603f29e03`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item only: issue #1893 CI repair (`test: failure`, exact-debt-ledger).
- Inspect existing admission codec/identity modules, their two test files,
  relevant ADRs, CI commands, and the supplied job evidence. No new issues,
  remote enumeration, production activation, or authorization changes.
- Initial working tree was clean. No incoming work needed salvage.
- This report is the only planned modification unless validation identifies an
  actionable defect within the assigned scope. Vulture ledger changes are
  permitted only for actual retained findings; reachability grants are not.

## Initial evidence and assumptions

The supplied check logs report dependency sync, lint and formatting success;
201 passing tests with three skips; and suite inventory success (16466 nodes).
These are driver evidence, not live PostgreSQL durability proof.
The generic `test: failure` supplies no failing test node. Reproduce focused
validation and the named gate before considering code changes. Previous
reports are hypotheses, not proof that the current trusted-base gate passes.
The coordinated assignment supplies authority for this repair only; it does
not resolve rollout policy or authorize an independent admission runtime.

## Results

- Resolved `origin/develop` and merge-base to the exact dispatch base; there is
  no local develop-sync conflict or new local base to merge.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings,
  1323 reviewed identities, zero unclassified. No vulture amendment justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add
  unreachable modules and dispositions absent from trusted-base authorization.
  The trusted counts are 169; candidate counts are 171. All other constituent
  provenance gates passed. This independently reproduces the earlier blocker.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3277 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: 1918 passed, 310 skipped, six
  aiosqlite closed-event-loop thread warnings in adjacent SQLite tests.
  Skips do not establish PostgreSQL durability.

Read accepted ADR-081426-1f7c and ADR-082526-7f02: Attempt owns physical
execution identity; immutable Run admission provenance is not dispatch
identity. This representation-only leaf must not introduce a competing runtime
or authorization path. Source import search found no production caller of
`admission_codec`, only codec-to-DTO and whitelist imports. Runtime behavior
must not be claimed from isolated codec tests.

Read accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle) and
ADR-083126-5e62 (protected-base quality authority). Reconciliation: candidate
bookkeeping cannot authorize the two new unreachable modules. The vulture-only
repair exception cannot be used for reachability authorization.

Extracted captured check-runs once from the supplied dispatch (no remote
requests). The failed `test` belongs to linked #1855 head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with no output summary or traceback.
Captured #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` has successful
`test` and failed `exact-debt-ledger`. Assigned-head test-failure attribution
is **UNRESOLVED**; no speculative source edit is justified.

An initial lookup under `migrations/` was not found; skipped. `alembic.ini`
resolves the real chain under `alembic/`; inspected its environment and 055
binding CHECK before live validation.

## Live PostgreSQL validation

Created only a new disposable DB `admission_1893_955b945a` on the existing
assigned `auto-1893-pg` container (PostgreSQL 18.6). Verified it did not already
exist. No existing DB was changed. Ran `uv run alembic upgrade head` from empty
through the real chain to 062, including 055's binding CHECK. No downgrade or
migration-test destruction was performed.

Set nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` to that same DB, plus `MAISTRO_REQUIRE_PG_LEGS=1`.
Executed:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/repair-focused-pg.xml
```

**204 passed, zero skipped.** XML contains every collected node and the three
raw/production-codec session pairs. All used database `admission_1893_955b945a`,
server `172.17.0.9/32:5432`; production/raw PIDs were 40581/40582 (unbound),
40583/40584 (bound), 40585/40586 (acknowledged). Each test asserted one committed
admission row, exact named-column equality through both pools, and typed
rejection of escaped-surrogate corruption in each snapshot TEXT column.
Production pool was required to be non-None and used `_register_json_codecs`.
Final SQL query returned zero admission rows, zero distinct generations and
zero distinct bound Run IDs. DB retained for inspection.

Logs: `repair-migrations.log`, `repair-focused-pg.log`, and
`repair-focused-pg.xml` in the supplied job directory. The source SHA remained
`14b3f0d3f6405419b2305b7ae3214fe603f29e03` throughout validation.

## Additional gates

All executed with 1200-second timeouts; command logs are `repair-check-*.log`
in the supplied job directory:

- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 unique nodes, zero copied-file
  duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger,
  171 unreachable modules of 1396. This does not authorize the new debt.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against
  candidate dispositions, 171 modules in 50 groups; not trusted-base approval.
- `uv run python scripts/check-promotion-surface.py`: PASS.

## Acceptance audit

| Criterion | Executed evidence and limits |
| --- | --- |
| Exact shared API, frozen/slotted scalar header, six decode codes | Source review plus header/schema/constructor tests and scoped mypy passed. |
| V2 immutable DTO, fresh flat named SQL parameters, all snapshot bytes | Three round-trip states and fresh-mapping tests passed; independent assertions check `task_id == receipt_id` and both binding columns; live INSERTs satisfy 055. |
| Strict storage UUID hex and signed timestamps, #1851 constructors | Owner/generation, invalid-scalar, lease-window and immutable DTO tests passed. |
| Bound, unbound, partial legacy records; receipt-only/announced-without-Run never guessed | Legacy distinction, missing-receipt, receipt-only, unreadable/whitespace and missing-request tests passed. A pair without receipt remains partial rather than fabricating identity. |
| Header/full-decode separation and fail-closed unknown formats | Expiry-with-bad-snapshot, fingerprint-with-partial-binding, expired-header and unknown-format/scalar-mismatch tests passed. Decoder takes no clock or request fingerprint. |
| Strict TEXT object JSON and safe error evidence | Duplicate/nonobject/bare nonfinite, numeric-loss, nesting, predecoded-object and Unicode corruption tests passed. Suppressed exception chains and validated-scope-only assertions passed. |
| Tagged nonfinite/context evidence and unchanged stored fingerprint | Tagged, exact-number and valid-Unicode tests passed. Hand-built tags do not prove original-model fingerprinting or real model materialization. |
| Raw and production JSON codecs read same migrated TEXT rows | All three live PG cases passed, non-None pool, distinct backend PIDs, one persisted row each, zero residue. |
| Named SQL fields, acknowledgement and completed_at semantics | Encoder review and live round trips passed; `test_legacy_completed_at_is_never_read` passed. Physical `request` TEXT maps to DTO `request_snapshot`, consistent with the migrated schema. |
| Evidence-json serializers, model_of/model_of_json, original-model fingerprint, Run TEXT-to-JSONB object insertion | **UNVERIFIED end to end**: codec tests use synthetic snapshot objects and do not insert/materialize a canonical Run. |
| Real explicit principals, authorized Workspace/Project and registered Graph kinds | **UNVERIFIED**: DTO fixture identities are not an authorized admission path. |
| No SQL mutation, HTTP, queue, scope-policy, assessment or competing execution authority | Codec remains a pure mapping boundary with no production caller. This round changes only this report. |
| Replacement/409 precedence | **UNVERIFIED**, explicitly a future C/F2 consumer obligation, not B2 behavior. |
| Required focused checks and full unchanged integration CI | Focused checks pass as recorded; full CI **UNVERIFIED**, required trusted-base provenance **FAILED**. |
| Coordinated ownership and production activation | Assignment authorizes this repair only; activation/owner policy remains **UNVERIFIED/BLOCKED**. |

No tests were added or removed; inventory delta is zero and no new inventory
note is required. No fresh regression/mutation result is claimed because no
source/test repair was made.

## Blocked handoff

Existing entries at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` fail the required trusted-base
check in `.github/workflows/vulture-ratchet.yml:77`. No vulture identities are
unbanked, so that permitted repair cannot resolve this measured failure.
Existing source, tests and ledgers are preserved. A fake caller, candidate
self-grant, or unauthorized production activation is not an acceptable fix.

Next: owner must coordinate an independently landed reachability authorization
under the two-merge rule, or separately approve the real consumer integration.
Supply an assigned-head failing CI traceback if another test repair is wanted.
Do not repeat unchanged validation as a substitute for either missing input.

Progress: checked 1 item; done 0 repairs; skipped 0 items; errors 1 reproduced
provenance blocker. This is a blocked handoff, not merge/integration approval.
No GitHub mutation, fetch, merge, or destructive Git operation was performed.
