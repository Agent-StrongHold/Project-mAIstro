---
inventory-delta:
  packages/maistro-core/tests: +5
---
# Resume a schedule whose resumed Attempt was reclaimed (#1112)

Five behavioral cases in `runs/test_parked_run_resume.py`:

- the ordinary `resume_parked_runs` tick resumes a Run whose resumed physical
  try died and was reclaimed CANCELLED by `recover_abandoned_attempts`,
  completing the node on a third Attempt with the original pause's metadata;
- `resumable_pause` reads the YIELDED pause past one or more reclaimed
  Attempts;
- a FAILED retry after a pause still leaves the Run parked (retry decision
  owed elsewhere);
- a CANCELLED Attempt that was not a lease reclaim is not looked past.
- a NodeRun whose *every* Attempt was reclaimed, and one with no Attempts at
  all, stay parked: reading past a recovery artefact only works because a real
  pause was recorded before it, so with no such pause there is nothing to
  re-enter and nothing may be invented. Added for the diff-coverage floor,
  which caught the exhausted-loop exit as the one uncovered line of the
  change.
