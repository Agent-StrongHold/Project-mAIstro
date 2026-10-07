---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-canvas/tests: +0
  packages/maistro-evolve/tests: +0
---

# Issue #41 CI-repair round 22: evidence-led coverage recheck

No production code or tests changed in this validation-only round.

The required exact vulture ratchet command passed at `ff96b0f65201`: 1,359
findings were all classified and reviewed, with zero unclassified and zero
never-allowlisted identities. No dead identity or vulture-ledger amendment was
therefore warranted.

The `coverage-unit` producer was executed with its workflow `PYTHONPATH`,
`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`, branch coverage, and `pytest
--timeout=30` settings. Its core leg passed (`11461 passed, 784 skipped, 1
xfailed` in 242.87s) and its Canvas leg passed (`464 passed, 75 skipped` in
25.38s). The producer then failed in `packages/maistro-evolve/tests` because
this worker cannot connect to `DOCKER_HOST=unix:///var/run/docker.sock`:

- `benchmarks/test_sandbox_exec.py::TestRunFunctionChecksDocker::test_correct_implementation_passes`
- `benchmarks/test_swebench.py::TestRunSwebench::test_correct_fix_scores_full_marks`
- `benchmarks/test_swebench.py::TestRunSwebench::test_malformed_response_fails_via_sandboxed_syntax_error`

Those tests require an actual sandbox and must not be changed to conceal a
missing Docker daemon. Consequently the publish-set coverage producer and its
combined/diff coverage judgment remain unverified locally; this is an
execution-environment block, not evidence for an issue #41 code change.
