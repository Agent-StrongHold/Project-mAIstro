# Issue #89 — bounded implementation validation (71864dc4)

## Frozen scope

- One item: issue #89, branch `auto-89`, starting HEAD
  `0950278bfe5eef942a897018b7d8dfa67f81c31b`, base
  `7926d9ab4dda6a699a80536c6d03a59eab205725`.
- Existing implementation under review: `.github/workflows/release.yml`,
  `scripts/promote_release.py`, `scripts/release_guard.py`, their adjacent
  `tests/test_promote_release.py` and `tests/test_release_guard.py`, and the
  existing issue-89 inventory/verification notes. Relevant release ADRs and
  consistency gates are context, not new implementation assignments.
- Evidence: supplied job `dispatch-context.json` only. Do not re-fetch issues
  or inspect/modify sibling worktrees. Initial git log/diff/status show prior
  implementation commits and no uncommitted work; nothing needs salvage.
- Job directory has no `check-*.log` files. Validation must be executed here.

## Prior-attempt diagnosis and assumption

The prior result explicitly left every operational release acceptance criterion
unverified: no designated RC or actual release workflow run, no completed exact-RC
soak, and no final promotion. Repeating static checks cannot turn that absence
into acceptance. Preserve the implemented reuse path and test it against the
production workflow; repair only a reproduced defect. Do not invent RC evidence,
lower soak thresholds, run a competing scheduler, or publish artifacts.

This is the writer lane (assignment says implement), so focused implementation
and a local commit are permitted. Actual tag pushes, registry publishing and
release-environment approval remain prohibited. The prior attention request is
not a develop sync conflict: starting HEAD already contains the assigned base.

## Results

Reproduced production-graph defect: `pypi.needs` is `[guard, wheels,
m1-closeout]`, while `adopt-digests` (the only soak gate) runs in `images`,
which has the same needs. Thus PyPI can irreversibly publish the final even
when `images` fails for missing/failed soak evidence or unrouted findings.
Repair: require successful `images` before `pypi`, preserving the single
`release.yml` publisher and existing approval environment. Added dependency
regression test first: targeted pytest failed with `assert 'images' in
['guard', 'wheels', 'm1-closeout']` at `tests/test_promote_release.py:826`.
After the needs repair, `uv run pytest tests/test_promote_release.py
tests/test_release_guard.py -x -q` passed **84 tests** (1.09 s).
`uv run ruff check .` and `uv run ruff format --check .` both passed (3678
files formatted). Inventory delta: `tests/: +1`. Existing pytest plugin
warnings (unset async fixture loop scope and AnyIO CallSpec2 deprecation)
are unrelated to this workflow repair.

First independently solvable repair committed as `684e9fa5ea`.

Second reachable workflow defect in the same frozen file: `github-release`
unconditionally downloads `soak-evidence`, even for RC runs, although its
producer in `images` runs only for finals and the workflow explicitly says the
candidate has no soak evidence yet. An absent artifact is not optional for
`download-artifact`; `if-no-files-found` is an upload-artifact input, not a
skip-missing download input. The RC run cannot finish successfully to become
eligible for `select_rc_run`. Repair only this branch mismatch: download the
soak evidence on finals, fail closed if absent there, skip on RCs. Add a
workflow regression test before editing the branch condition. It failed at
`tests/test_promote_release.py:852` with `None` rather than the finals-only
condition. After repair, `uv run pytest tests/test_promote_release.py
tests/test_release_guard.py -x -q` passed **85 tests** (1.03 s).

Fresh gate results (all exit 0):
- `uv run python scripts/check-image-inventory.py`: 10 Dockerfiles inventoried.
- `uv run python scripts/check-workflow-inventory.py`: 33 workflows dispositioned.
- `uv run python scripts/check-release-consistency.py`: released none, shipping
  0.9.0, working toward 1.0.0.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: 6501 unique
  test identities match baseline plus deltas; new inventory delta is now +2.

Second repair committed as `232008c900`.

Additional fresh validation:
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0 (3678 files).
- `/tmp/actionlint -no-color -oneline -shellcheck /tmp/shellcheck-bin
  .github/workflows/release.yml`: exit 0. Installed actionlint 1.7.7 and
  ShellCheck 0.10.0 match CI's tools/flags; scope is the changed workflow.
- `uv run python scripts/check-promotion-surface.py`: exit 0.
- Validation invocation error: `uv run python scripts/check-no-legacy-paths.py`
  exited 2 because that file does not exist. **Not found; skipped**. This
  unrelated guessed gate was not retried or replaced; it provides no evidence.
  The chained backlog check did not execute in that invocation.
- `git merge-base --is-ancestor 7926d9ab4dda6a699a80536c6d03a59eab205725
  HEAD`: exit 0. No develop sync conflict at the assigned base.
- `git tag -l 'v*'`: empty. `scripts/soak` and `docs/testing/soak`: absent.
- Frozen dispatch PR #1672: open, unmerged, non-draft, mergeable state blocked,
  head `b536bf23e80043484c4bcb7aa271a7c0e6ab775b`. This is snapshot evidence,
  not a fresh claim about GitHub, and does not substitute for a soak run.

Final additional gates:
- `uv run python scripts/check-doc-links.py`: exit 0; 3589 Markdown files,
  zero broken relative links.
- `uv run python scripts/check-backlog-consistency.py`: exit 0; 167 items.
- `git diff --check`: exit 0.

## Acceptance matrix (all eight criteria checked)

The focused pytest command above executed every test named below. Tests prove
local mechanisms, not that a release or sustained production soak happened.

| Criterion | Executed local evidence | Operational disposition |
|---|---|---|
| RC artifacts built only from candidate commit | `test_record_evidence_freezes_the_candidate_identity` uses a real git repo and artifact hashes; `test_shipping_workflow_promotes_rc_artifacts_on_finals` pins candidate-only builds | UNVERIFIED: no RC tag/build evidence supplied or found locally |
| Soak includes clean install, real model, security hot path, backup/restore | `test_required_soak_checks_are_pinned_not_adaptive`, `test_every_required_soak_check_gates_promotion`; new dependency test ensures missing evidence cannot race PyPI publication | UNVERIFIED: no actual install/model/security/recovery soak outputs |
| #860 sustained exact-RC multi-replica workload, crash/restart, fencing, pressure, duplicate detection | `multi_replica_soak` remains required by the schema; frozen child PR is unmerged; no harness or soak evidence in this tree | UNVERIFIED: no designated immutable RC/config or completed representative sustained workload |
| Invariant-invalidating findings routed before promotion | `test_invalidated_invariant_must_be_routed_before_promotion`, `test_adopt_digests_fails_closed_on_unrouted_invariant_findings`; PyPI now waits on this gate | UNVERIFIED: no real load findings/routing evidence; string-reference validation is not independent issue verification |
| Runtime/code/config changes require a new RC and applicable soak | `test_final_cli_rejects_changes_after_the_rc` covers source/config/executable-bit drift; stale wheel/image binding tests reject different artifacts | UNVERIFIED operationally: tracked tree is guarded, but deployed config identity is only a declared digest/reference; actual runtime/environment configuration has not been independently checked |
| Final tag/tree byte-equivalent to soaked RC | Real git-tree guard tests, `test_adopt_wheels_promotes_the_candidate_bytes`, tampered-byte rejection, digest fallthrough wiring | UNVERIFIED: no real RC/final pair exists locally; no registry manifest equality proof |
| External package/image/signature/install verification succeeds | Workflow parses/lints; wheel reuse and required dependency behavior tested locally | UNVERIFIED: no PyPI/GHCR/cosign/install execution; maintainer publishing/approval setup not independently established |
| Machine-readable evidence tied to exact artifact/config | Record/adopt/finalize CLI tests bind wheel SHA256/image maps and validate declared config digest; finals-only required attachment regression test | UNVERIFIED: no real soak-produced record, deployed-config verification, or exercised evidence transport/attachment |

## Handoff and stop condition

**BLOCKED**, not merge/release approval. Both reproduced workflow defects are
repaired and locally committed. No new scheduler, Goal/event store, authorization
path, ledger/grant edit, or GitHub mutation was introduced. ADR-073126-c4e1 §6
requires adopting the last RC's tested artifacts, not rebuilding; ADR-095 keeps
`develop -> main` as the sole promotion boundary. These repairs preserve both.

Required next inputs are program-owned: designate immutable RC artifacts and a
runtime/configuration manifest; complete the exact-RC #860 sustained soak plus
install/model/security/recovery checks; route real findings; exercise evidence
transport and the approved single shipping workflow; verify external installs,
signatures and RC/final byte identity. A local dry run cannot satisfy those
criteria. Do not treat another static verification pass as a release soak.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, repairs_committed: 2,
next: designated RC/config + completed soak + authorized release execution}`.
The single error was the missing, unrelated gate invocation recorded above;
no observed implementation test or relevant gate remains failing. No new
implementation items will be started.
