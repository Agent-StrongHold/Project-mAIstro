# #2059 repair round — exact-head validation log (2026-11-25, round 3)

Lane CR2059, job `1e857502e6354bab9969170f65f2a66e`. Start head `e976a68477cc`
(= PR #2059 head as dispatched); end head `f20ef51abfb5` after this round's
required develop sync. Supersedes
`.cursor/context/2059-repair-a7be1d3-validation.md` for everything after
`e976a68477`. No production code changed this round — every gate below was
re-proven at the round's end head rather than inherited.

## Block resolution: develop sync (round 3 occurrence)

The dispatched brief carried the standing block "develop sync conflict …
resolve before verification". `git fetch origin` showed `origin/develop` moved
past the round-2 base `80c837d578` to `bd96877ed8` ("Decision: Freeze
exact-effect payload bytes (#2264)", one commit, 35 files: gitleaks allowlist,
SPEC-101826-1836 doc, ac-state bank, 1836 repair notes, frontend
package-lock). Merged into `fix/vulture-single-owner-1357`:

- `git merge origin/develop` → **exit 0, 'ort' strategy, zero conflicts**.
  The one potentially conflicting path, `tests/test_distribution_contract.py`,
  carried the **byte-identical change on both sides** (both `1bcc431d8d →
  b09d14fad7`), which git auto-resolves — verified by comparing
  `git diff 80c837d578..origin/develop` and `git diff 80c837d578..e976a684`
  for that path before merging.
- Post-merge ledger integrity (AGENTS.md multiset rule):
  `git diff --numstat origin/develop -- quality/` → only
  `quality/ac-state-notes/fix-vulture-single-owner-1357.json` (17+/0-);
  `quality/vulture-baseline.json` byte-identical to `origin/develop`
  (dict-compare `==` True; no row loss, no row gain).
- End head `f20ef51abfb5`; tree clean; `origin/develop` fully contained.

## CI-repair instruction: exact-debt-ledger — executed, no-op

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (byte-identical to the
quality.yml:1608 and vulture-ratchet.yml:82 invocations) at end head:
**exit 0**, 1221 reviewed identities → 1221 findings, `unclassified: 0`,
`never_allowlist: 0`, base `bd96877ed8cc`, candidate `f20ef51abfb5`.
**No unbanked identities exist, so no ledger amendment was required** — the
permitted exact-debt-ledger exception stays unused this round; the change
eliminates no identities (workflow-conditional only).

## Hosted exact-head evidence (read-only API, no mutations)

Check-run rollup on dispatched head `e976a68477` (fetched live via
`gh api …/commits/e976a684…/check-runs?per_page=100`, 84 runs): **17 success,
64 queued, 2 in_progress, 1 skipped** (Container scan, path-filtered — expected
exclusion, not a failure), **zero failures**. Among the successes, the two
gates this issue touches:

- `exact-debt-ledger` → success (completed 2026-11-25T12:00:52Z) — the vulture
  per-identity ledger gate is green on the exact dispatched head.
- `workflow-lint` → success (completed 2026-11-25T12:04:21Z) — resolves the
  prior round's "actionlint UNVERIFIED" finding hosted-side.

Also green on the dispatched head: CodeQL (3 analyzers), DevSkim, Mutation
gate, block, pr-base, lint-and-type-check, formal-conformance,
cross-product-parity, sandbox-conformance, Gate C, ADR/spec front-matter.
The earlier "RED gates" list (Coverage, Acceptance state, Agent store writes,
…) reflects an older evaluation; nothing in the current rollup is red.

The remaining 64 queued / 2 in_progress legs are hosted work not yet executed
at capture time; they are pending, not failing.

## Local actionlint replay (CI-exact toolchain)

Replayed ci.yml's gate with CI's exact pinned tools and arguments
(`/tmp/actionlint -no-color -oneline -shellcheck /tmp/shellcheck-bin`):
actionlint 1.7.7 + shellcheck 0.10.0 downloaded to /tmp (never into the tree)
→ **exit 0** over the whole workflow set at end head.

## Local replays at end head f20ef51abfb5

- `uv sync --locked --extra dev` → OK; `uv run ruff check .` → "All checks
  passed!"; `uv run ruff format --check .` → 3659 files already formatted.
- `uv run pytest tests/test_ci_vulture_ownership.py
  tests/test_gates_ran_merge_group_scope.py tests/test_check_gates_ran.py
  tests/test_check_required_checks.py -q` → **232 passed** (ownership
  partition incl. negative controls unchanged).
- `uv run pytest tests/test_devskim_scan_scope.py
  tests/test_distribution_contract.py
  tests/test_docker_cli_vendored_advisory_floors.py
  tests/test_cpython_base_grype_floor.py
  tests/test_temporalio_bridge_zip_floor.py
  tests/test_restore_oracle_characterization.py
  tests/test_restore_oracle_readiness_gate.py -q` → **66 passed**.
- Script gates (all exit 0): check-required-checks (79 PR checks match
  REQUIRED-CHECKS.md), check-backlog-consistency (167 items),
  check-ratchet-provenance (ten sub-ratchets incl. vulture provenance, 0
  candidate-approved expansion; 55 quality JSON consumers have provenance),
  check-shipped-surface-truth (matrix complete), check-suite-inventory
  (21 suites match, delta 0 — the merge nets zero new/changed test files:
  test_distribution_contract.py is identical on both sides), check-adr-index,
  check-adr-status-language, check-adr-status-language-provenance,
  check-contract-markers, check-doc-links (new SPEC-101826-1836 doc from
  develop validated), check-branch-protection (21 develop / 35 main rules),
  check-workflow-write-safety (33 workflows), check-uv-setup (74 steps).

## Change-scope invariants re-proven at end head

- `git diff origin/develop..HEAD -- .github/` → exactly one file:
  `.github/workflows/quality.yml`, 9+/2− (the topic-push-only `if:` gate +
  ownership comment). Sole semantic workflow change preserved.
- `git log origin/develop..HEAD` messages scanned for
  `(fixes|closes|resolves) #N` → none (grep exit 1). No premature closure.

## Residual (outside worker mutation scope — handoff, not repair failures)

1. **PR body figure stale**: body claims "1,328 reviewed identities = 1,328
   findings"; every replay at both heads this round measures **1221 = 1221**.
   Editing the PR body is a GitHub mutation this lane is prohibited from
   performing — must be refreshed by the integrator before merge.
2. **PR body/draft drift**: body says "Keep draft pending exact-head hosted
   checks" while the PR is draft:false; same prohibition applies.
3. **Hosted CI for the new head `f20ef51abfb5`**: the merge necessarily moves
   the PR head past `e976a68477` (whose hosted state is 17 green / 0 red /
   66 pending). The queued/in_progress legs and a fresh exact-head rollup on
   `f20ef51abfb5` can only materialize after the next push, which this lane
   cannot perform. Local replay of every locally-runnable gate is green at
   the new head.

Round-2's full CI-shape reproduction of Quality / Acceptance state (pg18
pgvector, `--mandate 80c837d578`) was performed at the immediate parent
`a7be1d3a95`; this round's delta to it is develop's docs/allowlist commit plus
a docs-only round-2 note — no code, ledger, or workflow-semantic delta — and
the round-3 ledger/provenance/contract/ADR gates above re-cover the touched
paths.

No test files were added or changed this round → no inventory delta required
(check-suite-inventory: 21 suites, delta 0). Tree left clean at `f20ef51abfb5`
plus this note.
