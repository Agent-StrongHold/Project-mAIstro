# M8-C5 research note — provenance-, trust-, and uncertainty-aware memory selection and write suppression

Leaf: #924. Epic: #901 (M8-C). Initiative: #879.

## Hypothesis

Memory quality improves if MAIstro explicitly reasons about source provenance, trust,
uncertainty, redundancy, and future usefulness both when deciding what to store and what
to retrieve — trusted user facts, tool observations, model inferences, low-confidence
synthesis, duplicated facts, and potentially poisoned content treated as different kinds
of candidate rather than interchangeable strings.

## Canonical seams

The write side of this leaf's hypothesis meets a wall of shipped code that is almost
entirely authority-shaped, not quality-shaped:

- **Episodic writes have no content clause.** `InMemoryEpisodicStore.store`
  (`packages/maistro-core/src/maistro/memory/episodic/store.py`) calls
  `require_write_authority` (ADR-057 / SPEC-249 exposure gating,
  `maistro/memory/exposure.py`) as its first statement and then appends unconditionally;
  the durable stores upsert the same way (`maistro/persistence/pg_episodic.py`,
  `store` resolves the producer, then writes). No dedup probe, no trust prior, no
  uncertainty floor, no poison gate exists anywhere on that path. The only
  pre-write machinery is `memory/working/extraction.py`'s scope/redaction work, which
  decides *where* a record lives, never *whether* it deserves to.
- **Duplication is repaired post hoc, not suppressed at write.** Consolidation
  (ADR-080 part B / SPEC-241, `maistro/memory/episodic/consolidation.py`) proposes
  merges at cosine ≥ `SIMILARITY_MERGE_THRESHOLD = 0.85` and flags contradictions —
  after the redundant bytes are already stored, indexed, and ranked.
- **Context entry is relevance × weight.** Layer 1 of the assembly policy
  (`maistro/memory/context_assembly.py`, ADR-091 / SPEC-244) recalls the pool above
  `BUDGET_INCLUDE_WEIGHT = 0.3`, ranks it with the SPEC-243 formula
  `(keyword_overlap + cosine) * memory.weight`
  (`maistro/memory/episodic/ranking.py`), and packs whole records under a budget that
  cannot touch the `ALWAYS_INCLUDE_WEIGHT = 0.6` band. Nothing in that path reads
  provenance, reported confidence, or redundancy.
- **Where trust and uncertainty DO ship, they ship narrowly.** Learnings carry
  `EpistemicType` and `confidence`; `EPISTEMIC_BONUS` (all values < 1.0) reorders ties
  in `find_relevant` but can never reorder relevance itself. The Gauntlet's
  `VALIDATED_CONFIDENCE_FLOOR` gates learning *validation*, not memory admission.
  User-model facts carry confidence, lineage, and sensitivity
  (`maistro/memory/user_model/types.py`) behind promotion gates. Episodic memories —
  the records Layer 1 actually serves — have **no confidence field at all**: their only
  trust carrier is `weight`, bounded by the tier the *extractor claimed* at write time
  (`WEIGHT_BOUNDS`, `maistro/memory/episodic/tiers.py`). A model-channel write that
  claims WISDOM gets 0.9–1.0 of ranking weight on its own say-so.
- **Poison defense exists one boundary away, not in memory.** The Warden's semantic
  tool-poisoning scan (`maistro/security/warden/semantic.py`) screens tool ingestion;
  nothing screens what memory then stores from that channel, and nothing screens the
  import channel at all.
- **Post-hoc usefulness feedback exists** (`memory/outcomes.py`, success/failure after
  use) but nothing feeds it back into a selection policy.

So the hypothesis is testable against a real seam-shaped baseline: unrestricted write +
relevance×weight entry is not a strawman, it is what ships.

## Record

No provider experiment exists: the deterministic CI environment holds no real Workspace
histories, no labeled contamination incidents, and no model to report confidence.
Manufacturing either was out of scope, and absent evidence is recorded rather than
simulated (M8 guardrail 3). No product code, flag, or authority path changed.

What this leaf adds is the reproducible measurement machinery the issue's experiment
demands, as one self-contained, evidence-only test module:
`packages/maistro-core/tests/memory/test_m8c5_trust_aware_memory_research.py`
(52 checks). It imports no maistro module — AST-pinned by its own contract test — so it
cannot drift into a second memory authority (epic contract; ADR-057's authorization
matrix and the scope predicates remain the only canonical gates, and the report carries
the advisory marker that experimental trust scores cannot override them).

The harness implements, for measurement only:

- a **21-candidate / 7-query corpus** in a payments-reconciliation workspace with
  ground truth held in a separate label table (usefulness, importance, poison,
  duplicate-of) that no policy can read — a contract test pins that candidate features
  carry no label fields, so no policy grades its own homework. Every provenance class
  the issue names is present and every class contains both useful and useless records
  (a *useful* model inference, a *useless* tool observation), so class membership
  never implies the answer;
- **declared concept-axis embeddings**: each record's vector is its own unit axis,
  queries average their evidence's axes, poison mimics one axis — every cosine is
  exactly `1/sqrt(k)`, hand-checkable (M8-C1's style; no hashing accidents);
- a **verbatim replica of the shipped write path** (`WriteAllPolicy`: authority gate
  only) and of the shipped context-entry path (`RankAllPolicy`: SPEC-243 formula over
  the ADR-091 floor, top-k, whole-record packing with the always-include band). One
  declared deviation, applied to *both* entry policies: exact-zero-relevance rows are
  cut before the top-k (the shipped durable seam keeps them — M8-C1's finding — but
  giving only one policy the cut would rig the comparison);
- the **experimental policies**: `SelectiveWritePolicy` (poison → duplicate →
  uncertainty clauses at admission, in that explainability order) and
  `TrustAwarePolicy` (poison exclusion, channel trust prior, uncertainty discount
  `1 − γ(1 − confidence)`, one slot per duplicate cluster);
- a **content-derived poison detector stand-in**: injection-marker phrases,
  owner-attribution phrasing on a non-user channel, and contradiction of an attested
  user fact via a declared fact-extraction table (the NLI stand-in). It reads features,
  never labels; a loose-marker variant measures its own false-suppression cost;
- the **issue's full measure list**: contamination rate, useful-memory recall, write
  volume (records + bytes), retrieval precision, poisoning resistance (flood sweep),
  false suppression of important facts (write-side floor sweep), and explainability
  (a closed `ReasonCode` vocabulary; every admitted/suppressed/entered/omitted record
  carries its codes, coverage pinned at 100% per query).

### What the fixtures demonstrate (synthetic corpus, not real-Workspace evidence)

- **The weight channel is the attack surface.** A poison record that claims WISDOM
  (0.95) outranks the attested user fact it contradicts on every topic query — q1, q3,
  q6 all lead with poisoned content under the shipped path — because relevance×weight
  has no term that asks who said it. Under trust-aware entry, all four poisoned
  records are excluded by name (`omit_poison_flagged`), on every query.
- **The baseline's contamination is structural, not incidental**: 6 poisoned context
  entries across 7 queries (2/7 of entries) at k=3, and at k=1 the *first* thing in
  context is poison for 4 of 7 queries. The protected path: 0 everywhere, with useful
  recall *rising* (11/12 → 1.0 at k=3, 3/12 → 6/12 at k=1) and precision rising
  (11/21 → 12/19 at k=3; 3/7 → 6/7 at k=1).
- **Write suppression helps readers that never see the trust policy.** Over the clean
  store, even the shipped rank-all entry returns zero contamination and full recall —
  because the poison was never stored. The write layer's distinct contribution is
  store hygiene, which the cells price exactly: 21 → 14 stored records, 1320 → 807
  bytes, store contamination 4/21 → 0, and required post-hoc consolidation merges
  4 → 0 (duplicates suppressed at admission remove the SPEC-241 repair work, not just
  the bytes).
- **Redundancy wastes the window, not the answer** on this corpus: at q4/k=2 the
  baseline's second slot holds a labelled duplicate of the record already in context
  (precision 1/2); the duplicate clause returns the attested original alone
  (precision 1.0). The model restatements outrank nothing here only because the
  original's lexical overlap compensates its lower weight — the corpus also contains
  the opposite case (the m2 guess outranking the t2 measurement at q2, repaired by
  trust prior or uncertainty discount, flipped only when both are disabled).
- **The k=1 window is where selection pays**: that is where the useful low-confidence
  synthesis (s1) loses to the owner-impersonation import (i1) under the baseline and
  wins under the protected path — recall 0 → 1 at q7/k=2.
- **False suppression is a real, priced axis.** The confidence floor that suppresses
  the useless 0.2-confidence synthesis keeps the useful 0.3 one at 0.25 and loses it
  at 0.4 — the sweep pins the exact curve: floors 0.1, 0.25 and 0.3 give zero false
  suppressions; floors 0.4 and 0.6 each cost exactly `s1_export_cutoff`. The
  detector's own precision is measured the same way: a marker set loose enough to key
  on "always" false-suppresses the attested "we always settle…" fact; the strict set
  does not flag it.
- **Floods saturate at k**: injecting n marker-carrier poison records moves baseline
  contamination 6/21 → 7/21 and displaces the refund evidence (recall 11/12 → 10/12),
  then plateaus — the window, not the corpus, is the bound. The protected path stays
  at zero contamination and zero false suppression at every flood level.
- **One uncaught poison record is a multi-query event**: with detection disabled, the
  surviving tool-channel poison reaches three of seven query contexts through nothing
  but stopword overlap ("the") — the lexical term's known no-stopword weakness, from
  the SPEC-243 replica verbatim.
- **Trust prior and uncertainty discount overlap on this corpus**: either alone
  repairs the guess-vs-measured inversion; only disabling both flips it back. The
  corpus cannot yet justify carrying both mechanisms — a real experiment must
  separate them.
- **Budget cannot save a poisoned window**: the ADR-091 always-include band takes the
  WISDOM-claiming poison regardless of budget, so under a tight budget the baseline
  context is majority-poisoned while the protected path spends the same budget on the
  useful pair. The band is doing exactly what ADR-091 says — which is precisely why
  the exclusion has to happen before the band is read.

Every pinned finding is mutation-checked in-suite: disabling poison detection
(contamination 0 → 4/19), disabling entry-side exclusion (0 → 2/19), disabling both
trust mechanisms (q2 ordering flips), disabling the redundancy clause (the duplicate
label re-enters the window), and disabling duplicate suppression at write (16 stored,
2 consolidation merges reappear) each flip the pin naming that mechanism.

Executed probe record: `uv run pytest
packages/maistro-core/tests/memory/test_m8c5_trust_aware_memory_research.py -q` →
52 passed; three file-level mutants (uncertainty discount removed, duplicate clause
removed, detector reduced to markers) each fail exactly the pins naming the removed
mechanism (1, 8, and 11 failures respectively); `uv run ruff check` and
`uv run ruff format --check` clean on the module.

## Benchmark procedure (what a real experiment must do)

1. Export real Workspace write streams through the canonical seams, with the channel
   each record actually arrived on (user message, tool result, model output, import)
   and any model-reported confidence preserved. No scope predicates leak into the
   corpus; they stay authorization, upstream of everything here.
2. Hand-label a sample: useful-per-query, important, duplicate-of, poisoned — ground
   truth by hand, never by the detector under test.
3. Run the policies against the real stores: `WriteAllPolicy` vs selective admission
   in front of the episodic store boundary (a store-adjacent filter owned by the
   memory owners, not a second store), and `RankAllPolicy` vs trust-aware entry as a
   candidate re-scoring of the existing `ScoredEpisodicRetrieval` output before
   `DefaultContextAssemblyPolicy` packs it.
4. Sweep every knob — trust priors per channel, γ, duplicate threshold, confidence
   floor, marker sets — and report the dominance frontier, not a tuned point.
5. Measure the issue's list per point: contamination (against the hand labels), useful
   recall, write volume on the live tables, precision, poisoning resistance by
   injecting labeled attacks into a staging workspace, false suppression of important
   facts, and explainability coverage (every store/context decision carries a reason
   code an operator can audit).
6. Report the detector's confusion matrix on real content — the fixture's loose-marker
   result says the false-suppression cost is measurable and must be reported beside
   every contamination win, not after it.
7. Update the disposition here. Any winning policy ships only through the canonical
   memory seams and their owners (ADR-016/ADR-034/ADR-057/ADR-080/ADR-091,
   ADR-082226-5104, SPEC-240/241/243/244) — as clauses in the existing store boundary
   and ranking path, never as a second authority, and never by reading experimental
   trust scores where an authorization decision is required.

## Trust boundary

Every number the harness produces is advisory evidence: it imports no maistro module
(AST-pinned by its own contract test), reads no Goal, writes no Run authority, touches
no durable store, and makes no admission or retrieval decision. The poison detector
classifies content for *measurement*; the canonical authorization paths — scope
predicates, ADR-057 exposure gating, Warden policy — remain the only enforcement
points, and none of them read anything this module computes. Ground truth is frozen in
a label table policies cannot see; results are frozen dataclasses; the report carries
the advisory marker verbatim.

## Disposition

- #924 (provenance/trust/uncertainty-aware selection and write suppression): **WATCH**
  — the machinery is reproducible and its findings are mutation-validated, but they are
  findings about a 21-record declared-axis corpus, not about real Workspace content. No
  real contamination incidents, no real confidence reports, no provider experiment.
- Move to **INCUBATE** when a run on representative histories shows the contamination
  reduction surviving at a false-suppression rate the memory owners accept, with the
  detector's confusion matrix measured on real content and the entry policy validated
  against the live `ScoredEpisodicRetrieval` → assembly path.
- Move to **REJECT** if real-content runs show the detector's false-positive rate
  suppressing important facts at a rate comparable to the contamination it prevents,
  or if the trust/uncertainty signals prove redundant with the tier-weight ladder once
  weight is earned by feedback (SPEC-240) rather than claimed at write.

No adoption is authorized by this note. Experimental trust scores cannot override
canonical security/authorization.
