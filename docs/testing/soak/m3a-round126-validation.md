# Issue #860 — round 126 (job d977574f) validation at the dispatched head 460daaca2

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `d977574f9d1c4d9c83049232c3041ad4`, dispatched at head
`460daaca28d50534cdfd5766bb2ba9b70c54ae13` (= the round-125 record commit;
`git status --porcelain` empty at start and at end + this record). The
immediately prior attempt at this lane (`ac30434c9d3947b68a91a2d9672391b2`)
died on a provider timeout before running any checks (`"checks": []`,
`"failure_kind": "provider_error"`), so every result below was produced fresh
by this round, independently of round 125's record — no validation result is
carried forward unverified. The dispatch manifest for this job also lists
`"checks": []`, so the driver executed no deterministic checks; the battery
below is this round's own execution.

## Snapshot

- Start head `460daaca28d50534cdfd5766bb2ba9b70c54ae13` — exactly the
  dispatched head; working tree clean.
- Develop base `ab8b3737fa64` verified ancestor of HEAD
  (`git merge-base --is-ancestor` exits 0): **no develop drift, no sync
  conflict**. The standing "BLOCKED" attention request from round 125 is
  therefore not a merge conflict (see Disposition).
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md'` is **0 rows** — production code is
  byte-identical to the soaked head `5a59c724a`, so the round-109 evidence
  pack (`hashes.git_head = 5a59c724a…`, `git_clean = true`) remains bound at
  this head.
- **Gate-code drift, resolved**: `git diff --numstat 3da4e035..HEAD --
  scripts/soak/` shows 1 row (`run_soak.py`, +34/−7), but the entire delta
  lies between `3da4e035` and the pack-bound soak head: `git diff --numstat
  5a59c724a..HEAD -- scripts/soak/` is **0 rows**. The in-process gate replay
  below therefore runs the exact `run_soak.py` the round-109 pack was
  validated with — the replay is faithful, and the drift is pre-pack soak
  tooling work, not post-pack gate mutation.
- Relative to the develop base, no `quality/*.json` rows were added, removed,
  or amended (`git diff --numstat ab8b3737fa64..HEAD -- quality/` = 0 rows);
  the vulture ledger is untouched this round.

## Stale verifier finding, re-verified non-reproducing

Verifier job `98a11313167b41a98a420abfda80c292` (head `872fd2ce`, an ancestor
of this HEAD) failed `check-3.log` on
`test_ensure_schema_fences_ddl_behind_advisory_lock` (assert `24 == 21`: the
test's expected-DDL list predated the three Gauntlet audit columns). The fix
landed before round 112 and this round re-proves it at this head: the exact
failing pair passes — `uv run pytest
packages/maistro-core/tests/persistence/test_pg_learnings.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q`
→ **38 passed, 6 skipped** (the DDL-fence test now expects the full 24
statements, fence intact).

## Deterministic battery at `460daaca2` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed (rc=0) |
| `uv run ruff format --check .` | 3,301 files already formatted (rc=0) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** |
| `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` + `packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`, re-run by name | **3 passed** — re-proves the #842 replica-selection allowance and the pg_learnings DDL advisory-lock fence at this head |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings, no unclassified; base `ab8b3737fa64`, candidate `460daaca28d5`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 backlog items parse, statuses/gaps/citations resolve (rc=0) |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves (rc=0) |
| `uv run python scripts/check-promotion-surface.py` | promotion surface: ok (rc=0) |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (reproduced live, this round)

`failed_promotion_checks` (scripts/soak/run_soak.py, imported in-process at
this head) applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json`
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical to
rounds 109–125. `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` vs pack
`sustain_seconds = 420.05`; the pack's own
`thresholds.checks.exact_rc_artifact = {ok: false, topology:
"host-uvicorn-preflight", reason: "not the exact production Compose image and
configuration"}`. Re-verified from the raw pack document, field by field:

- Functional gates all true: `exactly_once_task_admission`,
  `exactly_once_schedule_occurrence` (with
  `occurrences_with_multiple_runs = 0`), `rate_limit_enforced`,
  `replica_2_rejoined`, `lb_failover_bounded` (observed **0** vs budget
  4320.0), `nonterminal_runs_after_settle` (count 0),
  `task_admission_availability` (ratio 1.0), `graceful_drain` (`required =
  true`, `drained = true`, `drain_5xx = 0`, `drain_conn_errors = 0`).
- Hash binding recomputed byte-for-byte this round: sha256 of the committed
  `m3a-round109-shakedown-nginx-soak-rendered.conf` = `86291c53ab2a81fd…` =
  pack `hashes.nginx_rendered_conf_sha256` (**MATCH**); pack
  `hashes.git_head = 5a59c724a…`, `git_clean = true`.

## External blockers (re-derived from dispatch-context.json, captured 2026-10-17T13:36:13Z — fresher than round 125's capture)

1. **`sustain_duration` — no authorized production window.** The promotion
   floor is a ≥4 h sustained soak (issue acceptance: "sustained load long
   enough to observe pool saturation, queue growth, lease expiry/reclaim
   …"). Round 109's 420.05 s shakedown intentionally does not satisfy it.
   A ≥4 h wall-clock soak cannot be executed inside a bounded worker job
   (this job's `timeout_s = 5400`; background execution is prohibited), and
   scheduling the production observation window is a release-owner decision.
2. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open
   with 0 comments** (comment list empty) in this capture — no RC candidate
   commit has been designated. RC PR #1672 is **open, `draft: true`**, head
   `15ce4681c4d9`, `merged: false` — not a promotable artifact. All 1,157
   comments on #860 are `maistro-progress` automation markers from the
   orchestrator account (spot-checked first `…:started` 2026-10-05 and newest
   `…:blocked` 2026-10-17T13:20:42Z); **zero** human/release-owner comments
   exist in the captured scope. Linked PRs #1567, #1602, #2100 are closed
   **and merged**; #1672 remains the only unmerged soak-related PR. Designating
   an RC is a GitHub/release-owner action this worker must not perform (no
   GitHub mutations).

## Disposition

Round 125's BLOCKED determination is **confirmed by independent re-derivation
at this head**, not carried forward. It is not a develop sync conflict (base
verified ancestor), and the verifier's stale `check-3.log` finding is
re-verified non-reproducing at this head. There is nothing repairable
in-repo: every deterministic gate is green, the evidence pack is intact and
hash-tied, soak gate code is byte-identical to the pack-bound head, and the
two failing promotion gates fail *correctly* — weakening them to force a pass
would falsify the release requirement this issue exists to enforce. The
remaining work requires (a) a release-owner-designated RC artifact under #89
(unblocking #1672 from WIP/draft or designating another candidate), and
(b) an authorized ≥4 h production observation window for that exact artifact.
Until both exist, this issue stays externally blocked.

No code changes this round; this record is the only file touched.
