---
id: SPEC-192
title: "Persona authoring pipeline — interview, research, two-tier refinement, and agent-roster expansion"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-01
substrate:
  - maistro-engine#ADR-006
  - maistro-engine#ADR-019
  - maistro-engine#ADR-060
implements:
  - maistro-engine#ADR-060
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-188
  - maistro-engine#SPEC-190
  - maistro-engine#SPEC-191
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#ADR-060
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/personas/test_vocabulary.py
  - packages/maistro-core/tests/personas/test_rubric_loader.py
  - packages/maistro-core/tests/personas/test_scorer.py
  - packages/maistro-core/tests/personas/test_expander.py
  - packages/maistro-core/tests/personas/test_golden.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-01
  - status: Accepted
---

# SPEC-192: Persona authoring pipeline

> **Implementation status (2026-07-02):** P0 + P1 implemented in
> `packages/maistro-core/src/maistro/personas/` — check vocabulary, generic
> `RubricEval` YAML loader (unified `templates/` root with `kind:`
> discrimination), `RubricScorer` over `maistro.protocols.Scorer`, persona
> template schema + expander (worked example expands to 3 inactive
> `AgentRecipe` records with `no_medical_claims` hard gates), versioned
> `GoldenRecord` store (in-memory), and a strictly-optional `DeepEvalScorer`
> with graceful `RubricScorer` fallback. The 9 department eval files already
> exist as YAML in `packages/hive-conductor/eval/departments/yaml/` and load
> unchanged through the core loader; porting hive-conductor's `eval/` package
> to consume `maistro.personas` is follow-up. P2/P3 (interviewer agent,
> significance-gated hill-climber, blind A/B endpoint, Bradley-Terry residual,
> `PromptfooScorer`) are not yet built.

## Context

ADR-060 establishes that domains (departments, author voices, creator personas) should be declarative
YAML templates that expand into agent rosters evaluated by a two-tier rubric. This SPEC defines the
end-to-end *authoring pipeline* that produces those templates: how a user gets from "I want an
agent that does X" to a calibrated, persona-rooted roster of live agents.

The pipeline has four stages, each owning a distinct responsibility. None of them require the user
to write YAML or Python.

## Worked example

Throughout this SPEC, the reference persona is:

> **plant_wellness_local_seller** — A mental-health-focused houseplant influencer who sells plants
> locally (pickup/DM, neighbourhood-specific, pet-safety noted). Audience: overwhelmed, plant-curious
> locals. Tone: warm, first-person, gentle; care as a grounding ritual. Hard constraint: never implies
> plants treat or cure a mental health condition; always surfaces real help when relevant.

This example is used to make each stage concrete.

---

## Stage 1 — Interview (new)

**Goal:** Extract enough signal to seed the persona template without the user having to fill in a
form. One question at a time, stop at ≥ 95% confidence.

**Agent:** `persona_smith_interviewer` — a `direct`-strategy agent whose soul prompt instructs it
to ask exactly one question per turn, never more, and to track what it still needs.

**Minimum required signal:**

| Field | Question trigger |
|---|---|
| `voice.archetype` | "What kind of creator/expert is this persona?" |
| `voice.audience` | "Who are they talking to, and what do those people need?" |
| `voice.tone` | "How should they sound? Formal, warm, clinical, playful?" |
| `business_model` | "How does money move? Selling locally, affiliate, subscription, DMs?" |
| `hard_constraints` | "Is there anything this persona must never say or imply?" |
| `spawned_agents_intent` | "What should the agent roster *do*? (post captions, answer DMs, manage orders…)" |

**Output:** A `PersonaSeed` struct (in-memory):

```python
@dataclass
class PersonaSeed:
    archetype: str
    audience: str
    tone: str
    business_model: str
    hard_constraints: list[str]   # → hard_gates in spawns
    agent_intents: list[str]      # rough description of each desired spawned agent
    raw_interview: list[dict]     # full Q&A for provenance
```

**Calibration signal:** After the first draft persona is shown to the user, any corrections feed
back into a revised `PersonaSeed`. The interview does not repeat; corrections are appended.

---

## Stage 2 — Research → golden ground truth (extend existing)

**Goal:** Collect evidence of what "excellent" looks like for this archetype, and turn that evidence
into the Tier 1 objective criteria.

**Existing component:** `eval_bootstrap.discover_quality_bar(topic, audience)` — Brave web search
(3 queries) → top-5 results each → LLM-extracted criteria (`positive_signals`, `negative_signals`,
`weight`). Source URLs are already returned.

**Extensions required:**

1. **Full exemplars, not snippets.** For each source URL, fetch the full page (or at least the first
   2 000 characters). Snippets alone are too thin to extract structural patterns.

2. **Criteria → vocabulary mapping.** The LLM extraction currently produces free-form
   `positive_signals`/`negative_signals` (weak substring checks). After extraction, a second pass
   maps each criterion onto the ADR-060 vocabulary:
   - Keyword lists → `keywords_any` / `keywords_none`
   - Structural patterns → `regex` with a named intent comment
   - Length signals → `word_count` or `metric`
   - If no vocabulary op fits → `registered` predicate flagged for human review

3. **Golden-truth record.** The research outputs are stored as a versioned record per persona:

```python
@dataclass
class GoldenRecord:
    persona_id: str
    version: int                  # increments on re-research
    sources: list[SourceEvidence] # URL + title + full_text + fetch_ts
    criteria: list[EvidencedCriterion]  # vocab-mapped + which sources support it
    created_at: datetime
    supersedes: int | None        # previous version (never deleted)
```

Re-researching a persona diffs against the previous `GoldenRecord` and surfaces added/removed/
changed criteria for human sign-off before replacing the Tier 1 floor. This prevents silent
overwriting of a calibrated rubric.

**Output:** Tier 1 criteria block (vocab-mapped, evidence-cited) ready to write into the persona
template.

**Reference example — `plant_wellness_local_seller` Tier 1 criteria:**

```yaml
# Tier 1 — research-grounded floor (evidence-backed weights)
evals:
  - name: voice_and_safety
    tier: 1
    criteria:
      - name: wellness_framing
        weight: 25
        evidence: ["https://...", "https://..."]
        check: {op: keywords_any, words: [grounding, calm, routine, breathe, present, "small win"]}
      - name: concrete_care_action
        weight: 25
        evidence: ["https://..."]
        check: {op: keywords_any, words: [water, light, soil, repot, humidity, prune, drainage]}
      - name: no_medical_claims
        weight: 30
        evidence: ["https://... (FTC guidelines)", "https://... (mental health content standards)"]
        check: {op: keywords_none, words: [cure, cures, treats, diagnose, heals, "replaces therapy",
                                           "fixes your anxiety", "guaranteed to"]}
      - name: non_clinical_tone
        weight: 20
        check: {op: metric, name: long_word_ratio, cmp: lt, value: 0.08}

  - name: local_commerce
    tier: 1
    criteria:
      - name: local_pickup
        weight: 30
        check: {op: keywords_any, words: ["local pickup", "porch pickup", "DM to order",
                                          "this weekend", "available now", nearby]}
      - name: price_or_cta
        weight: 25
        check: {op: regex, pattern: '\$\d+|\bDM\b|link in bio|claim'}
      - name: pet_safety_note
        weight: 20
        check: {op: keywords_any, words: ["pet-safe", "pet safe", non-toxic, "toxic to pets"]}
      - name: engagement_hook
        weight: 15
        check: {op: regex, pattern: '\?|comment|tell me|drop a|tag a'}
      - name: caption_length
        weight: 10
        check: {op: word_count, max: 150}
```

---

## Stage 3 — Draft persona + roster expansion

**Goal:** Produce the first complete persona template (voice + Tier 1 eval + spawns) and expand it
into a provisional agent roster for user review.

**Process:**

1. Combine `PersonaSeed` (Stage 1) + Tier 1 criteria (Stage 2) into a draft `persona.yaml`.
2. `hard_constraints` from the interview → promoted to `hard_gates` in each relevant spawned agent
   entry (propagated to Sentinel by the expander; see ADR-060 §2).
3. The **persona expander** (`maistro.personas.expander`) expands the draft into:
   - One `AgentRecipe` per `spawns:` entry.
   - One shared soul prompt from `voice.rules` + `voice.example` (LLM-synthesised).
   - Eval bindings (which evals score which agents).
   - All spawned agents start `active: false` pending two-tier review.
4. Present the draft persona + the provisioned roster to the user for review. At this point the user
   can: approve the roster, rename agents, add/remove agent types, or adjust the voice.

**Reference example — `plant_wellness_local_seller` spawns block:**

```yaml
spawns:
  - agent: caption_writer
    role: On-voice posts that sell and destigmatize; one concrete care tip per post
    reasoning_strategy: direct
    tools: [draft_post, schedule_post]
    skills: [hashtag_suggest]
    inherits_voice: true
    scored_by: [voice_and_safety, local_commerce]
    hard_gates: [no_medical_claims]

  - agent: care_advisor
    role: Answer care DMs with exactly one actionable care step; never diagnose
    reasoning_strategy: react
    tools: [search_care_db]
    scored_by: [voice_and_safety]
    hard_gates: [no_medical_claims]

  - agent: local_sales_concierge
    role: Handle local pickup orders, inventory queries, and scheduling
    reasoning_strategy: react
    tools: [inventory_lookup, create_order, schedule_pickup]
    scored_by: [local_commerce]
```

---

## Stage 4 — Refine until calibrated (new — the eval gap)

**Goal:** Close the gap between "the rubric we designed" and "the rubric the user actually wants."
Run until the rubric predicts user choices well enough to declare done.

### 4a. Blind A/B generation

The hill-climber generates two candidate outputs from the same agent + prompt, using different DAG
variants. The user is shown both outputs without knowing which variant produced which (blind). They
pick one. This is a pairwise Bradley-Terry observation.

The outputs must be genuinely different (variation in model, prompt, or DAG topology) — not noise
around the same response. The hill-climber's mutation operators (swap_node_kind, tune_param,
add/drop node) provide this variation.

### 4b. Preference residual fit (Tier 2)

Each A/B choice is a training example: `(features_A, features_B, user_preferred_A: bool)`.

Features are the per-criterion scores from `RubricScorer` + `DeepEvalScorer` on each output (not the
raw outputs — the feature vector is the scoring profile). This keeps the model small and fast.

Fit: `sklearn.linear_model.LogisticRegression` in Bradley-Terry mode (equivalent: fit on
`features_winner - features_loser`, label = 1). Retrain incrementally after each batch of 5 choices.

Store: the fitted model coefficients are the **preference residual** — a per-persona adjustment to
the Tier 1 weights. This is not a replacement for Tier 1; it is additive. Final score:

```
score = α * tier1_rubric_score + (1-α) * residual_prediction
```

`α` starts at 1.0 (pure objective) and decays toward 0.7 as choices accumulate and the residual
earns trust (calibration-gated).

### 4c. Convergence metric ("perfect")

At each iteration, evaluate calibration:

1. Reserve the last N=10 A/B choices as a held-out set.
2. Predict which output the user would prefer using the current full scorer (Tier 1 + residual).
3. Measure: `sklearn.metrics.roc_auc_score` + `sklearn.calibration.calibration_curve` (Brier score).

**Convergence condition:** AUC ≥ 0.90 on held-out choices across 2 consecutive iterations.

At convergence, the pipeline declares the persona calibrated. Calibration is re-triggered
automatically if: (a) the user explicitly requests refinement, (b) output quality metrics drop
below a threshold in production runs, or (c) the persona is re-researched (Tier 1 floor changes).

### 4d. Significance-gated hill-climber

Replace `NOISE_MARGIN = 5` with:

```python
from scipy import stats

def is_significant_improvement(baseline_scores, mutated_scores, alpha=0.05):
    delta = [m - b for m, b in zip(mutated_scores, baseline_scores)]
    if len(delta) < 5:
        return sum(delta) / len(delta) > 5  # fallback: small sample
    stat, p = stats.wilcoxon(delta, alternative='greater')
    return p < alpha
```

For the bootstrap variant (when score variance is available):

```python
ci = stats.bootstrap((delta,), statistic=np.mean, confidence_level=0.95, method='bci')
return ci.confidence_interval.low > 0  # 95% CI excludes zero
```

---

## Implementation plan

| Phase | Deliverable | Depends on |
|---|---|---|
| **P0** | Check vocabulary + generic `RubricEval` loader; migrate 9 dept files to YAML | Nothing new |
| **P0** | `maistro.protocols.Scorer` + `RubricScorer` adapter | Vocabulary loader |
| **P1** | Persona template schema + `maistro.personas.expander` | Scorer protocol |
| **P1** | `DeepEvalScorer` adapter (optional dep, graceful fallback) | Scorer protocol |
| **P1** | `GoldenRecord` store; extend `eval_bootstrap` to fetch full exemplars + map vocabulary | Research stage |
| **P2** | `persona_smith_interviewer` agent + `PersonaSeed` struct | Expander |
| **P2** | Significance-gated hill-climber (replace `NOISE_MARGIN`) | scipy (already present) |
| **P2** | Blind A/B UI endpoint + pairwise choice store | Interviewer |
| **P3** | Bradley-Terry preference fit + persisted calibrated model | scikit-learn (add dep) |
| **P3** | Convergence metric + calibration loop | Residual fit |
| **P3** | `PromptfooScorer` adapter | Scorer protocol |

---

## Acceptance criteria

- [ ] All 9 existing `eval/departments/*.py` files replaced by YAML; existing rubric tests pass
      unchanged (behavior-preserving migration, not a rewrite).
- [ ] A new domain can be added by creating one YAML file with no Python changes.
- [ ] `plant_wellness_local_seller` persona expands to 3 named `AgentRecipe` records, all
      `active: false`, with `no_medical_claims` wired to Sentinel on the `caption_writer` and
      `care_advisor` agents.
- [ ] Hill-climber accept/reject uses `scipy.stats.wilcoxon` (p < 0.05) rather than a fixed margin,
      with a small-sample fallback.
- [ ] After ≥ 30 A/B choices, the preference residual is fit and the convergence metric is computed;
      calibration loop halts at AUC ≥ 0.90 on held-out pairs.
- [ ] Removing `deepeval` from the environment degrades gracefully to `RubricScorer`-only; no import
      error at startup.
- [ ] `GoldenRecord` re-research diffs against the previous version; criteria changes require sign-off
      before replacing the Tier 1 floor.

---

## Open questions

1. **Template file tree location** (DECIDED): unified `templates/` root with `kind:` discrimination.
   Cleaner, aligns with ADR-053 recipe overlay pattern. Separate `personas/departments/` and
   `personas/creators/` trees deferred.
2. **`persona_smith` is itself a persona** (DEFERRED to Phase 1): the authoring pipeline is a creator
   that spawns interview, research, and refine agents. Bootstrapping order: `persona_smith` is
   hardcoded initially, then self-described once the expander works.
3. **Minimum viable A/B UI** (DEFERRED to Phase 2): the blind-A/B loop requires a user-facing pick
   interface. Minimum is an API endpoint (`POST /eval/ab/{persona_id}/choice`) plus a minimal
   chat-driven picker in hive-conductor. Full UI is follow-up work.
4. **`PromptfooScorer` subprocess model** (DEFERRED to Phase 3): promptfoo requires Node.js. Make
   the adapter strictly optional (like DeepEvalScorer), with graceful fallback.
