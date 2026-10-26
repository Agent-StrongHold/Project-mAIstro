---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
---
# M2-B5 required-contract repair: sandbox-conformance joins the merge contract

CI at the develop-sync resolution head failed four gates off one root cause
chain: the `sandbox-conformance` lane was added to ci.yml without joining the
PR-check contract, and its provisioning `run:` block carried four `|| true`
swallows with no written reason.

- `check-workflow-inventory` (#400 rule 3) flagged ci.yml:794/795/796/827.
  `workflow-lint` therefore failed, which `needs:`-skipped `docker-build`,
  which made `integration-scope` report "docker-build is required by
  integration scope but concluded skipped", which failed `gates-ran` and both
  quality aggregates.
- `check-required-checks` / `check-branch-protection` flagged that
  `sandbox-conformance` was "neither required on any branch nor listed under
  advisory" and that both generated documents had drifted.

Repair (no pytest node added or removed):

1. Written reasons for all four swallows: the linger swallow is covered by the
   delegated-cgroup `memory.max` read-back proof later in the same step; the
   two apt swallows are re-proven by the immediate `command -v newuidmap
   slirp4netns`; the dockerd.log tail swallow sits on an already-failing path
   whose `exit 1` still fails the step.
2. Disposition decision: `sandbox-conformance` is **required on develop and
   main** in `.github/branch-protection.json`. Rationale: the job is
   unconditional (no `if:`, no paths filter), merge-group capable, and is the
   only service-backed site where the ADR-093 Decision 2 escape/conformance
   suite executes instead of skips — advisory would pay its cost on every PR
   while letting a D-04-class sandbox regression land on develop unproven. It
   is not a `ci_merge_group_scope` specialized leg, so gates-ran keeps
   demanding it on merge-group queue SHAs with no evaluator change.
3. Regenerated `docs/ci/REQUIRED-CHECKS.md` (`--update`) and
   `docs/ci/BRANCH-PROTECTION.md` (`--update-doc`) from the repaired ruleset.

Evidence: `check-workflow-inventory` clean (31 workflows);
`check-required-checks` ok (76 checks, develop queue SQUASH, all ordinary
required checks report on merge_group); `check-branch-protection` ok (20 on
develop, 33 on main); 171 tests across test_check_workflow_inventory /
test_check_branch_protection / test_check_required_checks /
test_gates_ran_publisher_contract pass; classifier on the candidate's 55
changed paths selects `docker_build: true` and the aggregation passes with all
in-scope legs successful; `node --test tests/ci/integration-scope.test.cjs`
12/12; bootstrap sandbox suites 33 passed / 20 daemon-gated skips; the
rootful-daemon fail-closed refusal test passes against a live rootful daemon.
