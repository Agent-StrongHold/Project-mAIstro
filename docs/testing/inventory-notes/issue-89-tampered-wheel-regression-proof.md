---
inventory-delta:
  tests/: +0
---

# Issue #89: make the tampered-wheel CLI regression test reach byte verification

## Bounded repair and salvage

Writer job `2554b06c5413437e9b72e4d77bb8b800`, branch `auto-89`, starting
HEAD `c64d51f5d8e31ec85f90560af8b6cd3416b955a2`; assigned develop base
`4f8f40352d13281f217522a351ce47f99a1d1df6`. Initial log/diff/status showed
existing committed promotion repairs and a clean worktree. Preserve those
repairs; do not restart them. Scope is #89's release workflow, promotion/guard
scripts, adjacent tests and this evidence note, not child-lane implementation.

Read repository instructions, accepted release ADR-073126-c4e1 and branch
ADR-095, the supplied immutable dispatch context and prior result. Earlier
attempts could not establish operational release acceptance. Repeating local
schema checks cannot establish that acceptance, even when every check passes.
No driver `check-*.log` files were present in the supplied job directory.
Logs named `check-worker-*.log` there are this round's fresh local evidence,
not driver or hosted-CI evidence.

## Reproduced defect, not a scanner guess

`test_adopt_wheels_fails_closed_on_tampered_bytes` used a synthetic evidence
tree without pinning the CLI's current tree. Thus `cmd_adopt_wheels` rejected
that tree before downloading `dist`, and the test passed without exercising
its named regression. An in-memory probe replaced `verify_dist` with a function
returning `[]` and called the actual test: it still passed, emitting a tree
mismatch. No tracked production file was mutated.

Repair only the test: pin the current tree to the evidence tree, as the
successful-adoption test already does, and assert the downloaded wheel really
contains the tampered bytes. The test still requires a nonzero adoption result
and no output evidence. This makes a bypass of byte verification fail the test
instead of being masked by an unrelated guard. There are no added test cases;
the inventory delta is zero and the cumulative earlier notes are unchanged.

Repeated the same in-memory bypass after repair: adoption returned success and
the test raised `AssertionError` (**mutation killed**). With real verification,
the complete focused battery passed **594 tests**. The production publisher,
release guard, soak requirements, ledgers and execution authorities are
unchanged. This preserves ADR-073126-c4e1 §6's artifact adoption and ADR-095's
protected develop-to-main boundary; no reconciliation changes are needed.

## Fresh validation

All commands below exited zero unless explicitly stated otherwise:

- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py tests/release
  tests/test_check_required_checks.py tests/test_mutation_targets.py -x -q`
  — **594 passed**, both before and after repair. Existing pytest plugin
  deprecation warnings are not test failures.
- `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py
  packages/maistro-registry/tests --confcutdir=tests/tools
  -p no:cacheprovider -q` — **194 passed**.
- Registry workflow commands: `uv run python tools/lint_lifecycle.py`,
  `uv run python -m maistro_registry.cli lint . --strict`,
  `RATCHET_BASE_REV=4f8f40352d13281f217522a351ce47f99a1d1df6 uv run python
  scripts/check-citation-status-provenance.py`,
  `uv run python scripts/check-adr-index.py`,
  `uv run python scripts/generate-spec-ac-defined-index.py` followed by
  `git diff --exit-code docs/specs/README.md`, and
  `uv run python scripts/check-adr-status-language.py` — all pass.
  Strict registry lint reports 447 documents, zero errors/warnings and 199
  existing test-evidence debts, not proof that those debts were discharged.
- `uv run ruff check .` and `uv run ruff format --check .` — pass.
- `uv run python scripts/check-release-consistency.py`,
  `uv run python scripts/check-workflow-inventory.py`,
  `uv run python scripts/check-workflow-write-safety.py` — pass.
- `uv run python scripts/check-suite-inventory.py` — all 21 suites match,
  including 6630 root-suite identities; no baseline edits needed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — **1219 reviewed
  identities = 1219 findings**, zero unclassified/never-allowlist findings.
  The specifically requested gate does not reproduce a ledger failure, so no
  ledger amendment is justified.

## Acceptance: mechanisms are not release execution

The focused battery above executes every test cited here. Workflow inspection
traced candidate builds, adoption, soak gating, publication and attachment;
it is not an external artifact/signature/install run.

| Issue criterion | Executed evidence and remaining disposition |
|---|---|
| RC artifacts only from candidate commit | Real-git `test_record_evidence_freezes_the_candidate_identity` and candidate-only build wiring pass. Actual RC build **UNVERIFIED**. |
| Clean install, real model, security hot path, backup/restore soak | Required-check set and per-check failure tests pass; PyPI dependency test pins successful soak gating before publication. Actual soak **UNVERIFIED**. |
| #860 sustained exact-RC multi-replica workload, crash/restart, admission/fencing, resource pressure, duplicate-work detection | `multi_replica_soak` remains required. Frozen child #860 is open. Actual workload and thresholds **UNVERIFIED**; a schema assertion is not sustained-load evidence. |
| Invariant findings routed before promotion | Both unrouted-finding rejection tests pass. Real findings and their filing/reclassification **UNVERIFIED**; an issue-shaped string does not verify a filed issue. |
| Runtime/code/config changes require new RC and applicable soak | Real-git final-tree drift tests and stale artifact binding tests pass. Deployed runtime/environment configuration and new-soak execution **UNVERIFIED**; config digest/reference is declared, not independently measured by this gate. |
| Final tree/artifacts byte-equivalent to soaked RC | Tree guard, adoption tests and repaired mutation-sensitive tampered-byte test pass. Actual RC/final pair and registry digest equality **UNVERIFIED**. |
| External package/image/signature/install verification | Local release tests pass; no external publishing, pulling, signature verification or clean-machine install executed in this lane: **UNVERIFIED**. |
| Machine-readable evidence tied to exact artifacts/config | Record/adopt/finalize and final-only attachment tests pass. Actual soak-produced record, evidence transport and deployed-config identity **UNVERIFIED**. |

## Handoff and stop condition

**BLOCKED at issue acceptance**, despite the focused test repair. Local `v*`
tag list is empty. The source's cross-lane contract
(`scripts/promote_release.py:49-61`) requires a `soak-evidence` artifact on
the selected RC run; the child's native boolean record is not this schema.
No actual compatible record/transport execution was established here. Do not
weaken the gate to manufacture acceptance.

Assigned base resolves but is not an ancestor of the starting lane HEAD
(`git merge-base --is-ancestor` exits 1). Local `origin/develop` equals that
base; its one additional commit concerns advanced-assurance research. No
merge conflict was observed and no merge/fetch was performed. These results
are for this lane tree, not a merged tree or a hosted queue run.

Next inputs remain program-owned: immutable designated RC/configuration;
compatible exact-RC soak evidence from #860 plus install/model/security/recovery
checks; routing of real findings; authorized single-pipeline promotion and
external verification. No GitHub mutation, release publication, competing
scheduler or authority was introduced.

Progress: checked 1 issue; committed repair is a test correction, not operational
completion. Do not retry static validation as a substitute for those inputs.
