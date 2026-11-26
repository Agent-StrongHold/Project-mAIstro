# Repair #1792 @ b445c9a8eae7 (branch auto-1792) — 2026-10-20

## Verdict: MERGE-READY (writer handoff only — never integration approval)

Nothing to repair in code. The only substantive prior finding (the inventory
note's collected-test count) was already corrected by `b445c9a8e`, the assigned
starting head. This round re-derives every acceptance criterion firsthand at
that head; every number below was measured here, not carried over. No source,
test, ledger, gate or workflow file was edited — this file is the round's only
artifact.

Assigned base `e20e9f52e` (develop tip at dispatch); CI trusted base
`fad17a87c` (merge-base with develop).

## The block this round inherited

`recovery budget exhausted: launch/preflight: gh exited 1: gh: API rate limit
exceeded ... (HTTP 403)`. That is the driver's own `gh` preflight, not a gate:
the merge-queue evaluation never reached CI. The gate list itself was `green`.
No develop-sync conflict was recorded, so per the lane brief no merge was owed.

### Develop topology, resolved by plain git (no `gh` call)

- `git merge-base --all HEAD origin/develop` returns **two** commits —
  `fad17a87c` (2026-10-19) and `31d891a56` (2026-10-04): the histories are
  criss-crossed, so git's recursive merge synthesises a virtual ancestor.
- Develop's *net* content delta from `fad17a87c` is 5 files, #1851's leaf:
  `maistro/runs/admission_identity.py` (+520), its root test module (+660),
  two `.cursor/context` notes, and `quality/vulture-baseline.json` (+5 banked
  `admission_identity` enum identities). Zero overlap with this branch's 9
  surfaces; `quality/radon-baseline.json` and `quality/ratchet-authorizations.json`
  are byte-identical between `fad17a87c` and `origin/develop`.
- GitHub reports the PR `mergeable: true`, `mergeable_state: behind`
  (dispatch capture 2026-10-20T06:07Z) with a test-merge commit recorded.
  The branch is behind, not conflicting, and "behind" is what the merge queue
  itself resolves.
- A *local* `git merge-tree --write-tree HEAD origin/develop` reports 3 content
  conflicts (`.github/workflows/quality.yml`, `fail_first.py`,
  `quality/ratchet-authorizations.json`). All three are virtual-base artifacts:
  `git ls-tree` of the merge result shows stage 3 == the `fad17a87c` blob for
  every one of them, i.e. develop did not move those files relative to the base.
  Resolution, should a later round be asked to sync develop anyway: keep ours
  in all three regions (the refactor and the 5-row/9-grant withdrawal).
- **Decision: do not merge develop this round.** It would import #1851's leaf
  and its 5 vulture identities for no gain, and the AGENTS.md hazard on
  `quality/*.json` merges is exactly the merge this branch has to survive
  without losing rows. Recorded as an assumption, not a spiral: if a future
  evaluation shows a real develop conflict, the recipe above is mechanical.

## Acceptance evidence (all executed at b445c9a8e)

### 1. Per-block complexity, `radon cc` 6.0.1, measured at HEAD and at the trusted base

| block | at `fad17a87c` | at HEAD | rank |
|---|---|---|---|
| `fail_first.py::_has_related_failure` | C (14) | **B (9)** | ≤ B ✓ |
| `fail_first.py::collect_fail_first_evidence` | C (12) | **B (6)** | ≤ B ✓ |
| `fail_first.py::fail_first_gate` | C (11) | **B (6)** | ≤ B ✓ |
| `candidate_fitness.py::evaluate_candidate` | C (20) | **B (8)** | ≤ B ✓ |
| `candidate_fitness.py::compose_scorecard` | D (23) | **A (2)** | ≤ B ✓ |
| `local_loop.py::LocalRsiLoop._fitness_decision` | B (10) | B (10) | ✓ |

`_fitness_decision` needed no code change and got none:
`git diff fad17a87c..HEAD -- packages/maistro-rsi/src/maistro_rsi/local_loop.py`
is 0 lines, and the base itself measures B (10), so there was no ledger row to
withdraw and none was invented.

No helper took the complexity instead: every extracted function is A except
`_objective_scores` B (6), `_work_scores` B (6), `_baseline_derived` B (8);
none is C/D.

### 2. CI-exact gates (true exit codes, read from output not status)

- `uv run xenon --max-absolute B --max-modules B --max-average A -i third_party
  <the ten workflow roots>` → block violations **129 == `XENON_BASELINE` 129**
  (quality.yml:1356), average 0, module 0, and none of the six blocks or their
  helpers appears in `xenon.log`. The move 134 → 129 is a **tightening**.
- `uv run python scripts/check-radon-baseline.py` → **rc=0**; 134 reviewed →
  129 current, new 0, regressed 0, stale 5 (the 5 pruned rows).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **rc=0**, 1321 reviewed
  identities → 1321 findings, `unclassified: 0`, `never_allowlist: 0`. The
  CI-repair vulture-ledger clause of this round is therefore **vacuous**: no
  unbanked identity, nothing genuinely dead, nothing to amend.
- `uv run python scripts/check-ratchet-provenance.py` → **rc=0** (reachability
  168→168 of 1416, shell 3→3, contract-markers 358→358, lifecycle 0→0, 53 JSON
  consumers have provenance).
- `uv run python scripts/check-suite-inventory.py` → **rc=0**; 21 suites,
  32310 node IDs, `packages/maistro-rsi/tests: 1726` (786 recorded + the +4
  delta in this change's note).
- `uv run ruff check .` → rc=0; `uv run ruff format --check .` → rc=0,
  3360 files formatted.
- `uv run pytest tests/test_complexity_gate_scope.py -q` → 5 passed (pins
  `XENON_BASELINE` to the ledger length). `uv run pytest
  tests/test_ci_quality_split.py -q` → 96 passed (re-pinned obligation digest).

### 3. Suites

- `uv run pytest packages/maistro-rsi/tests -x -q -p no:randomly` →
  **1722 passed, 4 skipped** (1726 collected == inventory).
- `test_fail_first.py` `--collect-only` → **45 tests**, i.e. 42 pre-existing +
  the 3 added in-file; the 4th addition lives in `test_candidate_fitness.py`.
  The note's "42 of the file's 45" wording is now true — the prior finding is
  closed at this head.
- Diff-coverage gate, reproduced with this change's own producer
  (`coverage run --branch --source=packages/maistro-rsi/src/maistro_rsi -m
  pytest packages/maistro-rsi/tests`): `scripts/check-diff-coverage.py
  coverage.xml --base fad17a87c…` → **rc=0**; 2 changed files scored, 2 test
  files exempt. Whole-file coverage 96% (`candidate_fitness.py`) / 98%
  (`fail_first.py`). The 4-changed-arcs-at-75% failure that `ca1a2d59c` fixed
  does not reproduce.

### 4. Behaviour preservation

- Every string literal of length > 3 containing a space was compared AST-wise
  between `fad17a87c` and HEAD for both modules: **0 base-only literals**.
  All refusal reasons, gate pass texts, refactor/characterization/
  documentation verdicts and detail keys survive verbatim; the only new
  literals are helper docstrings. `_REJECTION_TEXT` is untouched.
- Gate order and score order are preserved by construction
  (`_scorecard_gates` returns the same list in the same order;
  `_scorecard_scores` = red_green, scenarios, new_test, ladder, objectives,
  work) and the suite that asserts scorecard/promotion matrices passes.
- The one ordering change is `new_source_lines` moving from after
  `_uncollectable_tests` to `_baseline_derived` (before it): it is a
  `git diff <base> -- <rel>` probe over the base revision and the working
  tree, and no step between the two call sites writes a tracked source file
  (`_mean_quality`/`_mean_assertion`/`_syntax_check`/`_uncollectable_tests`
  only read or run tools). Same value both ways.
- `_run_base_probes`: the probe try/`except (OSError, SubprocessError)`/
  `return None` and the `finally` restore are the original semantics, moved
  whole; the except branch is still uncovered (lines 402-403) exactly as it
  was at the base.

### 5. The 4 added tests actually fail against the regressions they name

Mutation-probed in place and reverted byte-identically (`sha1sum -c` verified
after each) — no revert used a destructive git command:

| mutation | result |
|---|---|
| `_test_module_imports` fallback → `set()` **and** stem match → `False` | 3 failed, incl. `test_related_detection_falls_back_to_textual_imports_when_the_test_file_is_malformed` (crash: `SyntaxError`) |
| fallback → `set()` only | test still passes — the stem match covers malformed source on its own |
| stem match → `False` only | only the pre-existing "used without an import" test fails; the malformed test passes via the fallback |
| `except (OSError, RuntimeError): continue` removed in `_has_related_failure` | `test_related_detection_skips_unreadable_test_files…` fails (`OSError`) |
| `_resolve_evidence_shas` returns SHAs for an unresolvable ref | `test_probe_returns_missing_evidence_when_the_base_ref_is_unresolvable` fails |
| `_scorecard_scores` drops the `if nt is not None` append | `test_net_new_test_signal_fires_when_coverage_rises` fails |

Honest caveat for a future round: the malformed-evidence test's docstring says
the *textual import fallback* is what matches, and rows 2 and 3 show the two
attribution paths are each sufficient — any textual import of a changed module
contains that module's file stem as a word, so the fallback cannot be isolated
from the stem check. The test pins the composite behaviour (row 1) and the
docstring overstates the mechanism. Left unedited: the behaviour is what the
issue asks to preserve, and a docstring-only edit is cosmetic.

### 6. Ledger discipline (issue criterion 5)

- `quality/radon-baseline.json`: 134 → 129 entries, **removed exactly the 5
  scoped rows, none added, none modified**.
- `quality/ratchet-authorizations.json`: `radon` section 92 → 83, removed
  exactly the 9 scoped grants (`compose_scorecard@21/@23`,
  `evaluate_candidate@25/@30`, `_fitness_decision@16/@19`,
  `_has_related_failure@14`, `collect_fail_first_evidence@12`,
  `fail_first_gate@11`); every other section (`ac-state`, `contract-markers`,
  `execution-lifecycles`, `model-egress`, `principal-identity`,
  `promotion-surface`, `reachability`, `route-permissions`, `vulture`,
  `wiring-reads`) is **identical to the base**. Unrelated debt preserved;
  removing a grant for a block that no longer exists tightens, never relaxes.

## Residual risks

1. Develop is 478 commits / `behind`; a future sync must resolve the 3 virtual
   -base conflicts by keeping ours and must not drop `quality/*.json` rows
   (compare `git diff --numstat fad17a87c origin/develop -- quality/` before
   trusting the merge).
2. `_run_base_probes`' `except` branch (fail_first.py:402-403) remains
   uncovered — pre-existing, moved not introduced; a test that makes checkout
   or probe raise would close it.
3. The merge-queue block this round inherited was driver infrastructure
   (`gh` 403 rate limit), which no branch change can fix.

## Note for the verifier

The job directory contains no `check-*.log`: the driver's deterministic checks
did not run for this job (`manifest.json` carries `"checks": []`). Every figure
above is from a command executed in this worktree at b445c9a8e.
