# REPAIR-NOTES-1837 — verifier round 5: independent re-run at final head 1e8fc87f

Lane L1837 (issue #1837, Decision: Select WebAuthn verification adapter).
This round re-derived acceptance from the issue text and re-executed every
gate at the exact assigned head `1e8fc87ffd9293c0e067603b61778f20559367a9`
(worktree clean; no git state changed by this round except this note).
Nothing was assumed from round 4 (REPAIR-NOTES-1837-verifier-round4-ae582a6b.md).

## Environment correction that matters

The driver's pre-run `uv sync` had **uninstalled** `maistro-bootstrap==0.9.0`
(job check-0.log). Both interpreters were re-synced before any gate was
trusted: `uv sync --locked --extra dev` then the CI `test` job's exact
`uv sync --locked --extra dev --extra bootstrap`. The suite-inventory gate was
first run under bare `python3` (system 3.14, no pydantic) and failed the two
bare-python hive recipes with INTERNALERROR — an interpreter gap, not drift;
re-run under the venv interpreter (the gate's `sys.executable` semantics) it
is green. Recorded because "a missing module and a real violation both exit 1".

## Executed at this exact head (all rc 0 unless stated)

Issue deterministic acceptance:

- `uv run python scripts/check-adr-status-language.py && git diff --check`
  → 0 contradictions, none stale; diff clean.
- `scripts/check-adr-index.py` → every row agrees with front matter
  (ADR-101826-c3f1 v1 Proposed at docs/adr/ADR-INDEX.md:234).
- `scripts/check-contract-markers.py` → OK (ADR declares no kinds/tests by
  design; see the ADR front-matter comment and "Acceptance boundary").

CI `test` job steps, workflow-exact env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):

- `uv run pytest tests/ --ignore=tests/tools/registry -q --tb=short`
  → **5802 passed, 139 skipped** in 403.7s.
- `packages/maistro-server/tests` 646 passed, 10 skipped;
  `packages/maistro-turing/tests` 225; `packages/maistro-turing/backend/tests`
  125; `packages/maistro-design/tests` 662 passed, 1 skipped;
  `packages/maistro-ext-harness/tests` 273; `packages/maistro-ext-sdk/tests` 147.
- `packages/hive-conductor/backend/tests` (as the cross-suite step invokes it)
  4062 passed, 29 skipped in 279.8s. CI additionally runs this suite under
  bare system python with `uv pip install --system -r …/requirements.txt`;
  this box's system python is 3.14 and PEP-668 externally managed, so the
  venv invocation is the local equivalent (same node set; the inventory gate
  pins the count).
- `tests/test_check_image_lock_reconciliation.py` → 76 passed (branch-owned
  test file).
- `python scripts/check-suite-inventory.py` (venv interpreter) → 21/21 suites
  match, 34693 unique identities, 0 duplicates.
- `python scripts/check-test-duplicates.py` → 1734 files, 0 identical groups.

Quality ratchets (CI-exact arguments):

- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1256 reviewed == 1256 findings, base
  4019249e8.
- `gitleaks git --redact --log-opts="4019249e8..HEAD" .` with the
  security.yml-pinned gitleaks 8.30.1 → no leaks found, 19 commits scanned
  (executes the `.gitleaksignore` fingerprint for the ADR fixture line).
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .`
  → 3529 files already formatted.

## Deliverable checks against #1837's owned contract

- ADR-101826-c3f1 read in full: library source (duo-labs/py_webauthn),
  version pin 3.0.1 + wheel digest, permitted algorithms (ES256 required;
  EdDSA/RS256 permitted; PSS/SHA-1/ML-DSA excluded), required flags
  (UP+UV always; sign counter; BE/BS provenance-only), valid registration +
  assertion vectors, I1–I6 refusals, dependency owner @BlakeMatthews-dev,
  exact module path `packages/maistro-core/src/maistro/capabilities/webauthn.py`,
  ADR-039 §3 maintainer-signal rationale + py-webauthn typosquat note.
- No implementation by this gate: `webauthn` appears 0 times in `uv.lock`;
  the seam module does not exist; diff vs base 4019249e8 is docs, notes,
  `.gitleaksignore`, and the one root test file only.
- ADR cryptography claim matches `packages/maistro-core/pyproject.toml:28`
  (`cryptography>=50.0.0,<51`).
- Stale-note repair from c1836f646 confirmed: `auto-1837-5646.md` is gone and
  no live reference remains outside REPAIR-NOTES narratives; inventory green.
- Closure keywords: PR #2268 body uses "Refs #1837" only; no
  fixes/closes/resolves in any commit message body on the range.

## CI "test: failure" label — disposition

The captured check-runs for head 1e8fc87f are **all `queued`**: no completed
CI run exists at this head. The label traces to the merge-queue lane's
provider timeout (zai/glm-5.3-flash), documented in round 4, not to repo
content. Every pytest step of the `test` job passes locally at this head
(above). No repair is warranted; this note is the fix evidence.

## Unresolved items (recorded, not repairable by this lane)

1. **Cross-suite leakage step not seen green locally.** The CI step
   `pytest tests/ packages/hive-conductor/backend/tests
   packages/maistro-design/tests -q --timeout=60` produced 10206 passed /
   161 skipped / **421 errors** in one local run (771s). All 421 are in
   `packages/hive-conductor/backend/tests` and `packages/maistro-design/tests`
   — trees with **zero** branch diff; nothing in `tests/` errored, including
   the branch-owned file, which also passes with a hive prefix
   (`tests/test_check_image_lock_reconciliation.py +
   hive test_workspaces.py`: 148 passed). Each constituent suite passes
   standalone in the same env, with `--timeout=60`, and fd exhaustion is
   excluded (`ulimit -n` 1048576). The trigger requires the full tests/
   prefix and was not isolated within this round's probe budget. Because CI
   has never executed at this head, there is no green/red CI datum to compare.
   Verdict: not attributable to branch content from available evidence, but
   the step is honestly UNVERIFIED-locally rather than claimed.
2. **Owner acceptance of ADR-101826-c3f1.** Reserved by #1837 to
   @BlakeMatthews-dev (or a designated architecture/security reviewer). The
   ADR stays `Proposed`, the dependency stays uninstalled, and #1837 stays
   visibly open until that human record exists. No command or lane can
   grant it; nothing here claims to.
