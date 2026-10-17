# Issue #860 — round 123 (job c8150e2c) validation at the dispatched head 74c800eaa

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `c8150e2c2de440caafcb1e749c30c870`, dispatched at head
`74c800eaa` (= the round-122 record commit; `git status --porcelain` empty at
start and at end + this record). The job directory contained **no
`check-*.log` files** — zero driver-executed checks — so every result below
was produced fresh by this round, independently of round 122's record. Prior
artifact read: `/home/dev/maistro/jobs/04689b6925034801ba3bd7b241096a34/result.json`
(verdict `BLOCKED`; rows 3 and 8 externally blocked). This round re-derived
both determinations itself (see External blockers) instead of carrying them
forward.

## Snapshot

- Start head `74c800eaa` — exactly the dispatched head; working tree clean.
- Develop base `ab8b3737fa64` verified ancestor of HEAD
  (`git merge-base --is-ancestor` passes): **no develop drift, no sync
  conflict**. The standing "BLOCKED" attention request from round 122 is not
  a merge conflict (see Disposition).
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md'` is **0 rows** — production code is
  byte-identical to the soaked head `5a59c724a`, so the round-109 evidence
  pack (`hashes.git_head = 5a59c724a…`, `git_clean = true`) remains bound at
  this head.
- Relative to the develop base, exactly 7 non-docs files changed
  (`pg_learnings.py` + its schema-fence test, `tasks.py` + its
  backpressure test, `nginx-soak.conf`, `run_soak.py`, one backlog test);
  **no `quality/*.json` rows were added, removed, or amended**.

## Deterministic battery at `74c800eaa` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,301 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** |
| `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` + `packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`, re-run by name | **3 passed** — formally re-proves the #842 replica-selection allowance and the 98a11313 `check-3.log` finding closure at this head |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings, no unclassified; base `ab8b3737fa64`, candidate `74c800eaa272`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (reproduced live, this round)

`failed_promotion_checks` (scripts/soak/run_soak.py:758) applied in-process
at this head to `docs/testing/soak/evidence/m3a-round109-shakedown.json`
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical
to rounds 109–122. `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
(scripts/soak/run_soak.py:69) vs pack `sustain_seconds = 420.05`;
`preflight_artifact_check` (scripts/soak/run_soak.py:744) hard-codes
`ok = false, topology = "host-uvicorn-preflight"` with no CLI override by
design. Re-verified from the raw pack document, field by field:

- Functional gates all true: `exactly_once_task_admission = true`,
  `exactly_once_schedule_occurrence = true`, `rate_limit_enforced = true`,
  `replica_2_rejoined = true`, `lb_failover_bounded` (observed 5xx +
  conn-errors **0** vs budget 4320.0), `nonterminal_runs_after_settle`
  (count 0), `task_admission_availability` (ratio 1.0), `graceful_drain`
  (`required = true`, SIGTERM, `drained = true`, `drain_5xx = 0`,
  `drain_conn_errors = 0`).
- Hash binding recomputed byte-for-byte this round:
  `nginx_rendered_conf_sha256 = 86291c53…` matches the committed
  `m3a-round109-shakedown-nginx-soak-rendered.conf` directly (the file
  already embeds the recorded gateway `192.168.8.198`).

## External blockers (re-derived from dispatch-context.json, captured 2026-10-17T12:26:59Z)

1. **`sustain_duration` — no authorized production window.** The promotion
   floor is a ≥4 h sustained soak (issue acceptance: "sustained load long
   enough to observe pool saturation, queue growth, lease expiry/reclaim
   …"). Round 109's 420.05 s shakedown intentionally does not satisfy it.
   A ≥4 h wall-clock soak cannot be executed inside a bounded worker job
   (background execution is prohibited; the synchronous budget is far below
   4 h), and scheduling the production observation window is a
   release-owner decision that appears nowhere in the captured state.
2. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion", open) has
   **0 comments** — no RC candidate commit has been designated. RC PR
   #1672 ("WIP: [M3-A][#89] …") is **open, `draft: true`**, head
   `15ce4681c4d9`, last updated 2026-10-16 — not a promotable artifact.
   All 1,149 comments on #860 are bot progress markers; **zero** human/
   release-owner comments exist anywhere in the captured scope. Designating
   an RC is a GitHub/release-owner action this worker must not perform
   (no GitHub mutations).

## Disposition

Round 122's BLOCKED determination is **confirmed by independent re-derivation
at this head**, not carried forward. It is not a develop sync conflict (base
verified ancestor), and there is nothing repairable in-repo: every
deterministic gate is green, the evidence pack is intact and hash-tied, and
the two failing promotion gates fail *correctly* — weakening them to force a
pass would falsify the release requirement this issue exists to enforce.
The remaining work requires (a) a release-owner-designated RC artifact under
#89 (unblocking #1672 from WIP/draft or designating another candidate), and
(b) an authorized ≥4 h production observation window for that exact
artifact. Until both exist, this issue stays externally blocked.

No code changes this round; this record is the only file touched.
