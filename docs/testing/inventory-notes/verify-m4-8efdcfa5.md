---
inventory-delta:
  packages/maistro-evolve/tests: +0
  packages/maistro-registry/tests: +0
  packages/maistro-core/tests: +0
---

# verify-m4-8efdcfa5

Second M4 acceptance sweep for lane L8 (issue #8 snapshot "[MILESTONE M4]
Governed continual improvement"), resolving the NEEDS-DEEP-REVIEW block
recorded in `verify-m4-0a043651.md`. That record swept at `fa3391e5e`;
this round first synced the lane branch to the assigned develop base
`ab8b3737fa64f8d840f421ef87ca506c509444ff` (clean merge, no conflicts) and
re-ran the sweep at the merged head `4d5f0ac49aeac08d178ba44cb1bab87e27210dc7`.
The manifest again carried `checks: []` and no `check-*.log` files exist in
the job directory, so every check below was executed first-party at the exact
head. This note moves no test counts.

## What changed since the blocked sweep

The 344 develop commits between `fa3391e5e` and `ab8b3737` landed the four
module-level FAIL/PARTIAL gaps the previous sweep named:

- **Curriculum (#24, was FAIL-absent):**
  `packages/maistro-evolve/src/maistro_evolve/curriculum.py` now exists with
  host-owned independent validity gates — admission is refused without an
  independent solver (`curriculum.py:246-254`, "no independent solver —
  admission refused"), solver answers are checked against the verifier
  (`curriculum.py:307`), and a same-model second opinion is explicitly not an
  independent check (`curriculum.py:145`). Spec: `docs/specs/SPEC-282-self-generated-curriculum.md`
  (front-matter `status: Proposed`).
- **Corpus-aware retrieval (#26, was FAIL-absent):**
  `packages/maistro-registry/src/maistro_registry/retrieval/` (corpus.py,
  index.py, search.py, expand.py, terms.py, quality.py — 1,397 source lines)
  implements the epic's shape: registry IDs/status/reference-graph as source
  identity with content-hash versioning (`corpus.py` `CorpusDocument.version`,
  first 12 hex of SHA-256), BM25 lexical baseline, offline enrichment
  (KNOWN-GAPS split into per-gap units at index time), query expansion with
  corpus-statistical useless-term rejection, and a measured golden-set
  evaluation with nDCG/MRR/Recall@k and CLI thresholds (`quality.py`).
  Executed: `uv run python -m maistro_registry.cli eval . --min-mrr 0.9` —
  **exit 0** over the live repo corpus, all shipped golden queries `[ok ]`
  except the no-answer probe `'quantum consciousness module for the
  orchestrator'` which correctly returns `[MISS]` mrr=0.000 (no fabricated
  governing citation).
- **Repertoire reachability (was FAIL-unreachable):**
  `packages/maistro-core/src/maistro/agents/base.py:674-715` `_build_context`
  now passes `learning_store` into the canonical context builder (recall into
  prompt context, `learnings_injected` traced at base.py:711), per-turn
  outcomes are marked (`base.py:571-577` `mark_outcome`) and measured
  (`memory/learnings/evidence.py:105` `outcome_confidence(success_after_use,
  failure_after_use)` — a measurement outranks a report), and failure
  knowledge is promoted to ANTI_PATTERN only through the same Gauntlet
  (`base.py:578-586`, #121). Persistence ships (pg/sqlite learnings), gauntlet
  and lifecycle gate promotion.
- **Held-out evaluation (was self-documented as not enforced):**
  `benchmarks/bfcl_real.py:44-46,286` and `benchmarks/ifeval_real.py:27-33`
  now enforce deterministic hashed train/holdout splits where `split="train"`
  is what fitness may see, `split="holdout"` is the supervisor's, and
  capability bonuses are paid only on holdout;
  `executable_terminal_runner.py:52-55` runs training and holdout as separate
  ledger phases. Evolve fitness bonuses remain population-context only
  (`fitness.py:82-83` `diversity_bonus`/`elo_bonus`) — no bonus is paid on a
  benchmark score the loop can see. Residual: the SPEC-202 proxy-tier
  `terminalbench.py` still *reports* a combined headline with per-split
  metadata rather than enforcing separation (deliberate, documented in its
  docstring); owned by open #853/#384, not this lane.

## Writer-executed checks (all at 4d5f0ac4, post-merge)

- `uv run ruff check .` — **exit 0**.
- `uv run ruff format --check .` — **exit 0** (3,297 files formatted).
- `uv run pytest packages/maistro-evolve/tests -q` — **998 passed, 6 skipped**
  (11.07s; was 99 tests on six files at fa3391e5e).
- `uv run pytest packages/maistro-core/tests/memory/learnings
  packages/maistro-core/tests/repertoire -q` — **323 passed** (3.85s).
- `uv run pytest packages/maistro-registry/tests -q` — **84 passed** (2.53s;
  includes test_retrieval_corpus/index_search/expansion/quality/cli covering
  the #26 acceptance cases: renamed source with stable ID, changed content,
  superseded decision, duplicate identity, useless expansion terms, no-result).
- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_service.py -q`
  — **33 passed** (1.51s): canonical-graph cycle path still reachable.
- `uv run python scripts/check-promotion-surface.py` — **exit 0**
  ("promotion surface: ok").
- `uv run python scripts/check-suite-inventory.py` — **exit 0** ("ok: 17
  suite(s) match the recorded inventory"), after `uv sync --locked --extra dev`:
  the merge brought new dev-extra packages into the workspace (e.g.
  `maistro-ext-harness`, pyproject.toml:91), and without the resync the gate
  reports collection errors — environment, not drift.
- `uv run python scripts/check-doc-links.py` — **exit 0**.
- `uv run python -m maistro_registry.cli eval . --min-mrr 0.9` — **exit 0**.

## Exit-condition sweep (issue #8 snapshot → evidence at 4d5f0ac4)

| # | Criterion | Disposition | Evidence |
|---|-----------|-------------|----------|
| 1 | Candidate/evaluation/promotion loop explicit and auditable | PASS at substrate level | Unchanged from prior sweep and re-proven: `population.py` human-approval gate + `promote_audited`, `audit.py` append-only `GenomeAuditTrail`, Conductor evolution service 33 tests pass. Gate A milestone-level contract (#116/#854/#861) not in this dispatch snapshot → UNVERIFIED this round. |
| 2 | Validated collective learning influences later Runs, effect measured | PASS | Recall→run→measure→promote loop wired in `agents/base.py:380,674-715,571-586`; effect measured via `outcome_confidence` (evidence.py:105); Gauntlet/lifecycle gate promotion; 323 learnings/repertoire tests pass. |
| 3 | Population search preserves diversity and held-out evaluation | PASS with recorded residual | Diversity substrate (998 evolve tests); enforced train/holdout splits in bfcl_real.py/ifeval_real.py with supervisor-only holdout and holdout-only bonuses; terminalbench proxy-tier combined-report residual owned by open #853/#384. |
| 4 | Self-generated curriculum independently validated | PASS | curriculum.py independent-solver admission gates + SPEC-282; covered in the 998 evolve tests (test_curriculum.py). |
| 5 | Harness components improve without becoming another runtime | PASS | `check-promotion-surface.py` exit 0 at this head; SPEC-281 harness-lift measurement substrate present. Provider epics #822/#783 remain open under #25. |
| 6 | ADR/spec corpus retrieval corpus-aware and measurable | PASS | `maistro_registry/retrieval/` + shipped golden set; `eval --min-mrr 0.9` exit 0 over live corpus incl. no-answer case; 84 registry tests. |
| 7 | External benchmark / working-memory / verification-aware execution / persistent eval-workspace lanes dispositioned | PASS as dispositioned | All four epics (#104–#107) open with explicit `Parent initiative: #450` (snapshot). Substrate uneven by design: external benchmarks shipped (bfcl/ifeval/terminalbench + repo_history), eval-workspace shipped and CLI-reachable (`maistro eval-workspace`, `cli/_eval_workspace.py` — the #107 conformance proof), working memory (#301) and verification-aware executor (#106) still code-absent. |
| 8 | Direct EVENTUALLY children of #450 completed/obsolete/reclassified | PARTIAL (snapshot) | 11 of 21 CLOSED (#294, #295, #381, #383, #385, #386, #387, #388, #391, #394, #395); 10 OPEN (#287, #288, #292, #380, #382, #389, #390, #393, #396, #398). None obsolete; reclassifications recorded on #450 match live bodies. |
| 9 | No `milestone:M4` issue lacks one unambiguous canonical parent | UNVERIFIED this round | #614 (the one defect the prior sweep found, parented to closed M5-B epic #305) is not in this dispatch snapshot; no API access to re-query. Prior evidence stands; needs an owner decision, not a code patch. |

Tally: 6 PASS, 1 PASS-with-residual, 1 PARTIAL (issue-state), 1 UNVERIFIED
(issue-state) — versus 0/5/4 at fa3391e5e.

## Verdict rationale (NEEDS-REPAIR)

The module-level immaturity that justified NEEDS-DEEP-REVIEW is resolved with
executed evidence: curriculum, corpus retrieval, collective-learning wiring
and enforced holdout splits all landed and pass their suites at this head.
What remains is concrete and scheduled, not murky: ten open EVENTUALLY
children under #450 (exit 8), the #614 parentage defect awaiting an owner
decision (exit 9), the #853/#384 terminalbench proxy-tier residual (exit 3),
and the Gate A promotion contract (#116/#854/#861) outside this snapshot.
Those are owned by other lanes/issues; this milestone tracker cannot close
them from here, and no GitHub mutation is permitted. Branch state: synced to
the assigned base via clean merge; this record is the lane deliverable.
