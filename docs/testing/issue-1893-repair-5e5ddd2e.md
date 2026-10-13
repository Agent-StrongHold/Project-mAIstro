# Issue #1893 repair checkpoint — job 5e5ddd2e

## Frozen scope

- Single item: #1893, writer repair on `auto-1893` in the assigned worktree.
- Starting HEAD: `ea673321cf038c0c1330bd312d0721d3c8ae82d1`.
- Supplied develop base and local `origin/develop`: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean incoming worktree; no salvage required.
- Review scope: admission codec, admission identity constructors, adjacent tests,
  relevant ADRs, supplied job evidence, CI workflow and named quality gates.
- Planned write scope: this evidence note only unless executed checks identify an
  authorized, substantive repair. No reachability/grant/gate edits or activation.

## Initial evidence and ambiguity

The dispatch snapshot's issue body limits B2 to immutable row representation and
explicitly forbids activation and baseline/grant changes to hide unwired code.
The supplied repair mandate allows vulture ledger amendments only when actual
scanner findings warrant them; it does not authorize reachability grants.
The assignment is treated as ownership of local validation/repair, not release
of the issue's activation or integration coordination constraints.

Driver logs inspected: check-0 dependency sync succeeded; check-1 ruff passed;
check-2 format passed (3277 files); check-3 reported 311 passed, 3 skipped;
check-4 inventory passed (16467 core nodes). These are driver evidence, not my
executions. The unspecified CI `test: failure` has no failure traceback in those
logs and is not yet attributable to code.

## Executed gate checkpoint

- Named Vulture scan passed: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — 1323 findings
  match 1323 reviewed identities. No Vulture ledger amendment is warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py` failed (exit 1): both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new
  unauthorized unreachable modules and unauthorized dispositions. CI requires
  this gate at `.github/workflows/vulture-ratchet.yml:77`.
- This is not a develop-sync conflict. The local target already equals the
  supplied base; do not fabricate runtime callers or amend reachability policy.
- Prior job result and its committed note describe the same blocker. They are
  historical evidence, not substituted for the checks just executed.
- An attempted descriptive ADR filename was not found; skipped that path.
  Resolve the exact filename before reading the trusted-base policy.

## Focused independent validation

All commands used a 1800-second timeout at the starting source SHA (this round
changes documentation only).

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s` | 314 nodes: 311 passed, 3 skipped in 1.76s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16467 nodes, zero duplicate identities |
| `git diff --check` | PASS |

No tests were added or changed; no inventory delta is needed. The generic CI
`test: failure` was not reproduced by these focused tests. Full integration CI
is UNVERIFIED; do not infer that an unspecified CI failure has been repaired.

## Acceptance audit

Read repository instructions, quality-gates policy, accepted lifecycle
ADR-081226-a66b and trusted-base authority ADR-083126-5e62 (resolved filename:
`ADR-083126-5e62-generated-quality-evidence-is-not-the-judge.md`). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Staged types cannot authorize
their own quality exceptions. No scheduler, store, event or authorization path
was added or changed.

- Frozen/slotted header and exact shared interfaces, strict signed timestamps,
  storage UUID hex, named-field reads, fresh flat encoding, typed failures and
  safe error messages: inspected implementation and passing focused tests.
- V2 snapshot round-trip and binding shape: three-state tests independently
  assert task_id/run_id/acknowledged_at at `test_admission_codec.py:134-137`.
  `admission_identity.py:291-292` enforces receipt equality. This is not a new
  execution of the real SQL constraint.
- Legacy bound/unbound/partial, receipt-only and missing receipt evidence:
  passing contract tests; no inferred identity. Reconciliation: the prerequisite
  binding DTO requires receipt identity, so a bound task/run pair with no receipt
  remains a typed partial disposition rather than fabricating one.
- Header/full-decode separation: passing tests preserve expiry and fingerprint
  despite malformed snapshots or partial binding; mismatched header and unknown
  format are rejected. Inclusive expiry/replacement/409 decisions are explicitly
  not B2 behavior and remain later-consumer evidence.
- Snapshot strictness: passing duplicate/nonobject/bare-nonfinite, numeric-loss,
  Unicode and nested-corruption tests; tags and stored fingerprint are preserved.
  End-to-end original-model fingerprinting, production evidence-json encoding,
  `model_of`/`model_of_json` materialization and Run JSONB object insertion remain
  UNVERIFIED; fixed fingerprint/handwritten tag fixtures cannot prove them.
- Real migrated DB/raw versus production pools: UNVERIFIED this round. All three
  DB cases skip at `test_admission_codec.py:470` for missing required DSNs. No
  migration-chain/downgrade execution, DB session identity, final row/identity
  counts, or authorized principal/Workspace/Project/Graph admission is claimed.
  Stop at the independently reproduced mandatory blocker rather than equate
  historical DB results with current durability proof.
- Reachable production behavior: absent. Source import search finds the codec
  importing identity types and the Vulture whitelist importing its enum only;
  codec lines 50-53 explicitly describe the missing runtime consumer. Passing
  isolated tests does not establish a reachable admission path.
- Stage constraints: source inspection confirms no clock, incoming fingerprint,
  assessment/claim decision, SQL mutation or HTTP/queue mapping in B2. No changes
  to those boundaries this round. Ownership/activation release beyond the local
  assignment remains UNVERIFIED and is not implied by validation.
- Mandatory gates: Vulture/static checks/inventory pass; provenance FAILS.
  No mutation/pre-fix failure claim is made: this round has no code repair.

## Handoff

Verdict: BLOCKED. Changed file: this evidence note only. Preserve existing code,
tests and ledgers. Commit locally; no push, GitHub mutation or integration action.

Blocking paths: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`. The gate rejects both additions
against the exact supplied trusted base. The permitted Vulture repair exception
cannot authorize reachability policy changes or forbidden production activation.
An owner-approved integration resolution consistent with #1845/#1893 is needed;
a separately landed grant also requires reconciliation with #1893's no-grant
constraint. Do not dispatch another unchanged-input validation-only repair:
supply changed trusted-base/consumer evidence or the candidate-qualified failing
CI test traceback first.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker).
Next: owner resolution of integration authority, not a local gate bypass.
