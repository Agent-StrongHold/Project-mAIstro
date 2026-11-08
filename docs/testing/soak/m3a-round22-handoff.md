# Issue #860 — round 22 validation checkpoint (CI-repair round)

**Not promotion evidence or integration approval.** This round resolves the
previous "independent review: BLOCKED" request in its repairable part: the
first completed CI evidence for head `cd77bb81c` arrived, and its one
branch-caused failure (required gate `SAST (bandit + semgrep + gitleaks)`)
is repaired here. The issue's soak acceptance blockers are unchanged
external prerequisites — see the audit below.

## Frozen scope

Only issue #860 and the CI failures observable on its head, in
`/home/dev/Git/wt/auto-860`, starting at clean HEAD
`cd77bb81c452aaa15054bc925152e94c87cbfdfa` (matches the assigned job head).
The job directory contained no `check-*.log` files, so every check below was
executed locally. `1e640df17c` (assigned develop base) is an ancestor of
HEAD; the worktree started clean.

## New evidence: GitHub CI on cd77bb81c (read via gh, read-only)

The prior round recorded CI as `in_progress`/pending — the first runs have
now completed:

- **`SAST (bandit + semgrep + gitleaks)` — failure.** This check is in
  `.github/branch-protection.json`'s required contexts for `develop`, so it
  is a real merge blocker. Log breakdown (job 112324120054): bandit
  Medium+ count **0** (strict gate passed); semgrep **0 findings** (364
  rules); gitleaks `--log-opts=$BASE_SHA..$HEAD_SHA` over
  `1e640df17c..cd77bb81c` (184 commits): **1 leak**.
  Reproduced locally with the same gitleaks 8.30.1: the finding is
  `generic-api-key` on
  `docs/testing/soak/evidence/m3a-round7-prodstack-quick-probes.json:13`,
  introduced by commit `88edcc7e` — the round-7 pack's
  `"idempotency_key": "prod7-eo-<32-hex>"`, the correlation ID the probe
  client generated to deduplicate its own POST /tasks retries. It
  authenticates to nothing (the probe's principal traveled in a separate
  auth header) and the throwaway stack it named no longer exists. The file
  is a recorded observation tied to the round's artifact hashes, so
  de-shaping the value in place would falsify the record and rewriting the
  introducing commit is not available — the same bind as the `8185c1d0`
  entry this lane already recorded.
- **`devskim` (code-scanning) — failure, advisory.** 48 gating alerts (47
  failure + 1 warning), each individually inspected: 44× "Do not store
  tokens or keys" on `docs/testing/soak/evidence/*.json` — all fire on
  non-credential hex identifiers (run IDs, `*_sha256`/`git_head` fields,
  image digests), zero secrets in the packs; 1× "Insecure URL" on the
  recorded loopback `http://127.0.0.1:18080` endpoint;
  1× weak-random on `scripts/soak/run_soak.py:723`, where the PRNG is
  deliberately seeded per worker (`random.Random(worker_id)`) so the load
  mix is reproducible — a security-function rule applied to a load-shape
  sampler; the remaining 29 are non-gating notices. DevSkim is a documented
  **advisory** check: `docs/ci/REQUIRED-CHECKS.md:136-139` states it is
  "intentionally excluded from both protected required-check sets until the
  owner promotes it into the merge contract". In-file "fixes" for the
  evidence-pack alerts would falsify recorded evidence and dismissal
  requires GitHub mutations (prohibited), so the alerts are recorded here
  and left to the check's owner.
- **develop's own SAST is red today** (runs on `1e640df17` and
  `e28835544` fail): the `--all` arm re-reports the M4-A8 attribution
  false positive at lines that drifted after later merges (commit
  `77c17b9b8`, already on develop). Pre-existing debt, not this branch's
  diff; re-keyed under this round's repair (below) because it blocks the
  same gate this branch needs green at merge time.
- Still pending at capture: `test`, `Coverage gate (publish-set floor +
  diff coverage)` — in progress, not yet evidence either way.

## The repair (this round's committed diff)

1. `.gitleaksignore` — one fingerprint added for the #860 evidence-pack
   correlation ID, keyed to introducing commit `88edcc7e` exactly like the
   neighboring `8185c1d0` lane entry, with the justification in the file's
   house style; plus two re-keyed fingerprints for the M4-A8 attribution
   false positive (`77c17b9b8:packages/maistro-evolve/tests/
   test_attribution.py:generic-api-key:462/476`), whose earlier
   `bd8dc5fa:361/375` entries rotted when develop-side edits moved the
   calls. No rule is weakened: each entry is scoped to one commit + path +
   rule (+ line), and anything else — any other file, commit, or rule —
   still fails closed.
2. `tests/test_gitleaksignore_contract.py` (new, 8 cases) — pins the
   contract that keeps those entries from decaying silently: fingerprint
   grammar, repo-relative paths, uniqueness, and for every commit that
   resolves in this repository, the referenced blob must exist at that
   commit with at least the flagged line (`git cat-file -e`/`git show`).
   A mis-keyed entry fails loudly now instead of re-reporting as an
   unexplained SAST failure on a future PR.
3. `docs/testing/inventory-notes/860-gitleaksignore-contract.md` — the
   suite-inventory delta (`tests/: +8`, recorded by
   `check-suite-inventory.py --update`) and the prose rationale.
4. This checkpoint.

## Revalidation at cd77bb81c + this diff (all executed this round)

| Command | Result |
| --- | --- |
| `gitleaks git --log-opts="1e640df17c..HEAD" .` (the CI PR arm) | **no leaks found** (was 1) |
| `gitleaks git --log-opts="--all" .` (the develop push arm) | 0 findings reachable from HEAD; the 10 remaining are other lanes' rebased/unmerged refs (the file's own header documents that churn) |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (3048 files) |
| `uv run pytest tests/test_gitleaksignore_contract.py -q` | 8 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` (prior round's exact verifier argv) | 38 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -q` | 60 passed |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args) | PASS: 1332/1332, base `1e640df17c8a` |
| `uv run python scripts/check-suite-inventory.py --suite "tests/"` | PASS: 1 suite matches the recorded inventory (with the +8 delta note) |
| Mis-key demo: `git cat-file -e 88edcc7e…:<wrong path>` / `<wrong sha>:…` | both fail → the contract test's blob probe bites |

## Acceptance audit (unchanged in substance)

The external prerequisites recorded by rounds 19–21 stand and are not
reachable by this lane: (1) no release-owner designation of an immutable RC
image/configuration exists, so the ≥4 h soak of the exact RC artifact
(`run_soak.py:635-647` deliberately refuses host-process equivalence, no CLI
override) cannot start; the longest committed observation remains 1200 s vs
the 14400 s floor (`sustain_duration: ok:false` in the round-8 pack, whose
10-gate `failed_promotion_checks` replay this lane reproduced byte-for-byte
last round); (2) the aggregate cross-replica rate-budget contract awaits the
owning lane's decision (#842); (3) provider-credentialed production-path
workloads (physical Attempt fencing, Goal reconciliation under load) remain
unverifiable without credentials. What this round adds is the merge-readiness
of the branch itself: the one required check that this branch's content was
failing now evaluates clean in both scan arms, with the disposition recorded
where the next reviewer will look.

`{checked: 2, done: 2, skipped: 0, errors: 0, next: designated RC artifact,
#842 aggregate-rate ownership decision, provider-credentialed soak, then a
≥4 h soak of that exact artifact before final promotion}`
