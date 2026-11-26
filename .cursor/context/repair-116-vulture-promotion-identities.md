# Repair #116 @ 2b0e9325a (branch auto-116) — 2026-10-04, round 11

Round 11 (driver job 16e1f084a44d4bacae3531b9e6b9f53b, phase repair; brief
again carried the CI-exact vulture repair instruction and named develop base
29af8200e4a846036fa8357ab67d5bb47f950db9). No check-*.log files were present
(manifest `checks: []`), so every claim below is own execution at the
unchanged head 2b0e9325a (tree clean at start and end).

- **Vulture gate re-run CI-exact (quality.yml:963-965 form), direct exit**:
exit 1; base 97c05e0f17e3, candidate 2b0e9325a7c2, 1342 reviewed → 1344
findings, unclassified 0. Sole exit driver unchanged: the **3 unauthorized
identities** `governance/promotion.py:385 attach_effect / :414 mark_reversed /
:645 promote` (core-public-api-surface). The gate's own words: "New Vulture
debt is not authorized by the trusted base. Running --update in this branch
cannot authorize it; **land a reviewed grant first**."
- **Both develop-side unlock paths re-checked at the NEW designated base
29af8200e** (develop advanced a586560 → 29af8200e, dependency bumps): (a)
`ratchet-authorizations.json` vulture section at 29af8200e has **0
promotion.py keys** (61 keys total); (b) `vulture-baseline.json` at
29af8200e has **0 promotion.py rows** — the debt is not pre-banked there
either. Merge-base with origin/develop is still 97c05e0f1 (also 0 keys).
No in-branch state can pass: `ratchet_provenance.load_authorizations` reads
grants from the base revision only.
- **No-merge decision stands**: the brief conditions a develop merge on a
develop-sync-conflict block; this round's block is the grant. Merging
29af8200e would move the trusted base to a commit that still lacks the
grant (vulture stays red) and would re-fold the ac-state floors from the
new notes in a586560..29af8200e without an authorized bank (rounds 9-10
evidence) — strictly worse.
- **Instructed ledger amendment re-proven exact**: gate `--update` run again
→ **byte-level no-op** (`diff -q` clean vs pre-run copy);
`git diff --numstat origin/develop HEAD -- quality/vulture-baseline.json`
= **+3/−1**: the 3 reviewed retained identities banked under `rules` —
  - `packages/maistro-core/src/maistro/governance/promotion.py::unused method 'attach_effect'`
  - `packages/maistro-core/src/maistro/governance/promotion.py::unused method 'mark_reversed'`
  - `packages/maistro-core/src/maistro/governance/promotion.py::unused method 'promote'`
  and the stale `auth/resources.py POLICY` row pruned (that row appears only
  in the gate's informational trusted-removed section and is not an exit
term). "Fix what is genuinely dead" has no object: re-verified from primary
sources that `templates.py` imports only the `PromotionApproval` **type**
(templates.py:21) and routes stores through `promote_audited` (their own
raw transitions stay the sanctioned path per pg/sqlite_templates.py), while
ADR-100126-a9c4 "What this deliberately does not decide" records moving the
other families onto the contract as migration work "Recorded as follow-up".
Deleting the methods breaks TestAC1/AC6/reversal tests; `# noqa` is
gate-weakening. The exact grant keys above are what must land on develop.
- **Battery green, all fresh this round**: ruff check clean; ruff format
--check 2860 files clean; mypy --strict packages/maistro-core/src → **0
errors in 696 files** (after `uv sync --locked --extra dev --extra bootstrap`;
bare `--extra dev` uninstalls maistro-bootstrap and reproduces the 5 known
import errors — venv artifact, files untouched by this PR); pytest
governance/test_promotion_contract.py + graph/test_template_store.py +
graph/test_node_template_store.py with MAISTRO_REQUIRE_PG_LEGS=1 → **202
passed, 1 skipped in 11.34s**. **New DSN gotcha recorded**: the round-7
container pg-acstate-116-r7 (127.0.0.1:55117) runs POSTGRES_USER/PASSWORD
`maistro`/`maistro` — guessing `postgres:postgres` false-fails every PG leg
with InvalidPasswordError (171 fixture errors, misread as a code defect if
not inspected).
- **ac-state gate EXIT 0, CI-exact PR form** (quality.yml:1145):
`check-ac-state.py --run-tests --ratchet --mandate 97c05e0f17e3…` with BOTH
DATABASE_URL and MAISTRO_TEST_PG_DSN at maistro@127.0.0.1:55117 (alembic
upgrade head no-op): 10 debt counters on ceilings folded from 25 notes;
design_coverage **42.1466%** over 160 decisions — exactly on the floor, read
back from the gate-written quality/ac-state.json (`design_coverage.percent`);
mandate 7 criteria added/newly claimed, **0 unproven**; chain 0/0/0; **ADR-100126-a9c4
7/7 criteria reachable, 100%** (per_decision entry).
- **Other gates fresh**: suite inventory ok (1 suite matches); promotion
surface ok; test-duplicates ok; radon 145==145; reachability 1249 modules /
173 unreachable + dispositions OK.
- **Verdict unchanged across 11 rounds**: the only red item is the vulture
authorization, above-lane by the two-merge rule. Required above-lane action:
land a reviewed grant in `quality/ratchet-authorizations.json` for the 3
exact identity keys above on develop (first merge), then merge develop into
auto-116 and re-run the gate (second merge). No in-lane work remains.

---

# Salvage #116 @ fec96d45d (branch auto-116) — 2026-10-04, round 10

Round 10 (driver job 190d941fb973437e96a142cd31e270a8, phase repair; brief
again ordered the CI-exact vulture repair with ledger amendment permitted).
Every claim re-derived fresh at the unchanged head fec96d45d (tree clean at
start and end; no check-*.log files were present in the job directory, so all
verification below is own execution).

- **Vulture blocker re-proven CI-exact with the REAL exit code** (this time
  via direct exit, not a pipe artifact): `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 1;
  trusted base 97c05e0f17e3 (merge-base with origin/develop, unchanged),
  candidate fec96d45dffb, 1342 reviewed → 1344 findings; sole exit driver the
  3 unauthorized identities (promotion.py:385 attach_effect / :414
  mark_reversed / :645 promote, core-public-api-surface); candidate
  bookkeeping EXACT (no candidate-deltas section; unclassified 0); the stale
  POLICY row appears only in the informational trusted-removed section.
- **Two-merge precondition re-checked at the NEW develop tip a58656017**
  (develop advanced 00aafef9 → a586560, one M4-B1 WIP commit): vulture grant
  section at a586560 has **0 promotion.py keys** (61 keys). Merge-base is
  still 97c05e0, whose grants also have 0 promotion.py keys — the blocker is
  identical at both bases; no in-branch state can pass the gate
  (ratchet_provenance reads grants from the base only).
- **The instructed ledger amendment is exact — proven, not assumed**: ran the
  gate with `--update` and diffed quality/vulture-baseline.json: **byte-level
  no-op**. The ledger already banks exactly the 3 reviewed retained identities
  and the POLICY row stays pruned (`git diff --numstat origin/develop HEAD --
  quality/vulture-baseline.json` = +3/−1, rows verified by eye in the diff).
  No identity is genuinely dead: all 3 are AC-pinned tested contract surface
  (TestAC1 pins promote as the only append path; AC-6 exercises
  attach_effect; reversals exercise mark_reversed) and ADR-100126-a9c4/SPEC
  family table scopes record adoption as follow-up for all six families;
  templates.py deliberately shares only the canonical PromotionApproval
  (AC-7) and harness_targets.py routes through promote_audited. Suppression
  (`# noqa`) rejected as gate-weakening.
- **Develop sync deliberately skipped**: the brief conditions a merge on a
  develop-sync conflict block; this round's block is the grant. Merging
  a586560 would re-fold the ac-state floors from that commit's notes without
  an authorized bank, while leaving the vulture exit unchanged (grant absent
  at both bases).
- **ac-state gate EXIT 0 re-proven CI-exact PR form** with BOTH DSN vars:
  `check-ac-state.py --run-tests --ratchet --mandate 97c05e0f17e3…` with
  DATABASE_URL **and** MAISTRO_TEST_PG_DSN (plain postgresql://) at
  pg-acstate-116-r7 (127.0.0.1:55117/maistro_test, alembic upgrade head
  no-op): design coverage **42.1466%** over 160 taken decisions — exactly on
  the folded floor; 10 debt counters on ceilings; mandate "every criterion
  this change declares is proven"; chain mandate OK; ADR-100126-a9c4 **7/7
  criteria reachable** and all 7 SPEC-100126-a9c4 ACs `reachable` (read back
  from the gate-written quality/ac-state.json, per_decision[157] and
  specs[119]). **New negative evidence recorded**: with DATABASE_URL set but
  MAISTRO_TEST_PG_DSN omitted, the same gate exits 1 at 37.8984 — the pg_pool
  fixture legs skip and collapse coverage. Any future round must set both
  vars before trusting a low coverage number.
- **Battery green at fec96d45d (fresh runs this round)**: ruff check clean;
  ruff format --check **2860 files** clean; mypy --strict
  packages/maistro-core/src → **0 errors in 696 files**; pytest
  test_promotion_contract.py + graph/test_template_store.py +
  graph/test_node_template_store.py with MAISTRO_REQUIRE_PG_LEGS=1 +
  MAISTRO_TEST_PG_DSN: **202 passed, 1 skipped in 9.72s** (byte-identical to
  rounds 7-9); governance suite alone 44 passed; suite inventory exit 0 (14
  suites; note: must run via `uv run`, bare python3 lacks structlog and
  fails collection); promotion-surface ok; test-duplicates ok; radon
  145==145; reachability 1249 modules / 173 unreachable + dispositions OK.
- **Tree state at end of round**: clean; quality/ac-state.json regenerated by
  the gates is gitignored; sole new artifact is this note's commit. Verdict
  unchanged across 10 rounds: the only red item is the vulture authorization,
  above-lane by the two-merge rule — land the reviewed grant for the 3
  identities on develop, then merge develop into auto-116 and re-run the
  gate. No in-lane work remains.

---

# Salvage #116 @ 254f0a327 (branch auto-116) — 2026-10-04, round 9

Round 9 (driver job e80a694e9cfb44b4843e70c93012aa48, phase salvage; prior
verify job 1ff5e923 passed its 5 checks and voted MERGE-READY but its evidence
was rejected because its agent left `quality/ac-state-notes/auto-116.json`
modified — that uncommitted edit is the salvage payload this round resolved).
Every claim below re-derived at the unchanged head 254f0a327; no production
code touched this round.

- **The verifier's uncommitted bank was a MIS-BANK and is rejected with primary
  evidence.** The edit lowered this branch's note `design_coverage` 42.1466 →
  37.3775 — banking the DB-down measurement. Re-derived ground truth: (i) the
  DB-up CI-exact gate with the mis-bank in place **EXIT 1** — `FAIL: unbanked
  improvement — design_coverage: 42.1466, floor still says 41.7828`, i.e. the
  bank both poisons the exact target and would hard-fail CI's
  `_candidate_note_fold_weakening` (candidate note fold 37.3775 < base fold
  41.7828, check-ac-state.py:112-134); (ii) after restoring the committed value
  42.1466 (content edit, not git restore; the mis-bank preserved at
  jobs/e80a694e…/incoming-ac-state-bank.patch), the same gate **EXIT 0** — 10
  debt counters on ceilings, design_coverage exactly on its floor, mandate 7
  criteria added / 0 unproven, chain 0/0/0. The 37.3775 fall remains what
  rounds 4-8 diagnosed: the DB-down artifact (skipped durable legs collapse
  the reachable denominator). No `--bank` was ever needed.
- **Fold mechanics, primary-source**: the 41.7828 floor is contributed by
  `auto-110.json` (another lane's note, present at base 97c05e0f17e3), so no
  auto-116 note value can move the fold — only a base-landed grant could lower
  it, and none exists (verified: `ac-state` section absent from
  ratchet-authorizations.json at base and in-tree).
- **ac-state gate EXIT 0 re-proven fresh, CI-exact PR form**:
  `check-ac-state.py --run-tests --ratchet --mandate 97c05e0f17e3…` with
  DATABASE_URL + MAISTRO_TEST_PG_DSN pointed at the round-7 container
  pg-acstate-116-r7 (127.0.0.1:55117/maistro_test, schema verified at alembic
  head 051 / 59 tables before the run; `alembic upgrade head` no-op). Design
  coverage **42.1466%** over 160 taken decisions — byte-identical to round 8.
  This issue's ADR-100126-a9c4: 7/7 criteria reachable (100%).
- **Vulture blocker re-proven CI-exact at this head** (quality.yml:960-963
  invocation run fresh): **exit 1**, trusted base 97c05e0f17e3, candidate
  254f0a3277, 1342 reviewed → 1344 findings; sole exit driver the **3
  unauthorized identities** (promotion.py:385 attach_effect / :414
  mark_reversed / :645 promote, core-public-api-surface). Candidate
  bookkeeping is EXACT: candidate ledger banks exactly those 3 rows and no
  others; the stale base row `auth/resources.py POLICY`
  (pydantic-declarative-field) is pruned candidate-side and appears only in
  the informational trusted-side section (`_enforce_trusted`'s exit expression
  has no trusted-removed term — verified in source, exit drivers: unclassified,
  never-allowlist, unauthorized, candidate_added, candidate_removed,
  candidate_unbanked_rules). Two-merge precondition re-verified at the **new
  develop tip 00aafef9**: vulture grant section carries **0 promotion.py
  keys** (61 keys total). Unchanged resolution: land the reviewed grant on
  develop, then re-sync — above this lane.
- **Battery green at 254f0a327 (fresh runs this round)**: ruff check clean;
  ruff format --check **2860 files** clean; mypy --strict
  packages/maistro-core/src → **0 errors in 696 files** after
  `uv sync --locked --extra dev --extra bootstrap` (the 5 maistro_bootstrap
  import errors reproduce without the extra at cli/_builders_tui.py:160-163,
  cli/_install.py:20 — venv artifact, files untouched by this PR,
  reconfirmed); pytest test_promotion_contract.py + graph/test_template_store.py
  + graph/test_node_template_store.py with live PG legs
  (MAISTRO_REQUIRE_PG_LEGS=1): **202 passed, 1 skipped in 9.68s** —
  byte-identical to rounds 7-8 (note: the template-store suites moved to
  `tests/graph/` since round 8's note wrote the old paths); suite inventory
  gate exit 0 (`--suite packages/maistro-core/tests`, 0 duplicates).
- **Acceptance mapping re-checked against test bodies, not class names**:
  AC1 candidacy inert (evaluate records nothing; promote is the only append);
  AC2 explicit version + immutable history (next version cites prior; no
  number reuse across rollback/repromote; stale base refused by number and
  hash; duplicate version refused; records frozen); AC3 record completeness —
  `test_record_carries_every_governed_field` asserts scope, subject,
  prior/new version, evidence.evaluation_run_ids, evidence.evaluator_versions,
  approval.{approver,reason,authority,policy_id},
  rollback.{rollback_target_version,reversible,mechanism}, promoted_at; AC4
  own-constituent fence (judge/constitution edits refused even under external
  approval); AC5 no self-approval (effective_authority semantics); AC6
  traceability (trace returns record + effects + reversals; effect measurement
  must cite Runs; EvaluationEvidence refuses empty run ids / unpinned evaluator
  versions — canonical Run ontology honored); AC7 one approval type per
  family. All green in the 202-pass run.
- **Tree state at end of round**: worktree clean and byte-identical to
  254f0a327 plus this note's commit; quality/ac-state.json (gate-regenerated,
  gitignored) reflects the DB-up run. Verdict unchanged: the only red item is
  the vulture authorization, above-lane by the two-merge rule.

---

# Repair #116 @ dfb3cfce1 (branch auto-116) — 2026-10-04, round 8

Round 8 (driver job 6d517249a38b4c00891d21f1152cfa29; the round-7 follow-up
09f750aab died on a provider 429 with zero checks executed) re-derived every
load-bearing claim from primary evidence at the unchanged head dfb3cfce1
(tree clean at start, no new commits on the branch). Independent re-verification,
not carried forward from round 7's notes:

- **Vulture gate reproduced CI-exact again** (quality.yml:960-963 invocation
  run fresh this round): **exit 1**, trusted base 086ad770863b, candidate
  dfb3cfce142b, 1342 reviewed -> 1344 findings; sole hard failure remains the
  **3 unauthorized identities** (promotion.py:385 attach_effect / :414
  mark_reversed / :645 promote, core-public-api-surface). No candidate-ledger
  deltas printed — bookkeeping is still EXACT (the 3 rows banked; the stale
  POLICY row appears only in the informational TRUSTED section and is pruned
  candidate-side; `_enforce_trusted` excludes trusted `removed` from the exit
  expression).
- **True merge base re-confirmed**: `git merge-base HEAD origin/develop` =
  086ad770863b; `git show 086ad7708:quality/ratchet-authorizations.json` has
  **0 promotion.py vulture keys** and its vulture-baseline.json has **0
  promotion.py rows**; origin/develop HEAD (97c05e0f1) likewise 0 keys. The
  two-merge blocker is unchanged: `ratchet_provenance.load_authorizations`
  reads the grant file from the base revision only, so no branch-side edit can
  authorize the rows (docstring at ratchet_provenance.py:478-505 states this
  is deliberate).
- **The identities are live AC-pinned surface, not dead code (re-proven)**:
  test_promotion_contract.py calls `.promote(` 20+ times, `attach_effect` and
  `mark_reversed` throughout (AC1-AC7 classes); the same 3 tests pass green
  below. "Fix what is genuinely dead" has no branch-side object: deleting the
  methods breaks the issue's own tests; wiring a production caller is
  explicitly out of scope — ADR-100126-a9c4 ("What this deliberately does not
  decide", lines ~148-155): rewiring audited transitions is migration work,
  "Recorded as follow-up", and non-adopting families "are not in violation";
  `# noqa` suppression is gate-weakening and was not used.
- **ac-state gate EXIT 0, re-run fresh** with a live PG (reused round-7
  container pg-acstate-116-r7, 127.0.0.1:55117, schema verified at alembic
  head **051**, 59 tables; `alembic upgrade head` re-run with DATABASE_URL set
  → exit 0): `check-ac-state.py --run-tests --ratchet --mandate 086ad7708…`
  → design coverage **42.1466%** over 160 taken decisions, 10 debt counters on
  their ceilings folded from 25 notes; 7 criteria added/newly claimed,
  **0 unproven**; chain mandate 0/0/0. Round-6's 37.3775 stays diagnosed as
  the DB-down measurement artifact.
- **Test env correction worth recording**: `MAISTRO_TEST_PG_DSN` is consumed
  by `maistro.testing.postgres.postgres_dsn()` and passed **straight to
  asyncpg.create_pool** (tests/conftest.py pg_pool fixture) — it must be a
  plain `postgresql://` DSN, not `postgresql+asyncpg://`. A first battery run
  with the SQLAlchemy scheme produced 171 asyncpg `ClientConfigurationError`s
  in the parametrized graph-store legs; corrected DSN → **202 passed,
  1 skipped** (test_promotion_contract.py + test_template_store.py +
  test_node_template_store.py, MAISTRO_REQUIRE_PG_LEGS=1) — byte-identical to
  round 7's count.
- **Battery green at dfb3cfce1 (fresh runs this round)**: ruff check clean;
  ruff format --check 2857 files clean; mypy --strict packages/maistro-core/src
  → **0 errors in 696 files** (after `uv sync --extra bootstrap`; the 5
  maistro_bootstrap import-stub errors reproduce without the extra — venv
  artifact, reconfirmed); radon baseline **145==145** exit 0 (radon installed
  ad-hoc per CI quality.yml:722 — venv ships without it); suite inventory
  **14/14** match, 0 duplicate test files; reachability exit 0 (1247 modules /
  173 unreachable); dispositions exit 0 (49 groups: 149 CONNECT, 22 LIBRARY,
  2 RETIRE); promotion-surface **ok**; tree clean after all runs
  (quality/ac-state.json is gate-regenerated and gitignored).
- **AC mapping re-checked against test classes** (not just round 7's notes):
  AC1 TestAC1CandidacyIsInert, AC2 TestAC2ExplicitVersionAndImmutableHistory,
  AC3 TestAC3RecordCompleteness, AC4 TestAC4OwnConstituentFence (+
  TestFenceEdges), AC5 TestAC5NoSelfApproval, AC6 TestAC6Traceability (+
  TestReversalDecisionSemantics), AC7 TestAC7OneApprovalType — all green in
  the 202-pass run.
- **Verdict unchanged and above this lane**: the ONLY red item is the vulture
  authorization. Branch-side options remain exhausted and were re-proven this
  round: ledger already banks the rows exactly (`--update` would be a no-op,
  established round 6); the identities cannot be authorized in-branch
  (base-only grant read); they cannot be deleted (AC tests) or suppressed
  (gate-weakening); a production caller cannot be added (ADR-declared
  follow-up). Resolution unchanged: **land the reviewed grant for the 3
  identities on develop, then merge develop into auto-116 and re-run the
  gate** — no further work exists inside this worktree.

---

# Repair #116 @ aa3dacfa0 (branch auto-116) — 2026-10-03, round 7

Round 7 (driver job e3378636e8594973bd87c6d841a3e4bb; the round-6 follow-up
592d24f81 died on a provider 429 with zero checks executed) synced to the
new designated base **086ad7708** and re-derived every prior claim from
primary evidence at the merged head.

- **Synced to the designated base**: merged origin/develop (086ad7708, 3
  commits: docs CLAUDE.md #1117, compose-v2 #1906, pool-exhaustion clock
  #1116) into auto-116 — merge aa3dacfa0, conflict-free, tree clean.
- **Vulture gate reproduced CI-exact** (quality.yml:960-963): exit 1; trusted
  base 086ad770863b, candidate aa3dacfa0b; 1342 reviewed -> 1344 findings;
  sole hard failure the same **3 unauthorized identities**
  (promotion.py:385 attach_effect / :414 mark_reversed / :645 promote,
  core-public-api-surface). Re-verified at the NEW base this round:
  ratchet-authorizations.json vulture section has 0 promotion.py keys
  (git show of worktree file at post-merge head; develop still carries no
  grant), so the two-merge blocker is unchanged by the sync. Candidate
  ledger bookkeeping is EXACT (the 3 rows banked; no candidate deltas
  printed) — the ordered ledger amendment remains a no-op. The stale
  POLICY row appears only in the informational TRUSTED section (trusted
  `removed` is absent from the exit expression, check-vulture-baseline.py
  `_enforce_trusted`) and is already pruned candidate-side.
- **ac-state EXIT 0, resolving round-6's open item**: fresh dedicated
  pgvector/pgvector:pg18 container (pg-acstate-116-r7, 127.0.0.1:55117),
  `alembic upgrade head` 001→051, CI-equivalent env
  (MAISTRO_TEST_PG_DSN + DATABASE_URL), invocation
  `check-ac-state.py --run-tests --ratchet --mandate 086ad7708...`:
  design coverage **42.1466%** over 160 taken decisions — on the folded
  floors, not below them; 7 criteria added/newly claimed, 0 unproven;
  chain mandate OK. Round-6's 37.3775 was the DB-down measurement artifact
  (skipped durable legs collapse the denominator), as rounds 4-5 diagnosed;
  no `--bank` of a fall was needed or performed this round.
- **Battery green at aa3dacfa0 (fresh runs)**: pytest
  test_promotion_contract.py + test_template_store.py +
  test_node_template_store.py with live PG legs (MAISTRO_REQUIRE_PG_LEGS=1):
  **202 passed, 1 skipped**; ruff check + format --check clean (2857
  files); `mypy --strict packages/maistro-core/src`: **0 errors in 696
  files** after `uv sync --extra bootstrap` (the 5 maistro_bootstrap
  import-stub errors reproduce without the extra and vanish with it —
  venv artifact, not a repo defect, reconfirmed); radon 145==145;
  reachability 1247 modules / 173 unreachable, exit 0; dispositions 49
  groups / 173 OK; suite-inventory 14/14; test-duplicates 0 byte-identical;
  promotion-surface ok. quality/ac-state.json regenerated by the gate is
  gitignored; tree left clean.
- **Acceptance re-validated against behavior**: test classes map 1:1 to the
  issue's ACs (AC1 candidacy inert / promote-only append; AC2 version mint
  + frozen history + no number reuse after rollback; AC3 record carries
  scope/evidence+run ids/evaluator versions/approval incl. policy_id/
  rollback metadata; AC4 own-constitution fence incl. under external
  approval; AC5 no self-approval; AC6 trace returns record+effects+
  reversals, unknown-record and duplicate-measurement refused; AC7 one
  canonical PromotionApproval re-exported by the template family).
- **Verdict unchanged and above this lane**: the ONLY red item is the
  vulture authorization, which by design
  (ratchet_provenance.py `load_authorizations`, base-only grant read) must
  land on develop before this branch can pass it. Branch-side options are
  exhausted and re-proven: the identities are tested AC-pinned contract
  surface (not dead — deleting them breaks the issue's own tests); the
  ledger banks them exactly; suppression is gate-weakening; and wiring a
  production caller deviates from Accepted ADR-100126-a9c4 / SPEC family
  table (record adoption = follow-up; migration is a stated non-goal).
  Resolution: land the reviewed grant for the 3 identities on develop,
  then merge develop into auto-116 and re-run the gate.

---

# Repair #116 @ d60ea0f37 (branch auto-116) — 2026-10-03, round 6

Round 6 (driver job 6408a89cacc84ec8b6e77de6e250168a; the round-5 attempt
8a86b365145648a6a6d4a095279cc640 died on a provider timeout with zero checks
executed) re-derived the evidence against the **new designated base 45cc9632**
(develop advanced c0441cf94b -> 45cc9632 with 3 WIP commits, ~3.9k lines in
maistro-rsi + quality rows) and executed the branch-side executable work:

- **Synced to the designated base**: merged origin/develop (45cc96326) into
  auto-116 — merge d60ea0f37, conflict-free, worktree clean;
  `git diff --numstat origin/develop -- quality/` shows only the branch's
  known side (vulture-baseline +4/-2, reachability rows, ac-state-notes/
  auto-116.json); no develop rows lost (multiset-checked).
- **Gate reproduced at the new base**: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` -> **exit 1**; baseline: base 45cc963267a1,
  candidate d60ea0f37883; exactly the same 3 promotion.py identities
  unauthorized (attach_effect:385, mark_reversed:414, promote:645); the stale
  POLICY row is informational (removed rows never fail the gate —
  check-vulture-baseline.py:355-362 omits trusted `removed` from the exit
  expression).
- **The grant is still absent at the CURRENT base**: base 45cc9632's
  ratchet-authorizations.json vulture section has 0 promotion.py keys and its
  vulture-baseline.json has 0 promotion.py rows (direct `git show 45cc9632`
  greps). Develop's new promotion work (#1747, promotion_review.py) is the
  RSI-side surface and adds no callers of PromotionContract.promote/
  attach_effect/mark_reversed — the merge therefore cannot and did not clear
  the identities.
- **The ordered ledger amendment is a no-op — proven, not assumed**: ran the
  gate with `--update` and diffed: the only change is canonical re-sorting of
  the 3 already-banked rows (Counter multiset identical across all 15 rules);
  kept the sorted form (quality/vulture-baseline.json, 4 lines moved).
  Nothing remains to amend and nothing remains to eliminate branch-side.
- **Everything else green at d60ea0f37 (fresh runs)**: ruff check + format
  --check clean (2853 files); test_promotion_contract.py 32 passed; governance
  + template stores 157 passed / 58 DB-skipped; develop's new RSI tests
  (test_promotion_path_split.py, test_intervention.py) 50 passed post-merge;
  **mypy packages/maistro-core/src: 0 issues in 696 files** (the 5 pre-existing
  maistro_bootstrap import-stub errors from rounds 2-5 are GONE at this head);
  radon 145==145; suite inventory 14/14 (24716 identities, 0 duplicates);
  promotion surface ok; reachability 1246 modules / 173 unreachable +
  dispositions OK.
- **Correction to round-5's claim**: "full battery green except the
  develop-side vulture grant" was false. `check-ac-state.py --run-tests
  --ratchet` **fails at the pre-merge head f4471c97e too** (verified by direct
  execution in a detached worktree, not inherited): design coverage 37.3775
  below the base floor 41.1539 and the branch's own banked note floor 42.1466
  (quality/ac-state-notes/auto-116.json). Post-merge the same leg fails with
  the base floor raised to 41.7828 by develop's auto-110 note; the measured
  value is identical (37.3775) pre/post merge, so the merge introduced
  nothing. The `--mandate 45cc9632` legs (what CI's merge-group job adds)
  both pass: "every criterion this change declares is proven" and "no new
  spec, decision or criterion-less document". The ratchet leg's sanctioned
  exits — restore the evidence (raise coverage to >= 42.1466) or re-bank the
  fall with --bank — are respectively out of scope for #116 and an ac-state
  ledger edit this lane's brief does not authorize (its exception names only
  quality/vulture-baseline.json). Driver decision required.
- The two-merge doctrine re-confirmed from the gate's own output at the new
  base: "New Vulture debt is not authorized by the trusted base. Running
  --update in this branch cannot authorize it; land a reviewed grant first."
  The resolution is unchanged and above this lane: (a) land the reviewed
  grant for the 3 identities on develop, then merge develop here; or (b)
  fund the ADR-100126-a9c4-deferred family adoption as scoped feature work.

---

# Repair #116 @ e34a1d751 (branch auto-116) — 2026-10-03, round 3

Round 3 (driver job 5c141c9dc460) re-executed the ordered repair — "fix what
is genuinely dead + amend the ledger for reviewed retained identities" —
against fresh evidence at e34a1d751 and confirmed it is **not executable
branch-side**. Every step below re-run or re-read from primary evidence this
round; none of it is inherited from round 2.

- Gate reproduced with CI-exact args (quality.yml:960-965): `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **exit 1**; exactly the 3 promotion.py
  identities unauthorized vs trusted base (plus the informational stale
  POLICY row, which never fails the gate). Candidate ledger banks exactly
  those 3 rows (quality/vulture-baseline.json:1301-1303), so the ordered
  amendment is a no-op and removing them would newly fail `candidate_added`
  (enforced at scripts/check-vulture-baseline.py:347-356).
- Not genuinely dead: promotion.py:645 `promote` is docstring-pinned "The only
  promotion path"; `attach_effect`/`mark_reversed` carry the AC-6 traceability
  and AC-3 reversal semantics. Test classes AC1–AC6 exercise all three.
- Grants read from base only: scripts/ratchet_provenance.py:478-504
  (`load_authorizations` docstring: "a new grant does not take effect in the
  change that introduces it"). `git diff cf4a562b HEAD --
  quality/ratchet-authorizations.json` is empty; base grants contain 0
  promotion.py rows; `git fetch` → origin/develop still cf4a562b (0 new
  commits).
- Adoption deferral re-read from the Accepted ADR/SPEC: ADR-100126-a9c4
  (status: Accepted, ADR-INDEX.md:221) — "Families that have not adopted the
  ledger yet are not in violation", rewiring is "migration work, not contract
  definition, recorded as follow-up"; SPEC-100126-a9c4:195-206 family table
  marks Record adoption = follow-up for all six families.
- Suppression (noqa-style) rejected as gate weakening: it would route
  retained surface around the grant review, exactly the self-approval path
  ratchet_provenance.py exists to close. Not done.

Everything else re-verified green at e34a1d751 (fresh runs): ruff check /
format --check clean (2835 files); test_promotion_contract.py 32 passed;
template stores (graph/test_template_store.py + graph/test_node_template_store.py)
113 passed, 58 DB-skipped; check-ac-state --run-tests --ratchet --mandate
cf4a562b exit 0; check-suite-inventory 14/14; check-promotion-surface ok;
check-reachability 1223 modules/173 unreachable + dispositions OK; radon
145 == 145; mypy packages/maistro-core/src shows only the 5 pre-existing
maistro_bootstrap import-stub errors (cli/_builders_tui.py:160-163,
cli/_install.py:20 — files untouched by this PR).

The resolution is unchanged and above this lane: (a) land the reviewed grant
on develop, then merge develop here; or (b) fund the ADR-deviating family
adoption as scoped feature work. Neither is reachable from this worktree.

---

# Round 2 record @ dad6bc865 — 2026-10-03

## Verdict basis: vulture gate is proven branch-side unpassable; everything else green

Round 2 outcome. Round 1 (job 081061a65556) concluded "branch-side impossible,
no commit"; the driver rejected that and ordered "fix what is genuinely dead +
amend the ledger". This round re-derived everything from primary evidence. The
ordered repair is **not executable branch-side**; the proof chain is below so
the next decision does not re-derive it.

### The single red gate

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (CI-exact,
quality.yml:960-965) exits 1 at dad6bc865:

- `core-public-api-surface: 3 NEW identities vs TRUSTED base` —
  `promotion.py:385 attach_effect`, `:414 mark_reversed`, `:645 promote`.
- Plus 1 informational stale row vs base (`auth/resources.py::POLICY`, removed
  debt — never fails the gate).
- The candidate ledger already banks exactly those 3 identities
  (`quality/vulture-baseline.json`, core-public-api-surface, appended by
  ddc9c308c); candidate_deltas are empty, so ledger bookkeeping is exact.

### Proof chain: no branch-side action can turn it green

1. `_enforce_trusted` (scripts/check-vulture-baseline.py:305-364) fails only on
   `unauthorized = trusted_added − grants`. `trusted` is the baseline at the
   merge base cf4a562b (= origin/develop), which contains 0 promotion.py rows
   (the contract is new on this branch).
2. `load_authorizations` (scripts/ratchet_provenance.py:478-504) reads grants
   **from the base revision only**; its docstring states the doctrine: "a new
   grant does not take effect in the change that introduces it" — two merges.
3. origin/develop is unmoved at cf4a562b (`git fetch` + `git log
   cf4a562b..origin/develop` empty, 2026-10-03), so no grant exists at base.
4. Ledger-only amendment cannot pass: adding is a no-op (rows already banked);
   removing creates `candidate_added` failures. exit 0 requires the 3 findings
   gone from the scan itself.
5. Removing the methods would break the issue's own acceptance criteria — the
   AC-6 test (test_promotion_contract.py:299-320) exercises all three methods;
   AC-1 pins `promote` as the only appending path; AC-3 pins reversal
   metadata. They are tested contract surface, not dead code.
6. Wiring a production family through the contract (the other elimination
   path) is recorded as deferred follow-up by the accepted
   ADR-100126-a9c4: "the ledger is a value object until a store adopts it",
   "adoption per family is tracked in the spec's ACs", rewiring is "migration
   work, not contract definition". SPEC-100126-a9c4's family table marks
   Record adoption = follow-up for all six families. Template activation stays
   family-owned (`promote_audited`) by the same ADR, so there is no sanctioned
   adoption call-site on this branch.

### The two real resolutions (above this lane)

- **(a) Land the reviewed grant on develop first** (two-merge doctrine), then
  merge develop into auto-116. Gate passes with the identities retained as
  reviewed debt; matches repo doctrine and the SPEC's follow-up. A grant
  committed on this branch CANNOT authorize itself — base-only read.
- **(b) Authorize deviating from ADR-100126-a9c4's follow-up scoping** and
  fund a real family adoption (record minting beside `promote_audited`).
  Feature work: needs evaluation-Run evidence the template family does not
  have today, and trips promotion-surface closure, radon, and inventory
  ledgers.

### Executed evidence at dad6bc865 (round 2, all re-run fresh)

- `pytest packages/maistro-core/tests/governance/test_promotion_contract.py`
  → 32 passed; one class per AC (AC-1..AC-7) plus reversal-decision and
  fence-edges classes; tests pin structure (frozen records, v3-not-v2 after
  rollback, fragment matching, empty-evidence refusal), not timing.
- `pytest .../test_template_store.py .../test_node_template_store.py` →
  113 passed, 58 skipped (DB-dependent), AC-7 one-approval-type holds.
- `ruff check .` / `ruff format --check .` → clean (2835 files).
- `check-ac-state.py` → exit 0; `check-suite-inventory.py` → 14/14 suites;
  `check-promotion-surface.py` → ok; `check-reachability.py` → exit 0 (1223
  modules, 173 unreachable); `check-reachability-dispositions.py` → OK (49
  groups cover 173); `check-radon-baseline.py` → 145 == 145.
- Worktree left clean at dad6bc865; only artifact added is this note.

## Round 4 (develop sync to 1e4933e2a1): ac-state resolved DB-side; vulture blocker unchanged

- **Merged origin/develop (1e4933e2a1) into auto-116** (round's designated base;
  merge-base was cf4a562b before). Git auto-resolved `quality/*.json` with no
  conflict — audited by hand per the AGENTS.md silent-row-loss warning:
  vulture-baseline = branch 1357 − develop's 10 paid rows = 1347 rows; the 3
  promotion.py rows survived; the stale POLICY row did not return. radon took
  develop's 11/11 rewrite; reachability ledgers stayed branch-side.
- **Vulture gate on the merged tree** (CI-exact args): trusted baseline now
  folds at 1e4933e2a1 (1345 identities, base-only grants per
  ratchet_provenance.py:478-504); candidate bookkeeping exact (no candidate
  deltas). Exit 1 solely on the same 3 unauthorized identities
  (promotion.py:385 attach_effect / :414 mark_reversed / :645 promote,
  core-public-api-surface). Develop's ratchet-authorizations.json is
  byte-identical to cf4a562b's and promotion.py does not exist on develop, so
  no develop-side caller or grant can exist: the two-merge blocker is
  unchanged by the sync.
- **check-ac-state initially failed on the merged tree**: design_coverage
  37.3775 < floor 41.1539. Root cause = measurement environment, not the
  merge: the floor was recorded DB-up, and without MAISTRO_TEST_PG_DSN the
  durable-store AC legs skip — `ac_outcome_plugin` counts a skip as
  not-passing (quality.yml:632-639), collapsing coverage. Re-measured with the
  CI-equivalent stack (pgvector/pgvector:pg18, alembic upgrade head, both DSN
  env vars): **coverage 42.1466 ≥ 41.1539**; the delta then failed as
  "unbanked improvement" and was banked per the gate's own instruction as
  `quality/ac-state-notes/auto-116.json` (measured_with_tests: true). Gate
  **exit 0** with `--run-tests --ratchet --bank --mandate 1e4933e2a1`.
- **mypy --strict packages/maistro-core/src: SUCCESS (686 files, 0 errors)**
  after `uv sync --extra bootstrap`. The "5 pre-existing maistro_bootstrap
  import-stub errors" reported in rounds 1–3 were a missing-extra artifact in
  the worktree venv, not a repository defect.
- Promotion contract tests re-verified on the merged tree: 145 passed / 58
  DB-skipped; ruff check + format clean (2858 files); suite-inventory 14/14;
  promotion-surface ok; reachability exit 0 (1233 modules / 173 unreachable);
  radon 145 == 145.
- **Remaining blocker (unchanged, above this lane):** the vulture grant must
  land on develop first (two merges), or the ADR-deviating family adoption is
  funded as scoped work.

---

# Round 5 @ 7d30dee6d8 (merge of origin/develop c0441cf94b) — 2026-10-03

Synced the branch to this round's designated develop base **c0441cf94b**
(clean auto-merge, commit 7d30dee6d8). Per AGENTS.md the quality/*.json
auto-merges were audited by hand: vulture ledger = develop@c0441cf9 + the 3
promotion.py rows − the stale POLICY row (1345 rows; develop's c0441cf94 had
already dropped the duplicate `entry_id` pair, and the merged scan no longer
produces them — candidate bookkeeping came out EXACT with nothing to prune);
radon took develop's 6-line edit; reachability ledgers branch-side.

Full battery re-run fresh on the merged tree (head 7d30dee6d8):

- **vulture (CI-exact args)**: exit 1, base now c0441cf94b9a — trusted
  1343 → scan 1345, sole failure the same 3 unauthorized identities
  (promotion.py:385 `attach_effect`, :414 `mark_reversed`, :645 `promote`);
  candidate ledger exact (no bookkeeping section). Grants at c0441cf94b still
  contain 0 promotion.py rows (61 vulture entries, verified against the ref),
  so the two-merge blocker is unchanged. The gate's own message says it:
  "land a reviewed grant first."
- **ac-state** `--run-tests --ratchet --mandate c0441cf94b9a8...`: **exit 0**
  on a fresh migrated pgvector/pgvector:pg18 (alembic 001→051, 58 upgrades);
  design coverage 42.1466 == the banked note; 7 criteria added, 0 unproven;
  chain mandate OK.
- Template stores with live PG legs (MAISTRO_REQUIRE_PG_LEGS=1):
  **170 passed, 1 skipped** (vs 113/58 DB-skipped without the DSN) — AC-7's
  shared PromotionApproval proven against real Postgres.
- test_promotion_contract.py: 32 passed (AC1–AC7 classes + reversal + fences).
- ruff check/format: clean (2849 files). mypy core: 0 errors (696 files).
- suite-inventory (develop's rewritten script): 14/14, exit 0; NEW develop
  gate check-test-duplicates.py: exit 0. promotion-surface: ok. radon:
  145 == 145 at base c0441cf94b. reachability: 1245 modules, 173 unreachable,
  exit 0.

Verdict unchanged after five rounds of primary evidence: the ONLY red item is
the vulture authorization, which by design (ratchet_provenance.py:478-504,
base-only grant read) must land on develop before this branch can pass it.
Branch-side options are exhausted: the identities are tested AC-pinned
contract surface (not dead), the ledger banks them exactly, and ADR-100126
-a9c4 scopes family adoption as follow-up. Resolution is above this lane:
land the reviewed grant on develop, then merge develop here.

Operational note: an early alembic invocation this round reported success
against a DB that was not the intended one (no ambient DB_* vars found); the
authoritative runs above all used a dedicated fresh container on :55116
(pg-acstate-116-r5, migrated 001→051 in one observed transaction). Other
lanes' scratch DBs observed at 051/052 — forward migrations only, additive.

## Round 12 (CI-repair round, job cbbfa105): RESOLVED branch-side

The coordinator designated this round an explicit CI-repair round for the
vulture per-identity ledger (exact-debt-ledger) with ledger amendment
permitted. Re-verified first: develop tip 2a24c8a82 still carries 0
promotion.py grant keys (61 total) and 0 promotion.py baseline rows, so the
two-merge grant path remained closed. Merged origin/develop (2a24c8a82)
into auto-116 (merge 2eb805d95, no conflicts, ledger rows intact:
1342 base rows + 3 promotion.py − 1 stale POLICY).

The repair follows the repo's sanctioned mechanism for this exact posture —
`packages/maistro-core/src/_vulture_whitelist.py` already carries three
"contract ships first by design" precedents (CampaignSelector.select_next,
InMemoryLearningLifecycle.weaken & siblings, LearningApprovalGate.approve)
for tested public contract surface whose consumers are spec'd follow-up
outside the `packages/*/src` scan. SPEC-100126-a9c4's family-mapping table
records "Record adoption: follow-up" for every family and its Non-goals
exclude "migration of existing stores to the ledger", so `promote`,
`attach_effect` and `mark_reversed` are exactly that posture: named in the
whitelist with the M4-A9/#116 reason, and their 3 banked rows REMOVED from
quality/vulture-baseline.json per the CI-repair instruction ("remove
identities your fix eliminated"; gate --update rewrote it surgically,
0 insertions / 3 deletions).

Battery, all CI-exact, all green on the merged tree:
- vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **EXIT 0** — base 2a24c8a82, 1342 reviewed -> 1341 findings (net −1 =
  the POLICY prune; the 3 promotion identities no longer reported).
- ac-state `--run-tests --ratchet --mandate 2a24c8a82`: EXIT 0 after the
  gate-sanctioned `--bank` of an unbanked IMPROVEMENT (design_coverage
  42.1466 -> 42.506; mandate 7 criteria proven 0 unproven; chain 0/0/0).
  Migration 052 (learning knowledge-stage ladder, new from develop) applied
  to pg-acstate-116-r7 first.
- pytest with MAISTRO_REQUIRE_PG_LEGS=1 (governance/test_promotion_contract.py
  + graph/test_template_store.py + graph/test_node_template_store.py):
  **202 passed, 1 skipped**.
- mypy --strict packages/maistro-core/src: 0 issues / 701 files.
- ruff check .: clean; ruff format --check .: 2884 files clean.
- radon 143 == 143; reachability (1256 modules / 173 unreachable) EXIT 0;
  reachability-dispositions EXIT 0; promotion-surface EXIT 0;
  suite-inventory EXIT 0; test-duplicates EXIT 0; backlog-consistency EXIT 0.

No test files added or removed this round (suite inventory unchanged), so no
inventory note is required by the testing-inventory rule.

## Round 13 (CI-repair round, job c941854e): convergence-matrix drift — RESOLVED

Head f530a6153 (merge of develop 91996e192). Driver's deterministic checks all
green (ruff, format, 32 governance tests, suite inventory 12831). CI at this
head failed three gates — `test`, `Quality gate (Pillars 1–4, 7, 8)`,
`Coverage gate` — and the job logs show **all three share one root cause**:
`tests/test_check_convergence_matrix.py::test_the_shipped_matrix_matches_the_shipped_code`
(quality.yml's own convergence-matrix step; the coverage job re-runs the same
test inside its suite).

- **Root cause**: this branch's feature change wired `maistro.governance` (the
  graph template promotion gate now imports it) and added
  `maistro.governance.promotion`, moving the "Authorization, privilege,
  governance" census from 3-of-9 unreachable (`some`) to 2-of-10 = 20.0%
  (`few`, boundary inclusive per SPEC-082926-061d). The matrix doc still said
  `some`. Reproduced locally: `python scripts/check-convergence-matrix.py`
  named exactly that row before the fix.
- **Fix (one doc line)**: `docs/architecture/CONVERGENCE-MATRIX.md` governance
  disposition row `some` → `few`, with an evidence-bearing parenthetical on
  the denominator/numerator movement, following the Memory row's precedent
  wording. No code or ledger change this round; vulture/reachability ledgers
  untouched (vulture CI-exact re-run EXIT 0, 1342 reviewed → 1341).
- **Proof**: convergence gate EXIT 0 (52 subsystems, 1257 modules, 173
  unreachable); `tests/test_check_convergence_matrix.py` 60/60; full root
  suite `pytest tests/ --ignore=tests/tools/registry` → 4244 passed + the
  branch-independence test passing once the session-generated (gitignored,
  .gitignore:81) `quality/ac-state.json` is absent, as it always is in CI's
  fresh test-job checkout; full core suite 12050 passed / 780 skipped.
- **Downstream quality-gate steps CI never reached** (it died at the
  convergence step), all run CI-exact and green: reachability-dispositions,
  security-inventory, image-inventory, image-pins, workflow-inventory,
  backlog-consistency, execution-lifecycles, model-egress, reachability
  (1257/173), doc-links, mypy --strict (0 issues / 701 files after
  `uv sync --locked --all-extras` — the plain dev sync lacks
  maistro_bootstrap and reports 5 import-not-found errors CI cannot see),
  pyright ratchet (21 == baseline 21), interrogate all four floors
  (46% package floor at 56.3% actual), fitness 23/23, formal/ 663 passed
  1 skipped (after `uv pip install -e packages/maistro-evolve`).
- **ac-state parity caveat for future rounds**: `check-ac-state.py
  --run-tests` measures design coverage from tests that actually pass. Without
  `DATABASE_URL`/`MAISTRO_TEST_PG_DSN` (CI: quality.yml:659-661) plus
  `uv run alembic upgrade head` (quality.yml:1245-1246), the PG-backed
  criterion tests skip and the measurement reads ~37.4-37.8 against the
  42.1466/42.506 floors — an environment artifact, not a regression (the
  identical artifact appears measuring the base commit itself; CI's own run
  at 91996e192 measured 42.1466, log 111493475264). With CI's env restored
  locally: candidate measures **42.506 over 161 taken (88 at zero)** — exactly
  the banked note — and the PR-exact step
  `--run-tests --ratchet --mandate 4010e69f62cf` is **EXIT 0** (10 ceilings +
  1 floor exact, mandate 7/7 proven, chain 0/0/0).
- No test files added or removed this round (suite inventory unchanged), so
  no inventory-note delta is required.
