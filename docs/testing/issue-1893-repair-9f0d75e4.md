# Issue #1893 repair handoff — 9f0d75e4

## Scope and outcome

**BLOCKED.** Tested source: `bd8c0eb6095207d924a3526320522198a2ffb31a`.
Frozen base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, initially clean.
Only issue #1893 was processed. This report is the only changed file; no source,
tests, inventory counts, ledgers, grants or gates were changed.

Read repository instructions, the full issue body in the frozen dispatch, linked
#1325/#1855 PR evidence, prior result, driver `check-0.log` through `check-4.log`,
and accepted ADRs `081226-a66b`, `082526-7f02`, `083126-5e62`.
Reconciliation: preserve Goal -> Graph -> Run -> NodeRun -> Attempt and immutable
admission provenance. Staged DTO work does not authorize production activation,
a fake runtime caller, or candidate-controlled authorization. The explicit
Vulture-ledger repair exception does not extend to reachability dispositions.

## Independently executed validation

Commands ran in the assigned worktree with 1200-second timeouts. Logs are under
`/home/dev/maistro/jobs/9f0d75e4414d4af9b711455fe8aa9200`.

| Command | Actual result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities/findings, zero unclassified; `repair-vulture.log`. No amendment warranted. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules and two unauthorized dispositions; `repair-provenance.log:20-29`. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 204 outcomes: 201 passed, 3 skipped in 1.35s; `repair-pytest.log`. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3277 files formatted. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: 2 files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `repair-shipped-surface.log`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes; zero duplicate evidence; `repair-inventory.log`. |
| `git diff --check` | PASS before report creation; repeated before commit. |

Driver logs independently inspected: dependency sync, lint, formatting, focused
tests and inventory passed, also with three PostgreSQL skips. Historical live-PG
and mutation claims were not treated as executions at this head.
No tests added or removed, so no inventory-delta note is required.

## Acceptance audit

- **Public types/interfaces and immutable representation:** source inspected;
  focused codec/identity tests passed. Header is frozen/slotted; six error codes,
  exact named fields, fresh flat mappings, strict storage UUID hex and signed
  timestamps are covered. Header immutability itself is source-verified.
- **Header/full-decode separation:** passed mismatch, unsupported schema/format,
  malformed-snapshot and partial-binding cases. Expiry and fingerprint survive
  full-decode failures. No clock, incoming fingerprint or assessment decision is
  accepted by the codec.
- **Identity without guessing:** passed bound/unbound/partial/receipt-only cases.
  Bound legacy pairs lacking receipt evidence fail rather than fabricate the
  receipt required by the canonical binding. `completed_at` confers no authority.
  Bound v2 mapping independently asserts both `task_id == receipt_id` and `run_id`
  (migration 055), not merely encoder/decoder agreement.
- **Strict TEXT snapshots and safe errors:** passed duplicate/nonobject/bare
  nonfinite, excessive nesting, precision-loss, Unicode and malformed identity
  cases. Tests inject original corrupt storage values directly and check typed
  errors, omitted private data and suppressed parsing chains.
- **Snapshots/fingerprints:** canonical bytes and hand-built evidence tags survive
  tested round trips without fingerprint changes. Raw JSON formatting is
  canonicalized. Production `evidence_json` plus `model_of`/`model_of_json`
  materialization and arbitrary permitted program_context are **UNVERIFIED** by
  these fixtures; no materialization path is introduced in this leaf.
- **Database proof:** **UNVERIFIED this round**. Three raw/production-pool tests
  skipped at `test_admission_codec.py:470` because both required database URLs
  were unset. No disposable DB, migration-chain run, session identities or final
  SQL counts were produced. No skipped test is counted as durability evidence.
- **Run JSONB object, authorized principals/Workspace/Project/registered Graph:**
  **UNVERIFIED**; these DTO tests do not admit or persist a canonical Run.
- **Stage boundary:** source inspection confirms no SQL mutation, HTTP response,
  queue, scope utility, claim or policy change. Consumer replacement/409 ordering
  is C/F2 evidence, **UNVERIFIED** here, not a claim made by B2.
- **Production reachability:** not satisfied. Source import search finds only
  codec -> identity and `_vulture_whitelist.py:105`; no production consumer.
  `admission_codec.py:51-54` explicitly documents that inactivity. Tests and
  exports are not runtime wiring.
- **Validation/staging:** focused tests, lint, format, scoped mypy and inventory
  passed subject to PG skips. Full required integration CI and external
  base/ownership/activation release remain **UNVERIFIED**. No new mutation,
  transaction, crash or dispatch invariant is claimed.

## Blocking evidence and next action

`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` add the admission modules without
trusted-base authorization. The required `exact-debt-ledger` job runs the failed
provenance checker at `.github/workflows/vulture-ratchet.yml:77`.
Owner-controlled trusted-base resolution is needed before a coordinated sync;
this worker cannot grant it or activate the prospective consumer. No conflict
existed, so the conditional conflict-repair fetch/merge instruction did not apply.

The generic `test: failure` remains **UNRESOLVED**. Frozen dispatch evidence names
a failed `test` for linked head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`
(`dispatch-context.json:114368-114376`), not this assigned HEAD. No attributable
assigned-head failing node/traceback was established. CI partitions core tests
out of its `test` job (`.github/workflows/ci.yml:574-612`), so focused success does
not prove that job passes. Obtain the assigned-head failing step and diagnostic
before changing unrelated code; no speculative repair was made.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate.
Next: trusted-base reachability resolution and attributable test-failure evidence.
This local report commit is a blocked handoff, not merge approval or issue closure.
