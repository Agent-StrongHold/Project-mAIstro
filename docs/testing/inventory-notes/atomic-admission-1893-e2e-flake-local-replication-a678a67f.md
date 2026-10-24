# atomic-admission-1893 — e2e flake disproven by local full-suite replication at head a678a67f

Repair round for the #1893 lane at branch `auto-1893`. Starting and ending
head `a678a67f41e2978caf5ca7948933c514e66d6f60`; develop base `b9cd15c60`.
**No code change, no test change** — the round reproduces the failed hosted
`hive-conductor-e2e-ui` job locally at the exact head and re-attributes the
stale "Container scan + SBOM + cosign failure" merge-queue note.

inventory-delta:
  packages/maistro-core/tests: +0

## Prior findings addressed

1. **`hive-conductor-e2e-ui` FAILURE at a678a67f** (run 39901312411, job
   120243520918, step "Run PM workflow Playwright UI e2e"): the job log shows
   a single failure — `[chromium] › tests/e2e/navigation-coverage.spec.ts:288`
   with `Error: locator.click: Page crashed` (217 passed, 1 failed, 1 did not
   run). A Chromium renderer crash is an environment fault, not an assertion
   failure. Three facts pin it as infra, not this branch:
   - the delta to the last fully-green head is one docs-only file
     (`docs/testing/inventory-notes/atomic-admission-1893-ci-green-27c43e7fc.md`,
     `git diff --stat 27c43e7fc..a678a67f4` = 1 file, +95);
   - the branch's diff touches nothing under `packages/hive-conductor/`
     (`git diff --name-only origin/develop..HEAD -- packages/hive-conductor/`
     is empty), and the runtime surface is confined to
     `packages/maistro-core` (new `tasks/admission_codec.py`, one
     `runs/__init__.py` re-export, vulture whitelist entries);
   - **local full-suite replication at the exact head is green**: built the
     `hive` image from this worktree (a678a67f), ran the exact ci.yml command
     `docker compose -f docker-compose.test.yml --profile test up --build
     --abort-on-container-exit --exit-code-from e2e-tests e2e-tests` with
     `CI=true` (playwright.config.ts then uses the CI budget and 0 retries,
     mirroring the runner) — **219 passed (4.3m), exit 0**, including
     `navigation-coverage.spec.ts:288` "browser back and forward return
     canonical surfaces after rail navigation". Compose stack torn down with
     `down -v` afterwards; the worktree stayed clean.

2. **"Container scan + SBOM + cosign: failure" from the last merge-queue
   evaluation** — stale attribution, re-verified live (read-only API,
   2026-10-23): at head a678a67f the `security` workflow run 39901312004
   concluded **success** with `Container scan + SBOM + cosign` → success (job
   120243299830). No merge-group head between 2026-10-22 and now contains
   a678a67f as an ancestor (ancestry checked over every `event=merge_group`
   head_sha in the window), so this PR has never entered a merge group; the
   only failed `security` run nearby (merge-group head ede303c0f, run
   39900691058, 04:30Z) failed `SAST / Gitleaks`, not the container-scan job,
   in a group that does not include this head.

3. **"recovery budget exhausted — /home/dev/fleet-ops/agents/
   maistro-implementer.md missing at launch/preflight"** — infra-only launch
   fault of the prior driver; this round launched normally. Not a tree defect.

4. **`integration-scope` FAILURE** — purely downstream: its "Wait only for
   required specialized CI evidence" step polls the required specialized jobs
   and aborts when one concludes failure ("hive-conductor-e2e-ui is required
   by integration scope but concluded failure", job 120243300120 log). It
   resolves when the e2e-ui job is re-run green; no separate fix exists.

## Local re-validation at a678a67f (this round, all executed)

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -q`
  → **273 passed, 3 skipped** (skips = PG-legs tests without DSN).
- `uv run ruff check .` → **All checks passed!**
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1314 → 1309.
- Full UI e2e suite in compose (exact ci.yml argv, `CI=true`) → **219 passed,
  exit 0** (evidence in finding 1).
- Verifier's deterministic battery (driver-executed, check-0..4.log in the job
  directory): uv sync ok; ruff check ok; ruff format --check "3467 files
  already formatted"; focused pytest 273 passed/3 skipped;
  check-suite-inventory.py ok (17627 nodes, 0 duplicates).

## Remaining gap

Hosted CI green at the exact head a678a67f: at capture time the 04:37Z batch
shows `hive-conductor-e2e-ui` failure (Chromium crash, disproven as a code
defect above), `integration-scope` failure (downstream), `test` and
`Coverage gate` still in_progress inside the same CI run, everything else
success including the security/containers job. Triggering a re-run is a
GitHub mutation outside this lane's authority; the single remaining repair
action is **re-run/observe `hive-conductor-e2e-ui` at a678a67f to green**
(integration-scope follows). No code or test change is indicated by any
evidence in this round.
