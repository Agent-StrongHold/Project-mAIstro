---
inventory-delta:
  tests/: +5
---

# CI #2450: dependency-bump PR surfaces must trigger the Mutation gate

Five structural tests pin the `pull_request.paths` widening in
`.github/workflows/mutation.yml` that repairs the merge-queue admission
failure "commit status not successful" on PR #2450 (anthropic 1.11.0 →
2.9.0, head 62ce6f87a9).

## Failure mode, measured not guessed

`check-gates-ran.py --require-complete --base-branch develop --event-name
pull_request --changed-files <measured 4-file envelope>` against the live
check-run payload captured at head 62ce6f87a9 exits 2 (PENDING) with exactly
one absent required row: "Mutation gate (changed critical lines)". All 73
other required checks were present and successful — the prior round's
`.trivyignore.yaml` trivy triage had already turned "Container scan + SBOM +
cosign" green — so no later publisher run could ever flip the verdict: the
PR's envelope (`.trivyignore.yaml`, `packages/maistro-bootstrap/
pyproject.toml`, `packages/maistro-core/pyproject.toml`, `uv.lock`) matched
no `paths:` pattern, GitHub never created the Mutation check-run, and the
evaluator can only excuse a check that is *present* and skipped. This is the
same producer-absence failure mode repaired four times before (#2120 image
pins, #2371 grant ledgers + inventory notes, #2432 gate scripts, #2345
dev-tool requirements); #2450 is the first dependency-bump PR to hit it.

## What the tests pin

- The three new trigger entries exist in the parsed workflow (`uv.lock`,
  `packages/**/pyproject.toml`, `.trivyignore.yaml`) and match exactly the
  envelope classes of #2450 — one test per surface, so a future revert that
  drops any one entry fails a named test.
- The surfaces exist on disk (a trigger for a deleted path would be dead
  text).
- Zero-overlap is structural: every entry in
  `quality/mutation-critical-files.json` is a `.py` source under `packages/`,
  and the job's changed-file pathspec stays `-- packages`, so dependency
  metadata diffs always resolve to "No mutation-critical file changed;
  nothing to mutate." The widened gate gains execution evidence without
  changing what it mutates; it still fails closed when a critical `.py`
  changes.

End-to-end proof at the edited tree: appending a synthetic successful
"Mutation gate (changed critical lines)" check-run to the captured payload
flips the same CI-exact evaluator invocation from PENDING (rc=2) to
`ok: all 79 required check(s) ran on this head` (rc=0) — i.e. the first
post-push Mutation run publishes gates-ran success and unblocks the merge
queue.
