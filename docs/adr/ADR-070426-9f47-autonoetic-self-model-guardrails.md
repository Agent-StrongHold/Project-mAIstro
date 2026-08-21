---
id: ADR-070426-9f47
title: Autonoetic self-model threat model and guardrail invariants (maistro-turing)
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-072
  - maistro-engine#ADR-073
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-064
  - maistro-engine#ADR-055
  - maistro-engine#ADR-068
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-9f47: Autonoetic self-model threat model and guardrail invariants (maistro-turing)

## Context

`maistro-turing` (`packages/maistro-turing/`) is the in-progress port of AgentTuring's autonoetic
self-model — Mood, HEXACO personality, drives, and proactive producers (blog, reflection,
curiosity, emotion) — into the engine, tracked by `docs/TURING-MIGRATION-SPEC.md`. At the time of
writing, the port has only landed Phase 0/1 (core types, ~1,290 lines across 5 files); the
self-model package itself (`packages/maistro-turing/src/maistro_turing/self_model/`) contains only
value types (`types.py`) — the repo, activation graph, tool registry, and memory-mirroring
described by the source design do not exist in this repo yet. Phase 3 ("Self-Model") and Phase 8
("Remaining Self-Model + Polish") in the migration spec are where that code will actually be
written.

Before Phase 3 starts, a post-merge security audit of the *source* design — **AgentTuring audit
`research/project-turing/AUDIT-self-model-guardrails.md`, Tranche 6** — reviewed the merged sketch
this port is based on and found 40 findings (the audit's own tally: 5 critical, 14 high, 13
medium, 8 low, numbered F1–F39) plus 18 proposed guardrail invariants (G1–G18) closing or
mitigating them. This ADR is the threat model and the decision to adopt those guardrails as
**mandatory acceptance criteria** for the maistro-turing self-model phases, before a single line
of self-model persistence code lands in this repo — landing the guardrails now is strictly cheaper
than retrofitting them onto a running self.

**Why this is a real threat, not hypothetical.** The self-model is designed to let an LLM write
first-person claims about itself (`note_passion`, `write_self_todo`, `record_personality_claim`,
`write_contributor`) that are then read back into every future prompt as if they were the agent's
own settled opinions. That write path sits downstream of the same untrusted user input Warden
already exists to police (ADR-072, ADR-073) — but the audit found the self-write path is not
wired to Warden at all in the source design. A prompt-injection payload that would be caught at
the ingress boundary today can be paraphrased by the perception LLM, written into the self-model
as a first-person claim, and then re-enter every subsequent prompt as the agent's own voice —
persistent, self-referential, and outside the boundary this engine otherwise treats as load-bearing
(Principle 6, `CLAUDE.md`: "All input is untrusted").

## Attack surface (summary of the audit's findings)

Grouped by mechanism, not by severity — full detail, code/spec locations, and severity
calibration live in the source audit; this ADR carries only what's needed to justify the decision:

1. **Self-authored content bypasses Warden entirely (F1, F3, F7).** Every `note_*` /
   `write_self_todo` / `record_personality_claim` call persists LLM-generated text with no scan at
   the write boundary. Warden today scans ingress and specialist-result egress
   (`security/warden/detector.py`); it has no hook on the self-model write path because that path
   does not exist in this repo yet.
2. **Active todo and dominant-passion text is injected verbatim into every prompt (F2, F3).** Up
   to 500 chars of self-authored todo text, and an unbounded-length dominant passion string, render
   as `[todo:id] {text}` / `I care about: {text}.` in the minimal prompt block on every turn — with
   no content policy. Five todos ride in every prompt (`MINIMAL_TODO_COUNT = 5` in the source
   design).
3. **Activation-graph poisoning via crafted embeddings (F4).** Top-K semantic retrieval matches
   materialize as `origin = retrieval` contributors weighted by similarity. A request whose
   embedding is crafted to rank well against a target node lets an attacker choose which
   passions/facets the self "feels active" about on a given turn — the attacker controls the
   request text that drives this.
4. **Facet and mood drift are attacker-shapable and unbounded (F8–F12).** Asymmetric mood nudges
   skew negative under noisy operation (regret hurts 2x what affirmation helps); weekly HEXACO
   retests accept stuck-answer patterns with no cap on cumulative drift; the retest prompt itself
   is built from self-authored todos, event-nudged mood, and routing-minted memories — all
   indirectly user-influenced. `record_personality_claim`'s per-claim cap (`narrative_weight ≤
   0.4`) has no cap on claim *count*, so many small claims sum to a dominant push regardless of
   calculated-retest history.
5. **Unbounded growth (F13–F17).** Retrieval-contributor rows are never garbage-collected despite
   the spec calling for it. Passions/hobbies/interests/preferences/skills have no per-kind cap.
   Near-duplicate detection is exact-match only, so semantically identical claims accrete as
   separate nodes. Skill levels can only ratchet upward.
6. **The self programs its own ontology with no review gate (F18, critical).** `write_contributor`
   lets the self wire any memory to any facet with no operator checkpoint between reflection and
   the edge becoming durable in the activation graph — combined with the retrieval-poisoning path
   (F4) and the unscanned-write path (F1), there is a route from user input to durable changes in
   how the self interprets all future input, with no human in the loop.
7. **Cross-self / identity integrity gaps (F24–F28)** and **implementation gaps against the source
   spec (F29–F39, including two more criticals)** — most notably that the self-model has **zero
   wiring to episodic memory** (F38: no self-model action mirrors as an OBSERVATION/AFFIRMATION/
   LESSON memory) and **the self-as-Conduit pipeline is entirely unwired** (F39: nothing in the
   request path calls `recall_self`, `render_minimal_block`, or the self's decision tools) in the
   source sketch this port is based on.

## Decision

Adopt the audit's **G1–G18** guardrail invariants as **mandatory acceptance criteria** for
`docs/TURING-MIGRATION-SPEC.md` Phase 3 (Self-Model) and Phase 8 (Remaining Self-Model + Polish).
No self-model write path, activation-graph write path, or personality-retest path may land in
`packages/maistro-turing/` without its corresponding guardrail(s) landing in the same PR. This
mirrors the audit's own recommended tranche ordering, which we adopt as the phase sequencing:

### Tranche A — boundary hardening (warden-on-self-writes; write budgets/preconditions)

- **G1 — Warden-scan every self-authored write.** Every `note_*`, `write_self_todo`,
  `write_contributor`, `record_personality_claim` call runs its text through Warden
  (`trust_tier = tool_result`, the same posture as specialist output) before persistence.
  Rejected writes raise `SelfWriteBlocked` and are logged as an OBSERVATION memory. Closes F1, F3,
  F7.
- **G2 — Per-request self-write budget.** ≤3 new nodes, ≤5 contributor edges, ≤2 todo writes, ≤3
  personality claims per request (identified by `request_hash`); a per-request counter enforced by
  the self-surface runtime, resetting each request. Closes F20.
- **G10 — Skill-level honesty precondition.** `practice_skill` may raise `stored_level` only when
  preceded, in the same request, by an OBSERVATION or ACCOMPLISHMENT memory citing the practice
  event; a scheduled drift-check flags "skill-inflation" if >10 skills rise without a downgrade in
  90 days. Closes F17.
- **G17 — Forensic tagging on every self-write.** Every write persists `context.request_hash` and
  `context.perception_tool_call_id`; writes outside the request pipeline require
  `context.provenance = "out_of_band"`. Makes every row's provenance reconstructible — a
  prerequisite for G1/G2 to be auditable, not just enforced. Closes F1 (partial), F18 (partial).

### Tranche B — drift bounds (facet-drift + mood-rolling-sum budgets; narrative-claim rate-limit)

- **G3 — Per-day/week/quarter drift budget on personality facets.** Cumulative absolute Δ on any
  facet capped at `FACET_WEEKLY_DRIFT_MAX = 0.5` (7-day rolling) and
  `FACET_QUARTERLY_DRIFT_MAX = 1.5`; a retest that would exceed the cap clips, with an OPINION
  memory recording the clip. Closes F9, F10.
- **G6 — Symmetric mood accounting with a rolling-sum guard.** `MOOD_ROLLING_WINDOW = 7 days`,
  `MOOD_ROLLING_SUM_CAP = 2.0` on absolute cumulative nudge per dimension; single-event asymmetry
  (regret hurts more than affirmation helps) is preserved by design, but total directional drift
  clamps — excess nudges log as OBSERVATION memories without mutating `self_mood`. Closes F8.
- **G4 — Narrative-claim rate limit.** `record_personality_claim` capped at
  `NARRATIVE_CLAIMS_PER_FACET_PER_WEEK = 3`; over-cap calls raise `NarrativeClaimRateLimit`.
  Closes F12.

### Tranche C — growth and retrieval bounds (retrieval-contributor caps/GC; per-kind node caps; near-duplicate review)

- **G5 — Bounded retrieval-contributor count and weight.** `K_RETRIEVAL_CONTRIBUTORS = 8` hard cap
  per target node per request; sum of retrieval weights into any target capped at
  `RETRIEVAL_SUM_CAP = 1.0` — lower-similarity matches are dropped once the cap is hit. Closes F4.
- **G7 — Retrieval-contributor GC.** Reactor-scheduled sweep deletes expired `origin = 'retrieval'`
  rows; opportunistic GC-on-read once a node's contributor count exceeds
  `GC_READ_THRESHOLD = 100`. Closes F13.
- **G8 — Per-kind node caps with eviction-by-activation.** Hard caps per self (passions ≤100,
  hobbies ≤100, interests ≤200, preferences ≤500, skills ≤200); at the cap, the lowest-`active_now`
  existing node of that kind is archived (not deleted) and the eviction itself is an OBSERVATION
  memory. Closes F15.
- **G9 — Near-duplicate detection with operator-review flag.** Cosine similarity ≥
  `DUPLICATE_SIMILARITY_THRESHOLD = 0.88` against same-kind existing text inserts the new row
  `pending_merge_review = True` (muted at strength × 0.5 until resolved) and an OPINION memory for
  the operator. Closes F16.
- **G11 — Revision compaction.** Weekly compaction retains first + last + every-10th revision for
  todos; personality-answer retention keeps the most recent 12 revisions plus all bootstrap
  answers, compacting older retest answers to one aggregate row per revision. Closes F14.

### Tranche D — operator oversight and identity integrity

- **G12 — Operator review gate on self-ontology writes.** Every `write_contributor(origin=self)`
  targeting a `personality_facet` or `passion` writes to a staging table
  (`self_contributor_pending`), not the live activation table; a weekly digest queues operator
  ACK; unreviewed rows are invisible to `active_now`. Declines (self-model refusing a request) also
  route through this digest. This is the largest single design change the audit proposes — it
  changes the self from "writes freely" to "proposes, operator ratifies" for load-bearing
  facet/passion edges, and is treated as its own design discussion before implementation, not a
  drop-in. Closes F18 (critical), F22.
- **G13 — Self-id ownership enforcement at the repo layer.** Every repo-layer write takes an
  explicit `acting_self_id`; a mismatch against the target row's `self_id` raises `CrossSelfAccess`
  — a second line of defense below the tool-surface `PermissionError` check. Closes F24.
- **G14 — FK from every self-table to `self_identity`.** Phantom-self writes (typo'd `self_id`)
  fail at the DB layer via `FOREIGN KEY (self_id) REFERENCES self_identity(self_id)`. Closes F25.
- **G15 — Bootstrap seed registry and collision detection.** `run_bootstrap` refuses to reuse a
  seed unless `--allow-seed-reuse` is explicit; reuse is itself recorded as a LESSON memory the
  self carries. Closes F26.
- **G16 — Signed bootstrap audit record.** The finalize LESSON memory is signed with the
  deployment's operator key; verification is mandatory before the self serves requests, and a
  rotated key requires re-signature. Tamper detection places the self into read-only mode with an
  explanatory OPINION memory. Closes F26 (forensic integrity).

### Tranche E — runtime firewall

- **G18 — Self-tool import firewall.** `SELF_TOOL_REGISTRY` is exposed only via a `SelfRuntime`
  object instantiated at program start, never via direct module import; an `importlib` meta-path
  finder raises `ForbiddenImport` on any attempt to import it from outside `turing.self_*`.
  Specialist agents get a separate `SpecialistRuntime` with no self-tools wired. This makes the
  "self-tools are trust-tier t0 and unreachable from specialists" contract (source spec
  `self-surface.md` AC-28.22/28.23) an enforced boundary instead of a convention. Closes F21.

### Mapping to the migration spec

Tranches A and E must land as part of `docs/TURING-MIGRATION-SPEC.md` Phase 3 (Self-Model) —
specifically wherever `self_nodes.py`, `self_todos.py`, `activation.py`, and `tool_registry.py`
are ported. Tranches B, C, and D may land incrementally across Phase 3 and Phase 8 (Remaining
Self-Model + Polish), but **no personality-retest, activation-graph-write, or node-creation code
merges ahead of its guardrail** — the ordering in the migration spec's phase checklist is amended
to interleave guardrail tasks with the corresponding port tasks, not follow them.

Two findings the audit flagged as `critical` are not closed by any guardrail above because they
are not security findings so much as missing wiring, and are called out here so Phase 3/8 planning
does not silently drop them: **F38** (self-model writes never mirror to episodic memory — the
activation graph's dependency on memory contributors, and G12's operator digest, both assume this
wiring exists) and **F39** (the self-as-Conduit request pipeline is entirely unwired in the source
sketch). Both must be resolved as ordinary implementation work in Phase 3/7 of the migration spec;
they are noted here because G7's memory-weighted contributor math and G12's operator digest are
silently no-ops without F38 fixed first.

## Consequences

- Every self-model write path ships with its Warden scan, budget check, and forensic tag from the
  first PR that introduces it — there is no window where an unscanned, unbudgeted self-write path
  exists in this repo (unlike the source sketch, which had one from the start).
- `docs/TURING-MIGRATION-SPEC.md` Phase 3 and Phase 8 checklists gain guardrail sub-tasks; the
  phase effort estimates in that document do not yet include this work and should be revised
  alongside the phase-3 kickoff.
- The G12 operator-review gate is a real product decision (self writes freely vs. self proposes /
  operator ratifies for facet/passion edges) — it needs its own design sign-off before Phase 3
  implements `write_contributor`, not a silent default.
- This ADR's guardrails become the acceptance criteria a follow-up SPEC (or a set of per-guardrail
  SPECs, matching the audit's "each guardrail needs a dedicated spec + implementation PR") will
  cite; this ADR does not itself specify schemas, migrations, or the `SelfRuntime` class shape —
  see Non-goals.
- Formal property tests for G1–G18 belong under `formal/` alongside the existing Warden/Sentinel
  conformance suite (e.g. `formal/models/test_warden_detector.py`,
  `formal/models/test_sentinel_policy.py`) once the self-model write path exists to test against;
  none exist yet because the write path itself does not exist yet.

## Non-goals

- Re-deriving or second-guessing the self-model's design (Tulving autonoetic-memory framing,
  HEXACO personality model, activation-graph math). This ADR only tightens the write/growth/review
  boundary around a design already decided elsewhere.
- Specifying the on-disk schema for `self_contributor_pending`, `self_bootstrap_seeds`, or any
  other guardrail-introduced table — deferred to the per-guardrail implementation SPECs.
- The `SelfRuntime`/`SpecialistRuntime` class shapes and the `importlib` meta-path finder mechanics
  for G18 — implementation detail for the Phase 3 PR.
- **Post-hoc memory poisoning via tool results** (audit's own out-of-scope note): Warden scans
  tool results at the ADR-073 boundary, but a false-negative that passes Warden still shapes mood
  and self-model writes downstream. Not addressed by G1–G18; flagged as a follow-up.
- **The self's relationship to Sentinel** — whether a Sentinel block on a `reply_directly` output
  mints a REGRET memory — is unspecified by the source design and out of scope here.
- **Multi-self reconciliation semantics** (what happens if a self is ever forked or split) — the
  source design's own DESIGN.md flags this as unresolved; this ADR does not resolve it.
- Re-litigating "the three laws" framing the source audit explicitly declined to address.

## Source references

- `research/project-turing/AUDIT-self-model-guardrails.md` (AgentTuring repo) — Tranche 6 audit,
  findings F1–F39, guardrails G1–G18.
- `docs/TURING-MIGRATION-SPEC.md` — migration phase plan; Phase 3 (Self-Model) and Phase 8
  (Remaining Self-Model + Polish) are where this ADR's acceptance criteria apply.
- `packages/maistro-turing/src/maistro_turing/self_model/` — current state (types only; repo,
  activation graph, and tool registry not yet ported).
- `docs/adr/ADR-072-threat-model.md` — engine-wide threat model this ADR extends into the
  self-model's write boundary.
- `docs/adr/ADR-073-warden-sentinel.md` — the Warden/Sentinel substrate G1 wires the self-model
  write path into.
