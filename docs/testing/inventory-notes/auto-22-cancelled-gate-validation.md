# auto-22 CI-repair round — local execution evidence for the cancelled gates

At head `24c999ba684c`, the merge-queue evaluation recorded five **cancelled**
check runs (`SAST (bandit + semgrep + gitleaks)`, `security`, `workflow-lint`,
`integration-scope`, `formal-conformance`) and a failing `gates-ran` commit
status. `scripts/check-gates-ran.py` run locally against the captured
check-run snapshot reproduces the verdict and names the cause precisely:
the five cancelled jobs sit under "present but did not execute to a verdict"
— i.e. concurrency supersession on the PR, **not** a code verdict. A cancelled
run carries no finding about the candidate, so this round proves the gates on
the candidate tree locally with CI's exact arguments instead of guessing.

## Gate evidence (all exit 0 against `24c999ba684c`, base `c560d4cca`)

- SAST bandit: `uv run bandit -r packages/maistro-core/src
  packages/hive-conductor/backend packages/maistro-server/src -ll
  --confidence-level=medium` → `bandit Medium+ count: 0 (strict gate)`.
- SAST semgrep: `uvx semgrep --metrics off --config tools/semgrep/maistro-rules.yaml
  --config p/security-audit --config p/owasp-top-ten --config p/secrets
  --exclude 'packages/hive-conductor/eval' --exclude 'packages/hive-conductor/cage'
  --error packages/ tests/` → 364 rules, 2038 files, **0 findings**.
- SAST gitleaks: `gitleaks git --redact
  --log-opts="c560d4cca..24c999ba"` → `no leaks found` (6 commits, 1.71 MB).
- workflow-lint: `actionlint -no-color -oneline -shellcheck <shellcheck>`
  (v1.7.7) exit 0; `shellcheck --severity=warning tools/*.sh` and
  `install.sh get.sh` exit 0; `check-install-functions.py`,
  `check-required-checks.py` (33 PR checks match REQUIRED-CHECKS.md),
  `node --test tests/ci/integration-scope.test.cjs` (0 fail) all exit 0.
- integration-scope: `ci_merge_group_scope.py --json` resolves all seven
  specialized scopes true; `check-integration-scope.py --required-json` emits
  the expected required-name list.
- formal-conformance policy steps: `check-m1-convergence-freeze.py --base
  c560d4cca` → "no unapproved new architecture island";
  `check-formal-oracle-independence.py --base c560d4cca` → OK. The
  Postgres-backed `pytest formal/models/` step is **not locally executable**
  (no reachable docker daemon in this worktree); the branch diff vs the base
  is docs-only plus a `pyproject.toml` comment, so the models' inputs are
  byte-identical to the base — recorded as unverified-locally rather than
  passed.
- exact-debt-ledger: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1342 reviewed identities
  = 1342 findings, ratchet green, no unbanked identities. No ledger amendment
  needed.
- ruff: `ruff check .` and `ruff format --check .` both clean (2982 files).

## Epic test surface at this head

`uv run pytest packages/maistro-core/tests/memory/learnings/
packages/maistro-core/tests/persistence/test_sqlite_learning_lifecycle.py
packages/maistro-core/tests/persistence/test_sqlite_learning_stage.py -q`
→ **301 passed**; `test_pg_learning_stage.py` (fake in-process asyncpg) →
**7 passed**. The M4-B stage ladder, Gauntlet, lifecycle and store suites are
green on the exact candidate head.

## Why no tree change

The merged branch's diff against the develop base contains no runtime Python:
five inventory notes and a comment-only `pyproject.toml` edit (ruff `external`
documentation). Every cancelled gate that reads code was re-proven on the
tree as-is; the cancellation itself resolves when CI re-executes on the next
queue evaluation. Nothing to repair in the tree; this note is the round's
record.
