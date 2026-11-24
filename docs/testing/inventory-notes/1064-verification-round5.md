# 1064-verification-round5

Round-5 repair of the hosted coverage-gate cancellation at head
`8fc5b6d76606614222acbb9ee445c25c200a453a` (develop base `0282be2423ab70480f15ebe585042c525c841ee9`).
Adds no tests; changes exactly two files: `.github/workflows/quality.yml`
(coverage-gate `timeout-minutes: 30` -> `45` with capacity arithmetic) and the
self-validating `coverage-gate` digest re-pin in
`tests/fixtures/ci_quality_obligations.json`.

## Hosted diagnosis (run 45447298201, read-only via gh at this exact head)

The named failure — "Coverage gate (publish-set floor + diff coverage) =
cancelled" — is a capacity cancellation, not a content failure. From the job
log (job 138644522615, started 17:34:43Z, killed 18:04:54Z):

- 17:35:18Z — combine + publish-set 87% floor: PASSED (report printed, floor met).
- 17:37:01–17:39:23Z — the seven serial producers that follow the floor, in
  step order —
  maistro-server, maistro-turing, maistro-turing/backend, maistro-design,
  maistro-registry, maistro-ext-harness, maistro-ext-sdk — ALL PASSED
  (execution-order pass counts 723/225/138/689/366/273/147; the first
  producer alone: 723 passed/18 skipped in 1m39s).
- 17:46:43Z — hive-conductor full backend producer: **4486 passed, 100 skipped
  in 7m16s — ALL PASSED.** The six "RuntimeError: Event loop is closed" job
  annotations land inside this suite's teardown noise; the suite and its job
  were green (the same annotations appear in the coverage (PostgreSQL)
  producer job, which finished ✓ in 15m03s).
- 18:04:27Z — root `tests/` scripts producer: **6081 passed, 140 skipped in
  17m39s — ALL PASSED.**
- 18:04:54Z — **"The operation was canceled."** — the job hit its own
  `timeout-minutes: 30` before `coverage xml` and the diff gate could run.

Consequences upstream: the required check never reported, so gates-ran
(run 45455624158) failed the candidate with "Required execution evidence is
missing or non-executed". The branch's gate-side diff vs develop adds no
serial producer (only the producer-side hive-conductor Evolve legs and the
`combine --append` fix); the growth is real test mass this branch adds that
measures changed code — hive-conductor backend producer 2m16s (#1591 era) ->
7m16s, root producer 17m39s (6081 tests). Remaining producers total ~4m40s;
floor/combine ~2m; need at this head ~32–33m > the 30m cap.

## Repair (capacity, not scope)

- `quality.yml`: `timeout-minutes: 30` -> `45` on the coverage-gate job,
  comment citing run 45447298201's arithmetic. Same rationale as the
  in-file 15 -> 30 raise (2026-09-26): a cancelled gate never reports and
  blocks every PR without measuring anything. Thresholds (87% floor, 90/80
  per-file diff) are untouched.
- `tests/fixtures/ci_quality_obligations.json`: `coverage-gate` job digest
  re-pinned with the test's own algorithm
  (`sha256(json.dumps(job, sort_keys=True, separators=(',',':')))`), the
  documented self-validating mechanism (cf. b66758034b "repin coverage-gate
  obligation digest"). Comment edits are outside the parsed job dict and do
  not affect the digest; the timeout value does.

## Local battery at `8fc5b6d766` + these two edits

- `pytest tests/test_ci_quality_split.py tests/test_check_diff_coverage.py -q`
  — **114 passed** (validates the re-pinned digest and the MEASURED_ROOTS
  agreement).
- `ruff check .` — clean; `ruff format --check .` — 3655 files already formatted.
- `scripts/check-workflow-inventory.py` — clean, 33 workflows dispositioned;
  `scripts/check-workflow-write-safety.py` — ok.
- Vulture ledger with CI's exact arguments
  (`check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) — 1221 == 1221, no ledger amendment needed.
- Gate-condition reproduction of the heaviest serial producer (no PG env,
  `coverage run --branch --source=packages/hive-conductor/backend -m pytest
  packages/hive-conductor/backend/tests --timeout=30 -q` after installing
  `packages/hive-conductor/backend/requirements.txt`): **4505 passed, 81
  skipped in 4m55s**, and the producer's `.coverage` carries
  `services/evolve_domain_store.py` rows (the data the diff gate consumes;
  PG arcs arrive via the coverage-postgres producer, which was ✓ hosted).
- `pytest tests/cross_product_parity/test_cross_product_parity.py -q` —
  **26 passed** (incl. the Builders closeout-evidence receipt test fixed by
  the head commit 8fc5b6d766).
- Develop containment re-proven at the round-5 head:
  `git merge-base HEAD origin/develop == origin/develop == 0282be2423`
  (origin/develop fetched fresh this round; the historical CONFLICTING state
  was resolved by the round-3 merge 62b6ff4fae; `git merge origin/develop`
  would be a no-op).

## Deliberately not changed

- The vulture ledger (`quality/vulture-baseline.json`): balances; no
  amendment permitted or needed.
- No suite list, `--source`, floor or diff threshold moved: the gate now
  gets the time to measure what it always measured.

## Hosted / cross-repo (read-only)

- A hosted run at the new tip: UNVERIFIED from this worktree (no push, no
  GitHub mutations). The repair's hosted prediction is concrete: the same
  suites that all passed at 8fc5b6d766 now have ~13 minutes of headroom to
  reach `coverage xml` + the diff gate.
- The #947 review-thread disposition and issue closure remain open and
  untouched (issue-closure preconditions, not PR-merge criteria).

## Front-matter repair (round-5 verification round, same change)

This note originally opened with `inventory-delta: {}` — a delta block with a
same-line value, which `check-suite-inventory.py` rejects as unreadable rather
than silently treating as zero. The change records no delta (it adds no
tests; it raises the coverage-gate capacity and re-pins one obligation
digest), so the block is removed entirely: per `inventory-notes/README.md`, a
note with no front matter records no delta, which is the correct form for a
change that moved no count.

Local battery re-run at head `0e5f077cd9` with this edit: the failed gate
(`check-suite-inventory.py`, both CI's no-arg form and the `--suite
packages/hive-conductor/backend/tests` form) passes — 21/21 suites match,
36483 node IDs; `ruff check .` and `ruff format --check .` clean;
evolve reconstruction/durable-snapshot legs 11 passed;
hive-conductor evolution restart-replay/startup/retention/store legs
52 passed, 20 skipped; `tests/test_ci_quality_split.py` +
`tests/test_check_diff_coverage.py` 114 passed (digest re-pin still valid);
cross-product parity 26 passed; workflow-inventory (33 workflows) and
workflow-write-safety clean; vulture at CI's exact arguments 1221 == 1221
(exit 0); merge-base HEAD == origin/develop == `0282be2423ab`.
