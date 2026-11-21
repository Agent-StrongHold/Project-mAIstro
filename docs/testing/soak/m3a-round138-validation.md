# #860 round 138 — fresh battery, vulture gate, develop-drift analysis, and external-blocker re-verification

- Dispatched head: `daff0328947f6031338ccaf51d221a6f579f6287` (branch
  `auto-860`, base `ab8b3737fa64f8d840f421ef87ca506c509444ff`);
  `git status --porcelain` empty at start and at end.
- Job: `/home/dev/maistro/jobs/5bec951e189b4f5cabae8860e7cdb149`
  (**no `check-*.log` files exist in the job directory** — the driver executed
  no deterministic checks), so every check below was executed by the worker at
  this head. The prior attempt chain also ended in a provider-timeout death
  (`38603fb1`, `Request timed out`, zero checks). Nothing was taken on trust:
  every deterministic check, both gate evaluations, the pack binding and raw
  pack contents, and both external blockers were re-derived this round.
- Previous block to resolve: round 137 **BLOCKED** (external prerequisites
  for criterion 8). Resolution attempt below — the block is external and
  stands, with one new fact (develop drift) derived and dispositioned.

## Fresh deterministic battery (all executed this round, at this head)

| Check | Command | Outcome |
| --- | --- | --- |
| Stale verifier failure `98a11313/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) | `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — 8th consecutive non-reproduction at this head |
| Soak promotion-gate contract | `uv run pytest tests/test_soak_promotion_gates.py -q` | **72 passed** |
| `.gitleaksignore` + prod-stack boot contracts | `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| Concurrency backpressure 429 probe | `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **1 passed** |
| Lint | `uv run ruff check .` | **clean** (all checks passed) |
| Format | `uv run ruff format --check .` | **3301 files already formatted** |
| Suite inventory gate | `uv run python scripts/check-suite-inventory.py` | **ok: 17 suite(s) match the recorded inventory** |
| Vulture per-identity ledger (CI's exact arguments) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **rc=0: 1322 reviewed identities = 1322 findings, base `ab8b3737fa64`, candidate `daff0328947f`, ledger unamended** |

## Structure checks

- Develop base `ab8b3737fa64` is an ancestor of HEAD
  (`git merge-base --is-ancestor` exit 0).
- `git diff --numstat ab8b3737fa64..HEAD -- quality/` is **0 rows**: the
  vulture ledger is untouched (confirmed by the rc=0 gate above; no
  CI-repair amendment needed or made).
- `git diff 5a59c724a..HEAD -- packages/ scripts/soak/` is **0 rows**:
  production and soak-gate code are byte-identical to the evidence-pack-bound
  head `5a59c724a20ef1241d57c048df90758f2c2e1e25`, so the round-109 pack
  remains a valid observation of the code at this head. Only round-record
  documentation differs.

### New this round: develop drift derived and dispositioned

`refs/remotes/origin/develop` has advanced to
`369ab9adde2eb66c105ca4ea950795df8192eb3f` —
`docs(#1796): drop the PostgresOntology claim from the ontology Protocol
docstring (#2140)` — whose **parent is exactly the lane base** `ab8b3737fa64`,
i.e. exactly one upstream commit appeared after round 137's capture (when
`origin/develop` still equaled the base). It is **not contained in HEAD**.

Disposition: **not merged.** The lane's open block is not a develop sync
conflict (it is the external RC/duration prerequisite below), and merging
`369ab9add` would change `packages/maistro-core/src/maistro/ontology/
protocols.py`, breaking the round-109 pack's byte-identity binding
(`git diff 5a59c724a..HEAD -- packages/` would become non-empty) while the
promotion soak that would supersede that pack is itself externally blocked.
The branch stays on its dispatched base; the drift is a docstring-only commit
from another lane's work and is flagged here for the release integrator.

## Promotion gates re-derived live (not read from any doc)

`failed_promotion_checks(m3a-round109-shakedown.json)` executed at this head
via `importlib` load of `scripts/soak/run_soak.py`:

- Result: `['sustain_duration', 'exact_rc_artifact']` — exactly the two
  externally blocked gates, nothing else.
- `sustain_duration`: observed 420.05 s vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`scripts/soak/run_soak.py:69`) — fails correctly against the ≥4 h
  floor.
- `exact_rc_artifact`: `preflight_artifact_check`
  (`scripts/soak/run_soak.py:744-755`) returns
  `{"ok": false, "topology": "host-uvicorn-preflight", "reason": "not the
  exact production Compose image and configuration"}` — `ok: false`
  unconditionally by design; there is deliberately no CLI override.
- CLI hardening re-read (`run_soak.py::main`): `failed =
  failed_promotion_checks(evidence)`; non-empty → `sys.exit(1)`. A run cannot
  report success with a failing gate.
- Pack binding re-read from raw JSON: `hashes.git_head = 5a59c724a…`,
  `git_clean: true`, `git_diff_sha256`/`git_status_sha256` both the
  empty-string hash (`e3b0c442…`) — consistent with the 0-row diff above.
- Raw pack contents re-inspected (not trusted from round 137's summary):
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `replica_2_rejoined` are literal `true`;
  `graceful_drain` is `{required: true, signal: SIGTERM, drained: true,
  drain_seconds: 1.0, drain_5xx: 0, drain_conn_errors: 0, escalated: false,
  ok: true}`; `lb_failover_bounded`, `nonterminal_runs_after_settle`,
  `task_admission_availability` ok; `fd_growth` 30→36 / 29→34 (max 41/39) and
  `rss_growth` 9.0% / 7.7% across replicas — all consistent with the
  round-132 per-criterion table.

## External blockers (re-derived from this job's own capture, 2026-10-17T18:22Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comments** (updated 2026-09-22) — no RC candidate designated. RC PR #1672
   is **open, `draft: true`, `merged: false`, `merged_at: null`**, head
   `15ce4681c4d9` — not a promotable artifact. Designating an RC is a
   release-owner GitHub action; GitHub mutations are prohibited for this lane.
2. **`sustain_duration` — no authorized ≥4 h production window.** The floor is
   14,400 s of sustained observation of the exact RC artifact. A ≥4 h
   wall-clock soak cannot execute inside a bounded worker job (background
   execution prohibited), and the soak target does not exist until blocker 1
   clears. Even an arbitrarily long run of this host-process driver still
   fails `exact_rc_artifact` by design.

Both gates fail correctly; weakening them or fabricating a pass would violate
the issue's own stop condition ("Do not convert this into a benchmark vanity
number") and the lane's no-gate-weakening rule.

## Acceptance-criteria disposition (re-confirmed)

Criteria 1, 2, 4, 6, 7, 9, 10 **MET**; 3/5 **PARTIAL** (documented #842
limitation); 8 (≥4 h exact-RC soak) **UNMET — externally blocked** via the two
gates above. Full per-criterion evidence table:
`m3a-round132-validation.md`, spot-checked against the raw pack this round
(see above). No in-repo change can move criterion 8.

## Disposition

Rounds 130–137's BLOCKED verdict stands. Every deterministic gate is green at
this head (battery, suite inventory, and — newly executed this round — the
vulture ledger gate with CI's exact arguments), the stale verifier failure is
confirmed non-reproducing (8th consecutive time), the two promotion failures
fail correctly against external prerequisites no in-repo change can satisfy,
the evidence pack remains hash-bound to byte-identical code, and the one new
external fact (single-commit develop drift) is derived, dispositioned, and
flagged rather than merged. Verdict: **externally BLOCKED**, not repairable
here. No code changes this round; this record is the only file touched.

Progress: `{checked: 13, done: 13, skipped: 0, errors: 0}` — 8-check fresh
battery (including the vulture gate), 3 structure checks + develop-drift
derivation/disposition, live promotion-gate re-derivation with CLI-exit and
preflight re-reads plus raw-JSON pack spot-check, external blockers
re-derived from this job's own capture, round-137 disposition re-confirmed.
