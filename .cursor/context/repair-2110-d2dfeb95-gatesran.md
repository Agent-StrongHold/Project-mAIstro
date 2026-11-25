# Issue #2110 repair round — develop sync + CI-faithful gate re-proof at d2dfeb95 (deep-review round 2)

Frozen scope: PR #2110 only; worktree /home/dev/Git/wt/cr-2110, branch
fix/windows-bootstrap-prerequisite. Starting head c21d94ffbc3d28273f2dab6aff05435df628caa9
(working tree clean at start); declared develop base
f927334a2e3b858a5b734ff94e804bb9c161d7 (M2-B1 #2241, one commit ahead of the
157c3f61 the branch had already merged). Job directory
/home/dev/maistro/jobs/2515eb38ee034d9d93c1100aed36ead2. This record does not
close the issue and is not merge or integration approval.

## What this round resolved

1. **Develop sync (the "mergeable_state=dirty" block).** GitHub's PR head is
   still 6730df2663 with `mergeable=false / mergeable_state=dirty`; the local
   branch already carried the c21d94ffbc merge resolving the 157c3f61
   pin/floor conflicts, and develop then advanced one commit (f927334a2e).
   `comm -12` of the branch's changed-file set against f927334a2e's is empty,
   so this round merged `origin/develop` into the branch conflict-free:
   merge commit **d2dfeb9516** ("merge: origin/develop (f927334a M2-B1
   #2241)"). Post-merge ledger integrity: `git diff --numstat origin/develop
   -- quality/` shows only this branch's intended files
   (ac-state-notes/fix-windows-bootstrap-prerequisite.json +17,
   image-pins.json 4/4); vulture-baseline.json is byte-identical to develop
   (its -2 rows are develop's own commit). `uv sync --locked --extra dev`
   passes, so pyproject/uv.lock stay coherent.
2. **The "ac-state design_coverage floor unreachable locally" prior finding is
   REFUTED, not re-confirmed.** The earlier round measured 40.3661 < floor
   44.4608 and concluded the floor was unreachable on any tree. Re-running CI
   exactly — fresh `pgvector/pgvector:pg18` container (dedicated port 15499),
   `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` pointed at it, `uv run alembic
   upgrade head` (through 068), `age-keygen` present, pytest-timeout +
   maistro-evolve installed, PR event payload at
   /tmp/event2110.json — reproduces the gate faithfully:
   `GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH=/tmp/event2110.json
   uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
   f927334a2e3b9b858a5b734ff94e804bb9c161d7` → **exit 0**: "passing rung
   measured: yes", **design coverage 44.4608% — exactly on the banked
   floor**, 10 debt counters exactly on ceilings, mandate 0 unproven, chain
   mandate 0 new absent links. The earlier 40.3661 was an environment
   artifact (incomplete/unmigrated DB), not a tree property. The prior
   round's claim that this check cannot pass locally is wrong.
3. **Accidental mutation, caught and reverted.** Running
   `scripts/check-ac-state.py --ratchet --compact` locally rewrites
   quality/ac-state-notes/ (compacts 49 notes into _baseline.json). That was
   not intended; every affected file was restored byte-for-byte from HEAD
   via `git show HEAD:<path>` (no destructive git commands used), and
   `git status` / `git diff` were verified empty before continuing. The
   gate's own strictness (notes banked with --run-tests are "not
   comparable" without it) is what exposed the error.

## Executed evidence at merged head d2dfeb9516 (CI-exact arguments unless noted)

- `uv run ruff check .` → pass; `uv run ruff format --check .` → 3569 files
  already formatted.
- `uv run pytest tests/test_get_ps1_wsl_detection.py -q` → **28 passed**
  (pwsh 7.4.6; includes the mocked relaunch harness test).
- `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1
  -PowerShell pwsh` → **all 23 cases passed** + `RESULT relaunch-policy ok`.
- Negative tests fire against the old code: harness against
  `origin/develop:get.ps1` throws `Unexpected elevation arguments`
  (relaunch_policy_harness.ps1:42); the static function-body regression
  finds `-executionpolicy`/`bypass` in both old `Invoke-Elevated` and
  `Register-Resume` bodies.
- Acceptance-state gate (CI-faithful, see §2) → **exit 0** at d2dfeb9516.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1236 reviewed
  identities = 1236 findings, exit 0. No ledger amendment needed: this
  branch deletes no source, so no identity was eliminated.
- `uv run python scripts/check-suite-inventory.py` → 21 suites match,
  exit 0 (branch adds exactly the +3 tests declared in
  docs/testing/inventory-notes/security-windows-policy-prerequisite.md).
- `gitleaks git --redact --log-opts="f927334a2e..d2dfeb9516" .` (v8.30.1, CI
  version) → **no leaks found** over the full 18-commit PR range; the
  fb322ab fingerprints in .gitleaksignore:186-203 are confirmed to target
  the documented fixture shapes (test_attribution.py:462/476 `context_key`
  + `ProducerKind.MUTATION_OPERATOR`; test_task_admission_generation_upgrade.py:46
  synthetic descending-hex `OWNER_TOKEN` fixture) — no credential suppressed.
- `python3 scripts/check-compliance.py` → "compliance registry and
  COMPLIANCE.md are valid", exit 0.
- `uv run pytest packages/maistro-core/tests/fitness -q --timeout=120` →
  39 passed (Architecture fitness job's exact step).
- `uv run python scripts/check-agent-store-writes.py` → pass.
- `uv run python scripts/vendor_bfcl.py --check` → "vendored BFCL tree OK
  (13 artifacts + shim)", exit 0.
- `uv run python scripts/check-image-pins.py` → 9 pins across 10
  Dockerfiles registered, exit 0 (exercises the merge-resolved
  image-pins.json).
- `uv run python scripts/check-backlog-consistency.py` → OK, exit 0.

## Hosted evidence (dispatch-context.json, captured 2026-11-17T04:43Z)

- `commits/6730df2663/check-runs`: every required check-run `completed` with
  `conclusion=success`, including all eight gates named in the stale red
  block (Compliance registry, Container scan + SBOM + cosign — success
  instance alongside a skipped sibling, Coverage gate, Gate C, Quality /
  Acceptance state, Agent store writes, Architecture fitness, BFCL
  provenance). The "RED gates" history predates those repairs.
- PR body and commits carry no fixes/closes/resolves keywords (verified in
  pulls/2110 body and commit subjects) — no issue-closure side effects.

## Residual risks

- Gate C (canonical clean install), Container scan + SBOM + cosign, and the
  Coverage gate are proven by hosted check-runs at 6730df26 plus
  develop-side CI for merged M2-B1 content; not re-run locally (Gate C is a
  full compose build; local docker host is shared with other lanes'
  live compose projects).
- GitHub cannot see the local sync merge (pushing is prohibited for this
  lane); the hosted dirty state clears only when the campaign driver pushes
  the branch. Local merge base for the next round: d2dfeb9516.
