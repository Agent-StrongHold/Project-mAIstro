---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
  packages/maistro-rsi/tests: 0
---

# Issue #80 round 31 — validation-only round: re-prove the named `test` gate and the live Decision-2 refusal at `f7f69a061`, then commit (the previous worker died on a provider 429 before committing)

Branch `auto-80`, head `f7f69a061f9359bb1f5fd2ef11cab6fbe74fa0e9` (unchanged
from the incoming round), issue #80, 2026-09-28. **No code or test file
changed** — this round exists because the previous lane run
(job `4ee37e70f60a47e98977259249ba7929`) had every driver check green
(check-0…check-5 all rc 0, including the exact named `test` gate argv →
199 passed, 19 skipped) but was killed by an upstream LLM rate limit
(`429 poolside/laguna-s-2.1:free`) before it could commit anything, so the
merge queue recorded "worker made no commit; clean tree is not proof of
repair".

## What this round executed (own evidence, at the same head)

- Live ADR-093 Decision-2 conformance on this host's rootful un-remapped
  daemon: `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -v -rs`
  → **1 passed, 18 skipped in 155.45s**. The passing test is
  `test_sandbox_refuses_a_rootful_unmapped_daemon` — the production
  `ContainerBuilderSandbox` positively observed the identity uid_map
  (`0 0 4294967295`, captured from a throwaway probe container) and refused
  entry with `ADR-093 Decision 2`, leaving no container behind. The 18 skips
  are the daemon-posture branch (escape suite runs on a rootless/userns
  daemon — the dedicated CI lane provisions one and runs it). The round-30
  tri-state probe worked as designed: collection completed even though the
  same daemon stalled a manual `docker run` probe past 130–170s minutes
  earlier.
- The exact named `test` gate argv (driver check-3 of this job), re-run in
  this worktree: **199 passed, 19 skipped, 6 warnings in 61.79s**.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 2619 files
  already formatted.
- `scripts/check-suite-inventory.py` for `packages/maistro-bootstrap/tests`
  and `packages/maistro-rsi/tests` → both `ok`, matching recorded inventory
  (delta 0, consistent with no test changes).
- Vulture per-identity ledger (CI-repair instruction):
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → rc 0, 1402/1402 identities banked. No ledger amendment (no `src` change).
- Bubblewrap Tier-3 twin suite
  `packages/maistro-core/tests/sandbox/test_escape_conformance.py` → 4
  passed, 24 skipped (bwrap not installed on this host; the CI lane installs
  it and runs the kernel assertions).

## Acceptance criteria mapping (unchanged from round 30, re-verified)

All ten conformance/escape criteria of issue #80 remain satisfied by
`packages/maistro-bootstrap/tests/test_container_sandbox.py` (live, production
class) + `test_container_sandbox_hardening.py` (daemon-independent selector
proofs, part of the 199 passed) + the CI conformance lane in
`.github/workflows/ci.yml` (rootful refusal step → self-provisioned rootless
daemon → full escape suite) + SECURITY.md limitation #8 citing both. The
detailed per-criterion mapping is in `l80-repair-round30.md` and still
accurate at this head; nothing in the diff surface changed since.

## Environment finding (host, not repo): `/tmp` inode exhaustion

During this round the named gate initially **ERRORED** with
`OSError: could not create numbered dir with prefix pytest- in
/tmp/pytest-of-dev after 10 tries` (via `pytest_asyncio` fixture setup). Root
cause measured on the host: `/tmp` is a 32G tmpfs with **1048576/1048576
inodes used (100%)**, filled by ~650 top-level directories of accumulated
cross-job debris (`find /tmp -xdev` as root sees 1,047,612 entries vs ~4,000
visible to `dev`). This is shared-lane infrastructure hygiene outside this
lane's write scope: no other lane's files were deleted. Mitigation used for
the re-runs above: `TMPDIR` + `--basetemp` pointed at a lane-local directory
outside `/tmp`. **Risk:** the campaign driver's next `/tmp`-rooted run on
this host can fail the same way until the host's `/tmp` is pruned by the
infrastructure owner; this is unrelated to the issue-#80 diff (the same gate
passed through the driver's own check-3 at 18:11 before exhaustion tipped
over).

## Residual risks

- The hosted `test` job's swebench benchmark pull flake (Docker Hub DNS,
  round-29 run 36440932829) remains outside this lane's diff and unproven
  from here; the sandbox-conformance portion of that job is what this issue
  owns, and it is green locally and by construction of the dedicated lane.
- Full escape-suite execution requires the rootless daemon posture; on this
  host only the refusal branch is executable (by design). Hosted CI lane
  evidence and the both-posture re-execution are recorded in
  `l80-verifier-round29.md` / `l80-repair-round30.md`.
