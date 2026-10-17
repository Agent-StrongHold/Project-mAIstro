# Issue #860 — round 131 (job 0614073f) repair validation at the dispatched head 8b26f7378

**Not promotion evidence or integration approval.** This round resolves the
NEEDS-DEEP-REVIEW block carried from job `87cefe4ff1064a63adf31ed9c843a185`
(round 130): it independently re-verified the two deep-review findings against
gate source at the dispatched head, re-ran the full deterministic battery
fresh, and re-tested the lane's stale verifier failure. Conclusion: the block
is a genuine external dependency, not an in-repo defect — see Disposition.

## Snapshot

- Start head `8b26f7378d91cf78887c45d4ffd7c07d6aaff6cb` — exactly the
  dispatched head; `git status --porcelain` empty at start and at end.
- Develop base `ab8b3737fa64` is an ancestor of HEAD
  (`git merge-base --is-ancestor` exit 0). Post-dispatch `git fetch origin
  develop` resolved `FETCH_HEAD` to `ab8b3737fa64` — identical to the lane
  base: **no develop drift, no sync conflict**.
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md' ':!quality'` is **0 rows** and
  `git diff --numstat 5a59c724a..HEAD -- scripts/soak/` is **0 rows** —
  production and soak-gate code are byte-identical to the soaked head
  `5a59c724a20ef1241d57c048df90758f2c2e1e25`, so the round-109 evidence pack
  (`hashes.git_head = 5a59c724a…`, `git_clean = true`,
  `git_status_sha256`/`git_diff_sha256` = sha256 of empty input) remains bound
  at this head. Only round-record documentation differs from the pack head.
- Relative to the develop base, `git diff --numstat ab8b3737fa64..HEAD --
  quality/` is **0 rows**: the vulture ledger is untouched this round.

## Deep-review findings from round 130 — inspected against gate source, confirmed correct-by-design

1. `scripts/soak/run_soak.py:1579` — `exact_rc_artifact` calls
   `preflight_artifact_check()` (line 744), which deliberately hard-codes
   `ok: false` with docstring "This driver boots host processes, never the
   promoted Compose artifact … There is deliberately no CLI override: an
   exact-RC runner needs its own observed image/configuration evidence before
   this gate can be satisfied." Not a gate bug: weakening it would falsify the
   release requirement this issue enforces.
2. `scripts/soak/run_soak.py:1626-1629` — `sustain_duration` compares
   `sustain_seconds >= PROMOTION_MIN_SUSTAIN_SECONDS` (line 69:
   `14_400`). Pack `observed_seconds = 420.05` (intentional round-109
   shakedown) → fails correctly; the ≥4 h sustained soak has not been run.

Both failures are the gate doing its job. Nothing to repair in gate code.

## Stale verifier finding — re-tested at this head, non-reproducing (4th confirmation)

`/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`
(`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`,
recorded at ancestor `872fd2ce`) re-executed fresh at `8b26f7378`:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -q` → **38 passed, 6 skipped** (rc=0).
- By-name: `test_ensure_schema_fences_ddl_behind_advisory_lock` → **1 passed**.

Stale, not a live defect at this head.

## Deterministic battery at `8b26f7378` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed (rc=0) |
| `uv run ruff format --check .` | 3,301 files already formatted (rc=0) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** in 2.35s |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q` | **26 passed** in 2.01s |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings; base `ab8b3737fa64`, candidate `8b26f7378d91`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 backlog items parse, statuses/gaps/citations resolve (rc=0) |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves (rc=0) |
| `uv run python scripts/check-promotion-surface.py` | promotion surface: ok (rc=0) |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (re-derived live, this round)

`failed_promotion_checks` (imported in-process from
`scripts/soak/run_soak.py` at this head) applied to
`docs/testing/soak/evidence/m3a-round109-shakedown.json` returns exactly
**`['sustain_duration', 'exact_rc_artifact']`** — identical to rounds
109–130. Re-verified field-by-field from the raw pack:

- Functional gates all hold: `exactly_once_task_admission = true`,
  `exactly_once_schedule_occurrence = true`, `rate_limit_enforced = true`,
  `replica_2_rejoined = true`, `nonterminal_runs_after_settle =
  {count: 0, ok: true}`, `graceful_drain` (SIGTERM, `drained: true`,
  `escalated: false`, `drain_5xx: 0`, `drain_conn_errors: 0`).
- Hash binding recomputed from the committed pack: `hashes.git_head =
  5a59c724a20e…`, `git_clean = true`, empty-diff digests
  (`e3b0c442…`); this HEAD's production tree is byte-identical to that head
  (0 diff rows above), so the binding holds at this head too.

## External blockers (from this job's dispatch-context.json, captured 2026-10-17T15:38–15:39Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89 (the
   RC-promotion epic) is **open with 0 comments** in this capture — no RC
   candidate commit has been designated. RC PR #1672 is **open, `draft: true`,
   `merged: false`**, head `15ce4681c4d9` — not a promotable artifact. Linked
   PRs #1567, #1602, #2100 are closed and merged; #1672 remains the only
   unmerged soak-related PR. Designating an RC is a release-owner GitHub
   action this worker must not perform (no GitHub mutations).
2. **`sustain_duration` — no authorized ≥4 h production window.** The
   promotion floor is a ≥4 h sustained soak of the exact RC artifact. A ≥4 h
   wall-clock soak cannot execute inside a bounded worker job (background
   execution prohibited; job budget 5,400 s), and the soak target itself does
   not exist until blocker 1 clears.

## Disposition

Round 130's NEEDS-DEEP-REVIEW is **resolved**: the review was performed and
the two findings are gate-correct by design, not defects. The single
acceptance criterion still unproven — "at least one long-running soak of the
exact RC artifact/configuration that #89 would promote" — is blocked by
external prerequisites that no in-repo change can satisfy: (a) a
release-owner-designated RC under #89, and (b) an authorized ≥4 h production
observation window for that artifact. Every deterministic gate is green, the
evidence pack is intact and hash-tied, production and soak-gate code are
byte-identical to the pack-bound head, and the previously failing promotion
checks fail correctly. Verdict: **externally BLOCKED**, not repairable here.

No code changes this round; this record is the only file touched.

Progress: `{checked: 12, done: 12, skipped: 0, errors: 0}` — snapshot +
binding checks, 2 deep-review findings inspected at gate source, stale
verifier failure re-tested, 9 deterministic gates green, promotion-gate
evaluation + pack hashes re-derived live, external blockers re-derived from a
fresher capture.
