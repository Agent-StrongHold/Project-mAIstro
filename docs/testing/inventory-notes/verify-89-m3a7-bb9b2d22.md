---
inventory-delta:
  tests/: +0
---

# verify-89-m3a7 — repair round at bb9b2d2200 (develop sync to assigned base + gate reproof + transport-seam disposition)

Round record for issue #89 (M3-A7, parent epic #19) on branch `auto-89`,
worktree `/home/dev/Git/wt/auto-89`. Starting head `d9bff8212565` (clean,
nothing to salvage), assigned develop base `73610a225d98` (= local
`origin/develop`). Named CI state for this round: "Validate ADR/spec
front-matter: queued"; prior block: worker-reported BLOCKED. No
`check-*.log` files existed in the job directory, so every gate below was
executed fresh with CI's exact arguments — prior claims were not trusted.

## What this round changed

1. **Develop sync (branch was 1 behind its assigned base).** Merged
   `origin/develop` (`73610a225d98`, M4-G harness benchmarks, PR #2528) into
   `auto-89` as `bb9b2d2200`: disjoint file sets
   (`packages/maistro-evolve/**`, `tests/fixtures/ci_quality_obligations.json`
   on develop only; no branch-side commit touched the fixture since merge base
   `c707949a0a`), zero conflicts. `quality/*.json` row counts verified
   identical to `origin/develop` after the merge (vulture-baseline 1369 lines,
   lifecycle-baseline 3 — the multiset/lost-row check from AGENTS.md).

2. **"Validate ADR/spec front-matter" (registry.yml), all 7 steps at the
   merged head, CI's exact arguments — all green.** Registry/lifecycle pytest
   `tests/tools/registry/ tests/tools/test_lint_lifecycle.py
   packages/maistro-registry/tests --confcutdir=tests/tools -p
   no:cacheprovider` — **194 passed**; `tools/lint_lifecycle.py` ✓ baseline 0;
   `maistro_registry.cli lint . --strict` — 447 files, 0 errors / 0 warnings
   (199 baselined test-evidence debts);
   `RATCHET_BASE_REV=origin/develop scripts/check-citation-status-provenance.py`
   — OK, 0 exceptions, no candidate-approved expansion (base 73610a225d98,
   candidate bb9b2d2200);
   `scripts/check-adr-index.py` OK; `generate-spec-ac-defined-index.py` +
   `git diff --exit-code docs/specs/README.md` — zero diff (57 AC Defined
   specs); `scripts/check-adr-status-language.py` — ok, 0 baselined
   contradictions. "Queued" did not reproduce as a failure: it is an
   in-flight scheduling state, not a source defect (same conclusion as the
   9f3eda2e round, now re-proven at the new head).

3. **Coverage gate, diff portion, at the merged head.** Root-producer shape
   `uv run coverage run --branch --source=scripts -m pytest
   tests/test_promote_release.py tests/test_release_guard.py
   tests/test_check_release_consistency.py tests/test_check_compliance.py
   tests/test_check_license_inventory.py tests/test_release_publish_metadata.py
   tests/test_soak_compose_pressure.py tests/release/
   tests/test_verify_wheel_imports.py --timeout=60 -q` — **703 passed**;
   `coverage xml` piped through `scripts/check-diff-coverage.py coverage.xml
   --base origin/develop` (the base the next PR/merge-queue evaluation
   scores; merge-base is exactly `73610a225d98`) — **"ok: every measured file
   this change touches is at or above 90% lines / 80% branch arcs"**, exit 0.
   The +20 fail-closed seam tests from `issue-89-diff-coverage-repair.md`
   remain the repair; no new coverage debt.

4. **Mutation probe re-proven at the merged head (method corrected).** The
   9f3eda2e round's process-local probe was re-run with a `-p` pytest plugin
   whose `@pytest.hookimpl(wrapper=True)` `pytest_runtest_call` swaps live
   `verify_dist` (the fixture-loaded `_promote_release` module instance) for
   an accept-any-bytes mutant, restoring it after the call:
   `PYTHONPATH=/tmp pytest
   tests/test_promote_release.py::test_adopt_wheels_fails_closed_on_tampered_bytes
   -p probe_plugin_89 -q` — **1 failed (`assert 0 == 1`), exit 1** while the
   mutant is live = byte verification is genuinely exercised; control run
   without the plugin — **1 passed, exit 0**. (Diagnostic first: an
   undecorated generator hook silently never ran under this pytest, which is
   why the hook is explicitly `wrapper=True`.)

5. **Static battery at the merged head — all green.** `ruff check .` ("All
   checks passed!") and `ruff format --check .` (3710 files);
   `scripts/check-suite-inventory.py` — all 21 suites match, no
   byte-identical duplicates; `scripts/check-release-consistency.py`,
   `scripts/check-workflow-inventory.py` (33 workflows),
   `scripts/check-workflow-write-safety.py` (33), `scripts/check-doc-links.py`
   (every relative link resolves), `scripts/check-backlog-consistency.py`
   (167 items); CI-exact vulture
   `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
   '*/third_party/*'` — 1218 reviewed identities = 1218 findings, base
   73610a225d98 / candidate bb9b2d2200; policy pytest
   `tests/test_check_required_checks.py tests/test_mutation_targets.py
   tests/test_check_diff_coverage.py` — **141 passed**.

## The prior BLOCKED finding, dispositioned against the code

`9f3eda2e` reported: "`scripts/promote_release.py:578-583` requires soak
evidence on the selected RC run; `.github/workflows/release.yml:952-960`
uploads it only on finals; compatible producer/transport remains unproven."
Re-inspected at this head; the reading is factually correct but it is **the
designed contract, not a defect**:

- `scripts/promote_release.py` (module docstring, "Cross-lane contract
  (#860 / PR #1672)" section) states the soak harness uploads the
  `soak-evidence` Actions artifact **to the RC run** during the candidate
  window, outside this script, and that `adopt-digests` fails closed until
  it exists — "adapting this gate to the harness's boolean schema would
  weaken it".
- `release.yml:946-953` uploads the downloaded evidence on finals **as
  preservation after it gated the promotion** ("A candidate run has no soak
  evidence yet — the soak happens during the candidate window"); the producer
  on the RC run is the soak lane.
- The soak lane is still open work: PR #1672 (open) and issue #860 (open,
  "sustained exact-RC multi-replica workload") — the dispatch context shows
  both unresolved at capture time.

Repairing this "seam" from the release lane would mean fabricating a soak
producer or accepting the harness's weaker schema — exactly what the gate
refuses. No production or workflow change is warranted; the dependency is
owner-owned and tracked.

## Acceptance state (unchanged where operational)

| Captured acceptance criterion | Executed local evidence | Operational remainder |
| --- | --- | --- |
| RC built only from candidate commit | RC-only build conditions + record CLI tests pass in the 703-test battery | Hosted candidate build UNVERIFIED |
| Soak: clean install, real-model, security hot path, backup/restore | Required-check/citation rejection tests pass | Actual soak UNVERIFIED |
| #860 sustained multi-replica workload on the exact RC | `multi_replica_soak` required by pinned tests; missing-soak CLI rejection passes | Actual workload/measurements UNVERIFIED; producer lane (#1672/#860) open |
| Invariant findings routed before promotion | `routed_issue` rejection tests pass | Real routing UNVERIFIED |
| Runtime changes require new RC + applicable soak | Real-git tree guard tests reject content/config/mode changes | Deployed-config equivalence UNVERIFIED |
| Final byte-equivalent to soaked RC | Tree/wheel-hash tests pass; bypass mutant killed (probe above) | Actual promotion pair UNVERIFIED |
| External package/image/signature/install verification | Adjacent release tests pass | External verification UNVERIFIED |
| Machine-readable evidence tied to exact artifact/config | Binding/config-identity rejection tests pass; schema-1 contract enforced | Real evidence + producer/transport owned by open soak lane |

## Disposition

Every gate this lane can execute is green at the merged head bb9b2d2200,
including the two gates named across rounds (front-matter, diff coverage)
and the regression kill proof. What remains is operational acceptance that
requires merging the soak-harness lane (PR #1672) and program-owned release
operations (real RC run, #860 soak, protected promotion, external
verification) — none of which this lane may perform, and for which no
fail-closed contract was weakened. Writer handoff only; no push, no GitHub
mutation, no issue closure, no integration approval. No tests were added or
removed in this round (inventory delta +0); the `tests/: +20` note from
`issue-89-diff-coverage-repair.md` remains the last test delta.
