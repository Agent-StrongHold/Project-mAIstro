# M8-C4 research note — episodic-to-semantic consolidation, temporal contradiction handling, forgetting

Leaf: #923. Epic: #901. Initiative: #879.

## Hypothesis

Long-lived Workspace memory improves when raw episodic observations are periodically
consolidated into higher-level semantic facts, stale claims decay, and contradictory temporal
facts are reconciled explicitly.

## Canonical seams

The hypothesis is not hypothetical in this repository — every mechanism it names already
ships, with an owner:

- **Episodic-to-semantic promotion** exists twice, at different granularities. The
  `LearningPromoter` (`packages/maistro-core/src/maistro/memory/learnings/promoter.py`)
  promotes repeatedly-useful learnings across a threshold, with three postures of increasing
  governance — Gauntlet (independent-context evaluation with frozen evaluation provenance,
  M4-B2), human approval gate, or legacy auto-promotion — and knowledge-stage transitions
  (`MEMORY -> LEARNING -> VALIDATED -> REPERTOIRE`, ADR-103) recorded per rung. On the
  episodic side, ADR-091's 7-tier dynamics promote WISDOM and demote REGRET from cumulative
  feedback counts (`memory/episodic/tiers.py`).
- **Consolidation** ships as `memory/episodic/consolidation.py` (ADR-080 part B / SPEC-241):
  an all-pairs scan proposing merges for similar pairs (primary survives, absorbed rows are
  amended to `deleted=True` — tombstoned, never purged) and flags for contradicting pairs
  (both sides lose `CONTRADICT_DELTA` confidence and both enter the review queue — never
  auto-resolved). The learnings lifecycle (`memory/learnings/lifecycle.py`, SPEC-283) carries
  the semantic twin: row-level supersession and consolidation with append-only evidence,
  revision, conflict and consolidation ledgers, where a `ConflictRecord` must name the Run or
  evaluation that detected it and retrieval (`find_relevant`) attaches every unresolved
  conflict touching a returned row — an answer never sees one side of a known contradiction
  without the other.
- **Forgetting** ships as the decay curve (ADR-080 part A / SPEC-240: `tick_decay` loses
  `decay_rate * elapsed_hours` weight, clamped to the ADR-091 tier floor, feedback slows or
  speeds the per-record rate) driven in production by `EpisodicDecayDriver`
  (`memory/episodic/decay_driver.py`, SPEC-080126-9e42), an hourly process-lifetime cadence
  whose disabled state is a *loudly degraded mode*, not a quiet preference.
- **Raw episodic retrieval** — the baseline every strategy must beat — is
  `memory/episodic/ranking.py` (SPEC-243 / ADR-080 part D):
  `(keyword_overlap + vector) * weight` over non-deleted rows, stable descending sort. Two
  facts about this seam drive the whole experiment: the score is **recency-blind** (nothing
  in it knows a fact was superseded), and the stable sort makes **insertion order the
  tiebreak** — so when a stale fact and its successor score equally (same tokens, same
  weight), the *stale* fact ranks first.

What does **not** exist at this head is temporal versioning on the episodic side: episodes
have no supersession chain, no current-version pointer, no audit path that distinguishes "the
fact changed" from "two facts fight". Temporal version handling exists only for learnings
(`lifecycle.supersede`, with `SUPERSEDED` evidence rows retained as historical record). That
gap is exactly what the temporal arm of the experiment below prices.

The issue's one hard constraint — consolidation may not erase provenance or mutate canonical
history invisibly — is already the architecture's own invariant: merges tombstone and retain,
superseded learnings become historical record, contradiction registration requires an
evidence link, and the episodic store's durability contract (PostgreSQL + pgvector per
ADR-011/ADR-034) is not touched by any of it. The experiment therefore *measures* retention
and auditability rather than assuming them.

## Record

This note does not report a real experiment. The deterministic CI environment holds no real
Workspace histories, and manufacturing either was out of scope; absent evidence is recorded
rather than simulated (M8 guardrail 3). No product code, flag, or authority path changed.

What it adds is the reproducible measurement machinery the benchmark procedure needs, as a
separated research artifact:
`packages/maistro-core/tests/memory/test_m8c4_consolidation_temporal_forgetting_research.py`
(test suite only; it imports no maistro module — AST-pinned by its own contract test, M8
guardrails 1-2). Validated on deterministic fixtures (50 checks), it implements:

- a synthetic Workspace history with ground truth by construction: version chains (declared
  supersession), duplicate groups, open contradiction pairs, obsolete one-offs, and
  audit-only episodes — every fact family the issue's experiment description names, with
  subject-prefixed tokens so cross-entity overlap is exactly 0.0 and only the queried
  entity's rows can rank;
- five strategy arms over a day-staged store, each an honest replica of a shipped shape:
  `raw` (the SPEC-243 formula verbatim, shipped `no_vector` default, stable tiebreak),
  `consolidate` (daily all-pairs batches with the lifecycle's unresolved-pair dedup, merges
  tombstoning and contradiction flags attaching), `decayed` (hourly sweep semantics with
  tier floors), `temporal` (declared supersession chains marking predecessors — retained),
  and `combined`;
- three WRONGNESS variants, each sabotaging exactly one retention mechanism —
  `consolidate-purge` (erases absorbed rows instead of tombstoning), `decay-no-floor`
  (removes the tier floor), `temporal-silent` (erases predecessors instead of retaining
  them) — so every pin is proven by the failure it prevents, not by assertion;
- an append-only ledger under every arm whose replay must reconstruct the full episode set,
  with chain integrity scored over the final state (absent episodes and broken
  absorbed-source chains both count) — the issue's auditability constraint, measured;
- the issue's full measure list: current-fact accuracy (top-1 against ground truth),
  stale-fact intrusion (non-current slots in the answer window), information loss
  (audit-relevant episodes reachable in no mode), contradiction resolution quality (declared
  pairs surfaced with both sides and the conflict attached, vs answered silently), storage
  (live vs retained rows), consolidation cost (exact per-batch comparison counts), and
  auditability (chain integrity + ledger replay).

What the fixtures demonstrate (synthetic histories, **not** evidence about real Workspaces):

- **The stale-lead defect is structural, and temporal versions are the repair that costs
  nothing else.** With content-identical stale and current facts, raw retrieval leads with
  the stale one (stable tiebreak, older first) on the hand fixture (top-1 miss) and on every
  versioned entity of the seeded corpus (current-fact accuracy 1/3 vs 2/3 for the temporal
  arm, 1.0 for the full stack). Supersession repairs it without touching weights, decay, or
  storage — and because predecessors are retained, audit-mode recall stays 1.0.
- **Decay is the wrong tool for staleness and the right tool for obsolescence.** Under the
  shipped curve both the stale and the current version of a fact decay to the tie floor
  together — the stale-lead defect survives decay (the hand fixture's decayed arm still
  leads with the stale fact). What decay actually buys is sinking obsolete one-offs to the
  OBSERVATION floor (0.10) *without* removing them: the hand fixture's audit-only and
  obsolete rows stay reachable at floor-weighted scores, and information loss stays 0.0.
  Removing the floor (the WRONGNESS variant) is what produces information loss — by the
  frozen numbers, 3 of 8 hand-fixture episodes and 29 of 36 seeded audit episodes drop out
  of every mode.
- **Consolidation trades answering footprint for exactly the two things it should, and the
  ledger is what makes the trade honest.** Merging collapses duplicate groups (seeded live
  rows 48 -> 42, hand fixture 8 -> 7), repairs duplicate-displacement (a heavier duplicate
  outranking the canonical row at top-1), and flattens storage growth — while retained rows
  keep audit recall at 1.0. The purge variant shows what the tombstone is for: chain
  integrity falls (0.75 seeded / 0.75 hand), audit recall drops, and the ledger replay can
  no longer reconstruct the episode set. Cost is quadratic and unavoidable at this shape:
  the hand fixture's daily batches spend 43 comparisons for one merge and one flag.
- **Contradiction handling is a surfacing problem, not a resolution problem.** Raw
  retrieval answers contradiction queries with both sides present and nothing attached —
  the conflict is smuggled into the prompt unresolved (quality 0.0 on every declared pair).
  The flagging arm registers the conflict once (the lifecycle's unresolved-pair dedup), both
  sides enter the review queue with `CONTRADICT_DELTA` confidence loss, and quality reaches
  1.0. Declared supersessions are correctly exempt: a temporal version is the resolution of
  an outdated claim, not an open conflict, and the batch never flags a version pair.
- **Retention is the load-bearing wall of auditability.** Across every retaining arm (raw,
  consolidate, decayed, temporal, combined) chain integrity is 1.0 and the ledger replay
  reconstructs the full episode set; each WRONGNESS variant breaks exactly its own pin. The
  frozen replay/retention invariant — an arm reconstructs the episode set if and only if it
  never broke a provenance chain — holds on every arm by construction, and it is the
  machine-checkable form of the issue's constraint.

Executed probe record (this change): `uv run pytest
packages/maistro-core/tests/memory/test_m8c4_consolidation_temporal_forgetting_research.py
-q` -> 50 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module;
the WRONGNESS grid provides the mutation evidence (each named mechanism — tombstone
retention, tier floor, predecessor retention — flips exactly its pins when removed).

## Benchmark procedure (what a real experiment must do)

1. Export real Workspace histories through the canonical memory seams (durable episodic rows
   with provenance columns and learnings with their evidence ledgers intact; no scope
   leaking into the corpus).
2. Hand-audit a relevance sample: per query, the current-fact set, the known-stale set, and
   the declared contradiction pairs. Ground truth by hand, not by the strategy under test.
3. Run the arms against the real stores: the shipped consolidation batch and decay driver on
   copies of real scopes; the temporal arm as a *prototype* supersession column + retrieval
   policy, clearly flagged as not-shipped.
4. Measure the issue's full list per arm at matched retrieval budgets: current-fact accuracy,
   stale intrusion, information loss (episodes reachable in no mode — retention must keep
   this at zero), contradiction resolution quality (surfaced vs silent), storage growth
   (live vs retained rows), consolidation cost (comparisons, merges, flags per batch), and
   auditability (chain integrity and ledger replay on the real append-only ledgers).
5. Sweep consolidation cadence and similarity thresholds — the quadratic all-pairs cost and
   the merge/false-merge boundary are the knobs a real deployment would tune.
6. Report the audit-query cost alongside the current-fact gain: the fixtures show the two
   move together (temporal current-mode wins are exactly audit-mode hiding), so a real run
   that reports only the current-fact gain is not done.
7. Update the disposition here. Adoption of any winning policy belongs to the canonical
   memory owners (ADR-034/ADR-091/ADR-080 parts A-D, SPEC-240/241, SPEC-283), as a change to
   the existing consolidation/decay/retrieval seams — never as a second store or a second
   memory authority.

## Trust boundary

Every number the harness produces is advisory evidence: it reads no Goal, writes no Run
authority, touches no durable store, and makes no memory decision. The module cannot import
maistro (its own test asserts this by AST), so it cannot drift into becoming a second memory
authority — the epic's prohibition is enforced structurally, not by convention. Ground truth
is frozen at fixture construction; results are frozen dataclasses; the ledger replay makes
the issue's "may not erase provenance or mutate canonical history invisibly" a measured
property rather than a promise. A strategy that survives a real experiment reaches production
only through the canonical memory seams and their owners, where consolidation proposals stay
subject to the review queue and the auditability constraints the shipped code already
enforces.

## Disposition

- #923 (episodic-to-semantic consolidation, temporal contradiction handling, forgetting):
  **WATCH** — the measurement machinery is reproducible and its retention/auditability pins
  are mutation-validated, but no real-Workspace experiment exists, so the hypothesis is
  unevidenced on MAIstro workloads. The fixtures already bound the shape of the answer:
  temporal versions are the only arm that repairs stale-lead without a storage or audit cost,
  decay's value is obsolescence-sinking (not staleness repair), and consolidation's value is
  duplicate-collapse with retention carrying the audit trail.
- Move to **INCUBATE** when a real run on representative histories shows (a) consolidation
  batches whose false-merge rate against a hand-audited sample is low enough that live-footprint
  savings survive, (b) a temporal-version prototype repairing current-fact accuracy at
  measured audit-query cost, and (c) the decay cadence sweeping obsolete facts to floor
  without information loss — with the memory owners holding the result and routing any
  episodic supersession design through the lifecycle's evidence-ledger pattern.
- Move to **REJECT** if real runs show consolidation cost (quadratic comparisons per batch)
  dominating the footprint savings at realistic scope sizes, or false merges erasing
  distinctions a hand-audited sample shows to matter, or temporal-version maintenance
  costing more than the stale-lead defect it repairs.

No adoption is authorized by this note.
