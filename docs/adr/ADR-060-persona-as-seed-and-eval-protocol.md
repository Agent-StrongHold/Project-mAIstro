---
id: ADR-060
title: "Persona-as-seed: declarative domain templates, pluggable Scorer protocol, and two-tier eval statistics"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-06-01
substrate:
  - maistro-engine#ADR-006
  - maistro-engine#ADR-019
  - maistro-engine#ADR-036
implements: []
related:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-042
  - maistro-engine#ADR-059
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-01
---

# ADR-060: Persona-as-seed — declarative domain templates, pluggable Scorer protocol, and two-tier eval statistics

## Context

Three related problems converge here.

**Problem 1 — departments are Python when they should be data.**
`eval/departments/*.py` (9 files, ~400 lines total) are pure data expressed as code: a `department`
string, an `eval_name` string, and a `criteria` list of dicts whose `check` keys are lambdas over a
vocabulary small enough to enumerate. Adding a new domain (project management, a creator persona, an
author voice) requires a code change, a review, and a deploy. The same work should be a YAML file.

**Problem 2 — personas stop at description; they should spawn agents.**
Authors, creators, and influencer archetypes (e.g. a mental-health-focused plant-seller) are a higher-
level concept than an individual agent. A persona is a *domain seed*: one template that, when expanded,
produces a coherent roster of `AgentRecipe`/`AgentIdentity` records — caption writer, care advisor,
local-sales concierge — all sharing one voice, one eval rubric, and one governance posture. The
runtime for this already exists (`recipes/`, `spawner/`, `factory.create_agents()`, ADR-006), but
nothing seeds them from a declarative template.

**Problem 3 — eval is not scientific.**
The hill-climber's accept/reject currently uses a `NOISE_MARGIN = 5` constant (added in #93) rather
than a proper significance test. The rubric's criteria-check vocabulary is strong (structural regexes
resist keyword-stuffing), but there is no preference residual — no mechanism to calibrate the rubric
against actual user choices and no convergence condition to declare "done refining." The `eval_judge`
LLM-as-judge is a single noisy sample with no confidence interval. Third-party judge frameworks
(DeepEval, promptfoo) are operationally useful but are metric libraries, not statistics engines;
importing them as if they supply the rigor inverts the dependency.

## Decision

### 1. Declarative check vocabulary

All deterministic rubric criteria are expressed in a fixed vocabulary rather than arbitrary Python.
The vocabulary is code (audited once, in one place); domains are data (a YAML file per domain).

| Op | Semantics |
|---|---|
| `keywords_any` | `any(w in output.lower() for w in words)` |
| `keywords_none` | `not any(w in output.lower() for w in words)` |
| `regex` | `bool(re.search(pattern, output, flags))` |
| `regex_absent` | `not bool(re.search(pattern, output, flags))` |
| `regex_count` | `len(re.findall(...)) >= min` (optional `max`) |
| `word_count` | `min <= len(output.split()) <= max` |
| `metric` | named scalar (avg_sentence_words, long_word_ratio, unique_word_ratio, paragraph_count, hashtag_count) compared with `lt/lte/gt/gte/eq` |
| `any` | short-circuit OR over a list of sub-checks |
| `all` | short-circuit AND over a list of sub-checks |
| `registered` | named predicate from a small audited Python registry (`maistro.eval.predicates`) — escape hatch for checks that cannot be expressed in the above |

A criterion using `registered` requires a comment justifying why the vocabulary is insufficient.

The `registered` registry is the *only* place new eval primitives are added; it is small and reviewed.
This is what keeps domain YAML files free of code.

### 2. Persona template schema

A persona template is a YAML file under `personas/` with a `kind:` discriminator.

**`kind: department`** — eval rubric only (replaces the existing Python department files).

**`kind: author` / `kind: creator`** — voice specification plus eval rubric plus a `spawns:` block.
The `spawns:` block is a list of agent declarations; each field maps 1:1 onto `AgentIdentity`:

```yaml
spawns:
  - agent: caption_writer           # → AgentIdentity.name suffix
    role: "..."                     # → AgentIdentity.description
    reasoning_strategy: direct      # → AgentIdentity.reasoning_strategy
    tools: [draft_post]             # → AgentIdentity.tools (resolved via capability registry)
    skills: [hashtag_suggest]       # → AgentIdentity.skills
    inherits_voice: true            # soul_prompt synthesised from persona.voice
    scored_by: [voice_and_safety]   # binds eval evals from this persona
    hard_gates: [no_medical_claims] # criterion promoted to Sentinel hard-block
```

The **persona expander** (`maistro.personas.expander`) takes a persona template and emits:
1. One `AgentRecipe` per `spawns:` entry, stored in the recipe registry.
2. A shared soul prompt built from `voice.rules` + `voice.example`.
3. Eval bindings: which evals score which agents, with which criteria promoted to hard gates.

Expansion is idempotent. Re-expanding a changed template diffs the old recipes and emits only changes
for review (governance: expanded agents start `active: false` until they pass the existing two-tier
review gate).

### 3. Scorer protocol

A `Scorer` protocol is added to `maistro.protocols`:

```python
class Scorer(Protocol):
    async def score(
        self, output: str, context: dict[str, Any]
    ) -> Score: ...

@dataclass(frozen=True)
class Score:
    value: float          # 0.0–1.0
    passed: bool
    rationale: str
    evidence: list[str]   # source URLs or criterion names
    provider: str         # "rubric" | "deepeval" | "promptfoo" | ...
```

Three providers ship:

| Provider | Default | Notes |
|---|---|---|
| `RubricScorer` | yes (no network) | Runs the declarative vocabulary. Fast, auditable, deterministic. |
| `DeepEvalScorer` | yes (LLM judge) | Wraps DeepEval (Apache-2.0). G-Eval, RAGAS metrics. Optional dep. Falls back gracefully if not installed. |
| `PromptfooScorer` | no | Wraps promptfoo (MIT) via subprocess. For regression matrices and red-teaming. |

The `RubricScorer` is always the primary signal. `DeepEvalScorer` is the default *judge* (LLM-graded
nuanced quality), used alongside the rubric for the preference residual. Judge providers sit *below*
the statistics layer — their noisy outputs are inputs to the stats, not trusted scores in themselves.

Selecting providers is a deployment/persona config, not a code change.

### 4. Two-tier eval statistics (L2)

The statistics layer is built on **scipy** (significance) and **scikit-learn** (preference model +
calibration). These are the actual statistics engines; the third-party judge frameworks are not.

**Tier 1 — Objective floor (rubric-grounded).**
Evidence-backed criteria from `eval_bootstrap.discover_quality_bar()` (existing: Brave search →
exemplars + source URLs → LLM-extracted criteria → mapped to the vocabulary). Weights are set by the
research phase. This tier does not change via user feedback; it can only change by re-researching the
domain.

**Tier 2 — Preference residual (learned from feedback).**
A logistic model (scikit-learn `LogisticRegression`) fit on pairwise A/B choices: given two candidate
outputs, the user picks one. The Bradley-Terry model converts a sequence of binary choices into a
consistent preference ordering. This is fit incrementally as choices accumulate and stored as a
persisted calibrated preference model per persona.

**Significance for hill-climber accept/reject.**
Replace the `NOISE_MARGIN` constant with `scipy.stats.wilcoxon` (paired) or
`scipy.stats.bootstrap` CIs on the improvement delta. Accept only when `p < 0.05` or when the
95% CI lower bound on improvement exceeds a minimum practical effect size.

**Convergence metric ("perfect").**
At each refine iteration: hold out the last N A/B choices, predict with the current rubric, measure
agreement. When the rubric predicts ≥ 90% of held-out choices correctly (Brier score / AUC via
`sklearn.calibration`), the rubric has captured user taste — the refinement loop converges. This is
the Goodhart guard: calibrating against *actual choices* (not the model's self-assessed scores)
prevents reward-hacking. The floor stays evidence-grounded throughout.

## Consequences

**Positive:**
- New domain = one YAML file, no Python, no deploy.
- Persona spawns a coherent agent roster; the same template seeds both agents and their evaluators.
- Eval gains a proper statistical foundation: significance-gated hill-climber, calibrated preference
  model, a measurable convergence condition.
- Provider pluggability: DeepEval can be dropped or swapped to promptfoo without touching application
  code.
- The `registered` escape hatch is explicit and auditable; the security property from #93 (structural
  regexes resist keyword-stuffing) is preserved and strengthened.

**Negative / tradeoffs:**
- The declarative vocabulary is less expressive than arbitrary Python. Exotic checks require a
  `registered` predicate, which is a code change. This is a deliberate constraint.
- The preference residual requires enough A/B choices to fit reliably (~30–50 pairs per eval dimension
  is a practical minimum for logistic regression to stabilize).
- scikit-learn adds a dependency (~30 MB). scipy is already present as a transitive dep.
- DeepEval as an optional dep adds install complexity; the fall-back to rubric-only must be clean.

## Open questions (track in SPEC-192)

1. **Template file tree**: `personas/departments/*.yaml` + `personas/creators/*.yaml`, or a single
   `templates/` tree with `kind:` discrimination? The latter is simpler to load uniformly; the former
   matches the existing `eval/departments/` layout.
2. **Roster: inline vs referenced**: Agent declarations inline in the persona (self-contained, easy to
   share as a unit) vs references to reusable named recipes the persona parameterizes (less
   duplication across personas). Inline is chosen for v1; references are a follow-up.
3. **Golden-truth storage**: Exemplars + source URLs + research-derived criteria should be versioned
   per persona (diff on re-research, not silent overwrite). Schema TBD in SPEC-192.
4. **Feedback → rubric update granularity**: Reweighting existing criteria (simplest) vs adding/
   dropping criteria vs the full two-tier split. The two-tier split (this ADR) is the target; v1 may
   ship reweighting only.
