# Issue #860 — round 130 (job 87cefe4f) repair validation at the dispatched head 662d11c80

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `87cefe4ff1064a63adf31ed9c843a185` (repair stage), dispatched
at head `662d11c8091093190c2d2b6472ab8b9ef6c2a7ab` (= the round-129 record
commit; `git status --porcelain` empty at start and at end + this record). The
prior repair attempt (job `1a94eb370b914eb4ac79872b426ba684`) died on a
provider timeout (`result.json`: `failure_kind: provider_error`, "Request
timed out", 57 s elapsed, `checks: []`) before executing anything, so no claim
from that attempt existed to carry forward. Every result below was produced
fresh by this round at `662d11c80`, independently of round 129's record, which
was treated as claims to re-prove, not evidence.

## Snapshot

- Start head `662d11c8091093190c2d2b6472ab8b9ef6c2a7ab` — exactly the
  dispatched head; working tree clean.
- Develop base `ab8b3737fa64` verified ancestor of HEAD
  (`git merge-base --is-ancestor` exits 0). Post-dispatch `git fetch origin
  develop` produced no new develop objects; `origin/develop` still resolves to
  `ab8b3737fa64`, also an ancestor of HEAD: **no develop drift, no sync
  conflict**.
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md' ':!quality'` is **0 rows** and
  `git diff --numstat 5a59c724a..HEAD -- scripts/soak/` is **0 rows** —
  production and soak-gate code are byte-identical to the soaked head
  `5a59c724a` (resolved: `5a59c724a20ef1241d57c048df90758f2c2e1e25`), so the
  round-109 evidence pack (`hashes.git_head = 5a59c724a…`, `git_clean = true`)
  remains bound at this head and the checks below ran the exact gate code the
  pack was validated with. The files that differ from `5a59c724a` are
  round-record documentation only.
- Relative to the develop base, `git diff --numstat ab8b3737fa64..HEAD --
  quality/` is **0 rows**: the vulture ledger is untouched this round.

## Stale verifier finding — re-tested, still non-reproducing

The verifier failure carried into this lane
(`/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`:
`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) was
recorded at ancestor head `872fd2ce` on 2026-10-10. Re-executed fresh at
`662d11c80`:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -q` → **38 passed, 6 skipped** (rc=0).
- By-name re-run of `test_ensure_schema_fences_ddl_behind_advisory_lock` →
  **passes** (1 passed): the test asserts exact equality against the full 24
  fenced statements, matching the production `ensure_schema` body
  one-for-one inside the `pg_advisory_xact_lock` fence. The finding is stale,
  not a live defect at this head — third independent confirmation (rounds
  128–130).

## Deterministic battery at `662d11c80` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed (rc=0) |
| `uv run ruff format --check .` | 3,301 files already formatted (rc=0) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** in 2.41s |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q` | **26 passed** in 2.08s |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings; base `ab8b3737fa64`, candidate `662d11c80910`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 backlog items parse, statuses/gaps/citations resolve (rc=0) |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves (rc=0) |
| `uv run python scripts/check-promotion-surface.py` | promotion surface: ok (rc=0) |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (re-derived live, this round)

`failed_promotion_checks` (scripts/soak/run_soak.py, imported in-process at
this head) applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json`
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical to
rounds 109–129. Re-verified from the raw pack document, field by field, this
round:

- Functional gates all hold in the pack:
  `exactly_once_task_admission = true`,
  `exactly_once_schedule_occurrence = true`,
  `rate_limit_enforced = true`, `replica_2_rejoined = true`,
  `graceful_drain` (SIGTERM, `drained: true`, `escalated: false`,
  `drain_5xx: 0`, `drain_conn_errors: 0`),
  `nonterminal_runs_after_settle = {count: 0, ok: true}`.
- Hash binding recomputed against the committed pack: `hashes.git_head =
  5a59c724a20e…`, `git_clean = true`; this HEAD's production tree is
  byte-identical to that pack head (0 diff rows above), so the binding holds
  at this head too.
- `sustain_duration` gate source (`run_soak.py`: `ok: sustain_seconds >=
  PROMOTION_MIN_SUSTAIN_SECONDS`): pack `observed_seconds = 420.05` vs
  `minimum_seconds = 14400` → fails **correctly**; round 109 was an
  intentional 420 s shakedown, not the required ≥4 h sustained soak.
- `exact_rc_artifact` gate source (`preflight_artifact_check()`): deliberately
  hard-codes `ok: false` with docstring "This driver boots host processes,
  never the promoted Compose artifact … deliberately no CLI override"; pack
  records `topology = host-uvicorn-preflight`, reason "not the exact
  production Compose image and configuration" → fails **correctly**, because
  no RC artifact has been designated (below). Both failures are by design,
  not gate bugs; weakening either gate to force a pass would falsify the
  release requirement this issue exists to enforce.

## External blockers (re-derived from this job's own dispatch-context.json, captured 2026-10-17T15:17:46Z — fresher than round 129's capture)

1. **`sustain_duration` — no authorized production window.** The promotion
   floor is a ≥4 h sustained soak. A ≥4 h wall-clock soak cannot be executed
   inside a bounded worker job (background execution is prohibited), and
   scheduling the production observation window is a release-owner decision.
2. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comments** in this capture (updated 2026-09-22) — no RC candidate commit
   has been designated. RC PR #1672 is **open, `draft: true`, `merged:
   false`**, head `15ce4681c4d9` — not a promotable artifact. Linked PRs
   #1567, #1602 and #2100 are closed **and merged**; #1672 remains the only
   unmerged soak-related PR. Designating an RC is a GitHub/release-owner
   action this worker must not perform (no GitHub mutations).

## Disposition

Round 129's NEEDS-DEEP-REVIEW block is **confirmed by independent
re-derivation at this head**, not carried forward. It is not a develop sync
conflict (both the lane base and the post-fetch `origin/develop` are ancestors
of HEAD). The one concrete verifier failure on this lane
(`test_pg_learnings.py` at `872fd2ce`) was re-executed and passes at this
head. There is nothing repairable in-repo: every deterministic gate is green,
the evidence pack is intact and hash-tied, production and soak-gate code are
byte-identical to the pack-bound head, and the two failing promotion gates
fail *correctly* by explicit gate design. The remaining work requires (a) a
release-owner-designated RC artifact under #89 (unblocking #1672 from
WIP/draft or designating another candidate), and (b) an authorized ≥4 h
production observation window for that exact artifact. Until both exist, this
issue stays externally blocked.

No code changes this round; this record is the only file touched.

Progress: `{checked: 10, done: 10, skipped: 0, errors: 0}` — 10 deterministic
gates/checks re-executed green, stale finding re-tested non-reproducing,
promotion gates re-derived live from gate source, external blockers
re-derived from a fresher capture. The single remaining action is outside
this worker's authority.
