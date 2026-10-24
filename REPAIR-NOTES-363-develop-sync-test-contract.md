# REPAIR-NOTES-363 — develop sync: distribution-contract test vs sqlite extra

Round: post-verification CI-repair for lane L363 (branch `auto-363`), starting head
`7098e507c2e8d61c4a2d55abe207c9d71302f082`, develop base `0a3dfdb4e7a97f29ed11e196cd9c86fe2ddde7a6`.

## What was actually red on `7098e507c` (from the check-runs capture, 2026-10-21T05:03Z)

| Check run | Conclusion | Cause |
|---|---|---|
| `test` (ci.yml) | **failure** | `tests/test_distribution_contract.py::test_image_pins_supported_python_and_installs_identity` |
| `coverage (no services)` (quality.yml) | **failure** | `packages/maistro-core/tests/runs/test_parked_run_resume.py::test_a_resumed_schedule_attempt_is_leased_and_reclaimed_after_worker_death[sqlite]` |
| `Container scan + SBOM + cosign` (security.yml) | **success** | — (the lane brief's "Container scan failure" was stale; the capture on this exact SHA shows completed/success) |

## Root cause 1 — `test` job: develop sync gap

The sync merge `7098e507c` brought develop's `2dfd3b97a` (Dockerfile installs
`maistro-core[...,sqlite]`) but stopped one commit short of develop tip
`0a3dfdb4e` ("fix(tests): distribution contract expects the sqlite extra
(2dfd3b97a follow-up)"), leaving the exact-string assertion behind.
`tests/test_distribution_contract.py:72` asserted
`maistro-core[identity,llm,sandbox,observability]` (with closing bracket) while
`Dockerfile:60` installs `maistro-core[identity,llm,sandbox,observability,sqlite]`.

**Fix:** merged `origin/develop` (`0a3dfdb4e`) into `auto-363`. The merge
conflicted on the same hunk (branch side had moved the python pin to 3.13.16 in
`9a821bb96`; develop side had added the sqlite assertion at 3.13.15). Resolved
by keeping **both** contracts: `python_tags == ["3.13.16", "3.13.16"]` (matching
this branch's digest-pinned `python:3.13.16-slim-bookworm@sha256:a1165e27…`
Dockerfile) plus develop's sqlite-extra assertion and its rationale comment.

## Root cause 2 — `coverage (no services)`: trunk-side flake, not this branch

The CI log (job 119032065440) shows
`test_parked_run_resume.py::…_after_worker_death[sqlite]` failing with "a live
resumed Attempt was not renewed by the heartbeat", plus an aiosqlite
`RuntimeError: Event loop is closed` teardown warning. The test's own comment
(records this exact failure mode as flaky: "adjacent pass and fail runs on the
same head" on the no-services coverage job). `git diff 0a3dfdb4e...HEAD` touches
**zero** files under `packages/maistro-core/` — the lease/heartbeat code and
test are trunk-side, unreachable from #363's diff (license inventory, release
gating, container gates). Per repo guidance ("CI failures are often not yours"),
no code change made; evidence gathered instead:

- 3× plain: `…after_worker_death` → 2 passed, 1 skipped (postgres leg skips, no DSN) — all pass
- 3× under the coverage job's exact shape (`coverage run --branch
  --source=packages/maistro-core/src/maistro … --timeout=30`) — all pass

## Validation executed on the repaired head (`6706453d0`)

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/
  --ignore=tests/tools/registry -q` (ci.yml:661's exact step): **5479 passed,
  138 skipped, 0 failed** (was: 1 failed, 5571 passed on `7098e507c`)
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .` →
  3391 files already formatted
- `uv run python scripts/check-suite-inventory.py --suite tests/` → ok, 5710
  node IDs, matches recorded inventory (no test-count delta from this round)
- `uv run pytest tests/test_check_license_inventory.py -q` → 77 passed
- `uv run pytest packages/maistro-rsi/tests/test_gate_evidence.py -q` → 34 passed

## Explicitly not done

- No ledger edits: `Quality / Vulture` and `exact-debt-ledger` were success on
  the captured SHA, and this round adds no production Python.
- No GitHub mutations (no push/PR/comment/close), per lane prohibitions.
- Remote re-run of `test` / `coverage (no services)` on the new merge commit is
  pending CI; local evidence above is the executed proof available in this lane.
