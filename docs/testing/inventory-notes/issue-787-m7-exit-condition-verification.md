# issue-787-m7-exit-condition-verification

Verification evidence pack for milestone #787 (`[MILESTONE M7] Closed-loop
design process`). Round 2: the branch was synced to the assigned develop base
`ab8b3737fa64f8d840f421ef87ca506c509444ff` (clean merge; the M7 leaf PRs
#1676/#1678/#1680/#1681/#1691/#1698 landed on develop between rounds), and
every exit condition was re-verified against reachable tree behavior and real
test runs at the merged head. No tests were added, removed, or moved by this
note; it records a verification pass only.

#787 is a milestone tracker. Its body delegates all implementation to the
live hierarchy: #788 (initiative) → #789 (epic) → leaves #790–#796, each with
its own `feat/m7-a*` branch off `develop`. This lane verifies the milestone
exit conditions against reachable tree content and records the dispatch
state; it does not re-own leaf scope on the milestone branch.

## Exit-condition evidence (tree at develop@ab8b3737f, merged)

1. **Rubric as first-class versioned ontology object bound to a Goal
   revision — MET.** `maistro.ontology.rubric` (kind slug `rubric`) defines
   `RubricSemantic` with per-revision entity ids, exact `goal_id` +
   `goal_revision` binding, ordered weighted dimensions, veto ids and
   pass/fail gate; `maistro.projects.rubric_store.RubricStore` persists it
   over any Project-scoped Ontology. Distinct from persona `RubricEval`
   (ADR-060) and from CreativeBrief. Landed via #1678 (M7-A2, leaf #791).
   Evidence: `uv run pytest packages/maistro-core/tests/ontology -q` —
   63 passed (includes `test_rubric_model.py`,
   `test_rubric_contracts.py`, `test_design_loop_kind_fencing.py`; the
   38-test rubric+fencing subset re-run alone also passed).
2. **Eval scores on the producing Run/NodeRun/Attempt stream — MET.**
   `RunEvalScore` (`maistro/runs/model.py`) names the scored NodeRun and
   Attempt plus exact Goal/Rubric revisions; all three stores append behind
   `validate_eval_score_spine` (`maistro/runs/store.py`) — Run, NodeRun,
   Attempt must agree or the record is refused; records are append-only;
   `eval_summary` derives completeness only from persisted records;
   `open_re_eval_attempt` opens the retry Attempt on the same NodeRun.
   Landed via #1681 (M7-A3, leaf #792). Evidence:
   `uv run pytest packages/maistro-core/tests/runs/test_eval_on_run.py -q`
   with a real Postgres (`MAISTRO_TEST_PG_DSN` against a pgvector/pg18
   container, alembic `upgrade head` applied) — **34 passed, 0 skipped**
   (memory + sqlite + postgres legs all green).
3. **Product/game/book as domain packs of one Run — MET.**
   `maistro_design.packs` ships the closed `PackId` enum with in-repo
   manifests `product.yaml` / `game.yaml` / `book.yaml`, default Rubric
   catalogs instantiated onto a canonical Goal (pack never owns Rubric
   identity), Graph shapes projected onto canonical GraphTemplate
   (content-hash-distinct per pack), and execute backends as binding
   references only — canvas is a binding, never a pack id. Landed via #1680
   (M7-A4, leaf #793). Evidence: `uv run pytest packages/maistro-design/tests
   -q` — 572 passed, 1 skipped (includes `test_packs.py` +
   `test_pack_lifecycle.py`: 65 passed, covering two packs sharing
   Workspace/Project/Goal Run identity with differing Graph hashes and
   Rubric catalogs).
4. **Park / redirect / accept as a HITL fence on waiting NodeRuns — NOT
   MET at runtime.** Packs declare `FencePoint`s (`packs/types.py`). The
   #989 game fixture demonstrates park/resume through canonical WAITING
   lifecycle moves; the book fixture's accept decision is NOT such evidence:
   its fence-NodeRun is created via `_complete_node`
   (`pack_fixtures.py:291-332,578-603`), which transitions
   QUEUED → RUNNING → COMPLETED without ever entering WAITING, so the
   recorded `accept` is nonconforming fixture data and cannot evidence the
   AC-7 rule that `accept` applies only to a waiting NodeRun. There is no
   first-class fence-decision
   runtime/store: grep finds no `FenceDecision` type in production src;
   `graph/seeds/pack_fixtures.py` documents that fence decisions "have no
   durable stores of their own yet" and live in evidence fields
   (`Run.provenance.redirect`, fence-NodeRun attempt `fence_decision`).
   `SPEC-093026-7a90` AC-7 is explicitly `unproven — proven by #794`. No
   #794/M7-A5 commit exists in `c5e070d97..ab8b3737f`.
5. **One public proof with inspectable lineage — PARTIAL.** #989 (M7-A13)
   seeds inspectable book (accepted: wave eval records → refine Attempt 2 →
   recorded accept decision, via direct completion — never WAITING) and
   game (parked: failing dimension → park fence → resume
   across a SQLite reconnect) fixture Runs through canonical spine APIs
   only, listable/openable in the host surface —
   `packages/maistro-core/tests/graph/seeds/test_pack_fixtures.py` (7
   passed), `packages/hive-conductor/backend/tests/test_pack_fixture_run_list.py`
   + `test_design_packs_route.py` (7 passed),
   `packages/maistro-core/tests/test_cli_pack_fixtures.py` (passed with the
   fitness guard: 16 passed). The full #795 proof (Design Studio starts a
   Goal, binds a Rubric, runs a pack, scores on the same Run, fences,
   refines, shows lineage — one live loop) is absent: SPEC AC-10 is
   `unproven — proven by #795`; no #795/M7-A6 commit in the range.
6. **Evolve/RSI mapped as eval consumers; second scoring authority
   contract-forbidden — NOT MET.** No `RunEvalScore` / `record_eval_score` /
   `eval_summary` reference exists in `maistro-evolve/src` or
   `maistro-rsi/src` (grep: 0 hits) — the consumer mapping has not been
   written. The #990 product-boundary tripwire
   (`tests/fitness/test_no_second_design_product.py`, 16 passed with the CLI
   fixture tests) forbids a second design *product*, not the eval-authority
   guard owned by leaf #796; SPEC AC-9 is `unproven — proven by #796`. No
   #796/M7-A7 commit in the range.
7. **No `milestone:M7` issue lacks a canonical parent — VERIFIED where
   captured (GitHub-side); #791–#795 bodies remain outside this dispatch's
   capture scope (UNVERIFIED here, unchanged from round 1).** Captured
   bodies show #787→#453 (parent program), #788→#787, #789→#788,
   #790→#789, #796→#789. Note: the *implementations* of #791/#792/#793
   verifiably landed on develop (PRs #1678/#1681/#1680 commit messages name
   them), so leaf completion is not gated on body capture.
8. **Implementation lands on `feat/*` off `develop` (ADR-095); nothing
   merges to `main` — MET for this lane.** This branch is develop@ab8b3737f
   plus this evidence doc only (`git diff ab8b3737f HEAD --stat` = 1 file);
   the M7 leaf PRs merged through `develop`; no `main` merge exists in the
   range.

## Validation executed (merged tree, real runs)

- `uv sync --locked --extra dev` — resolved.
- `uv run ruff check .` — All checks passed.
- `uv run ruff format --check .` — 3297 files already formatted.
- `uv run pytest packages/maistro-core/tests/ontology -q` — 63 passed.
- `MAISTRO_TEST_PG_DSN=postgresql://maistro:test@127.0.0.1:18787/maistro
   uv run pytest packages/maistro-core/tests/runs/test_eval_on_run.py -q`
   (after `DATABASE_URL=... uv run alembic upgrade head` on a pgvector/pg18
   container) — 34 passed, 0 skipped.
- `uv run pytest packages/maistro-design/tests -q` — 572 passed, 1 skipped.
- `uv run pytest packages/maistro-core/tests/graph/seeds/test_pack_fixtures.py
   packages/hive-conductor/backend/tests/test_pack_fixture_run_list.py
   packages/hive-conductor/backend/tests/test_design_packs_route.py -q`
   — 14 passed.
- `uv run pytest packages/maistro-core/tests/fitness/test_no_second_design_product.py
   packages/maistro-core/tests/test_cli_pack_fixtures.py -q` — 16 passed.

## Conclusion

Round 1 (at c5e070d) found all six runtime exits absent. At the synced
develop base ab8b3737f, exits 1–3 (Rubric ontology, eval-on-Run, domain
packs) are implemented and behaviorally green, and exit 5 has substantial
fixture-lineage evidence — but the milestone cannot close: exit 4
(park/redirect/accept HITL fence runtime) and exit 6 (Evolve/RSI consumer
map + eval-authority guard) are absent, and exit 5's live #795 proof is not
shipped. Remaining owners are leaves #794, #795, #796 under #789/#788; the
contract ADRs (ADR-092926-7a01, ADR-093026-7a90) remain Proposed with
AC-7/8/9/10 unproven until those leaves land. #787 itself stays open.
