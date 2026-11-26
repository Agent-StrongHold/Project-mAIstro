---
inventory-delta:
  tests/: +0
---

# cr-1532 verifier validation at 15744ed7 — full battery re-proven; sole hosted red remains the external picomatch advisory

Round 3 of PR #1532 (retire body status lines, ADR-092126-a28a) validation.
Exact head `15744ed7e6ffba40cf24115aa751c590479ea496` = last verified round
`6e94972e1f` plus one docs-only inventory note (confirmed: `git diff --stat
6e94972e1f..15744ed7e6` touches only that note). Worktree arrived clean; every
claim below was re-executed in this tree this round.

## Merge-queue state

- `git fetch origin develop` (2026-11-18): develop tip is still
  `d0e8e235a896` and `git merge-base --is-ancestor origin/develop HEAD`
  passes — the branch contains the develop sync; no new conflict.
- Dispatch context `GET pulls/1532` (2026-11-18): `mergeable: true`,
  `mergeable_state: "blocked"` (blocked only by commit statuses), base
  `d0e8e235a8`. Hosted check runs at `26ce281dc22e`: **77 success / 1
  failure**; the sole failure is the `test` job.

## The one hosted red — unchanged, external, no in-tree fix

The `test` job's red step is CI's `npm audit --audit-level=high`
(`ci.yml:702`, canvas frontend): picomatch GHSA-fc5q-39xc-vjpf, first
patched version **null** (re-proven live 2026-11-18 in the prior round).
`git diff origin/develop..HEAD` over the canvas lockfiles is empty — the
finding is inherited from develop tip, not introduced here. Fixing it
requires either an upstream release (none exists) or a gate re-scope by a
policy owner; both are outside this lane's authority. Everything else on
the branch is green locally with CI-exact commands and the hosted run
agrees (77/78).

## Acceptance battery re-executed at 15744ed7 (all exit 0)

CI-exact gate invocations (grep'd from workflows this round):

- `check-adr-status-language.py` (registry.yml:136, no args) → "0 baselined
  body-status contradiction(s), no new ones, none stale".
- `check-adr-status-language-provenance.py` → metric **v2**, empty
  unversioned legacy ledger (explicit zero-tolerance migration), candidate
  `15744ed7e6ff`, 0 contradictions, no candidate-approved expansion.
- `check-ratchet-provenance.py` (vulture-ratchet.yml:77) → **OK: 55 quality
  JSON consumer(s) have explicit provenance**, all ratchets (adr-status-
  language, citation-status, promotion-surface, reachability,
  reachability-dispositions, shell-execution, contract-markers,
  enumerations, lifecycle) equal base with no expansion.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI-exact) → 1236 reviewed identities = 1236 findings
  at candidate `15744ed7e6ff`. No ledger amendment made.
- `check-shipped-surface-truth.py` → matrix complete.
- registry.yml steps: `tools/lint_lifecycle.py` (baseline 0 accepted);
  `check-adr-index.py` (every row agrees); `check-citation-status-
  provenance.py` (0 exceptions); `maistro_registry.cli lint . --strict`
  → 445 files, 0 errors, 0 warnings (199 pre-existing test-evidence debts
  remain visible, not failures).
- `check-contract-markers.py` (every claim evidenced); `check-merge-
  markers.py`; `check-release-consistency.py` (0.9.0 toward 1.0.0);
  `check-suite-inventory.py` (21 suites match).
- `ruff check .` → All checks passed; `ruff format --check .` → 3573 files
  already formatted.
- Targeted suites `tests/test_check_adr_status_language.py` +
  `tests/test_check_adr_status_language_provenance.py` +
  `tests/test_check_adr_index.py` + `tests/test_check_contract_markers.py`
  → **158 passed**.

## Acceptance criteria re-derived against reachable behavior

- Corpus retirement (ADR AC, category 1 = absence): independent scan — not
  via the gate — of all 450 `.md` files under `docs/adr` + `docs/specs`
  for `**Status:**` body lines at ≤3-space indent, bare and list-item
  spellings: **0 hits**.
- Metric v2 contract shared by checker/ledger-writer/adapter, trusted
  mismatch failing through `require_metric_version`: confirmed live in the
  provenance gate output ("metric v2", "empty unversioned legacy ledger
  … migration to v2") and in `check-adr-status-language-provenance.py`
  (`_require_metric_versions`).
- ADR↔evidence linkage: `ADR-092126-a28a` front matter `tests:` names the
  suite; the suite carries `pytest.mark.contract("behavioral")` (line 26)
  including `test_the_corpus_carries_no_body_status_line_at_all` (line 93),
  so a merge reinstating an old revision fails.
- CHANGELOG: literal `(#1532)` owning-PR marker at `CHANGELOG.md:623`
  under `### Changed` inside `## [Unreleased]`.
- ADR-INDEX row present at `docs/adr/ADR-INDEX.md:219`, status Accepted,
  agreeing with front matter (index gate exit 0).

## Residual risks for the integrator (unchanged from prior round)

1. `test` job audit step stays red (and the `gates-ran` rollups with it)
   until upstream ships picomatch > 4.0.7 or a policy owner re-scopes the
   audit gate — merge-time decision, not an in-tree fix.
2. Commit-message auto-close risk in ancestry (`e9aad7356` "Closes #1127,
   #1098, #1056, #1109, #1143"; `0df275362` "(Closes #76 AC-2)") remains —
   `check-closure-targets.py` scans only PR title/body. History rewrite is
   prohibited in this lane.

No tests added or moved this round → `+0`.
