# M8-C3 research note — adaptive context budgeting, hierarchical compression, selective omission

Leaf: #922. Epic: #901 (M8-C). Initiative: #879.

## Hypothesis

Dynamically choosing how much context to retrieve, compress, summarize, or omit — based on
task complexity, evidence density, uncertainty, and context-window pressure — improves
long-horizon Agent performance and reduces token cost versus the fixed top-k/context limits
the shipped policy uses. Hierarchical summaries and selective omission of redundant or
low-value memories are the compression levers.

## Canonical seams

The seam this leaf evaluates is the context-assembly spine (ADR-091 / SPEC-244):
`packages/maistro-core/src/maistro/memory/context_assembly.py`. Three shipped facts define
the experiment space:

- **The budget is a constant.** `ContextBuilder.build` hands every assembly a fixed
  `system_token_budget = 4096` tokens (`_DEFAULT_SYSTEM_TOKEN_BUDGET`) — the same budget for
  a one-clause question and a multi-constraint audit, for an 8k window and a 200k window.
  Nothing in the shipped path turns that knob. That constant is exactly the baseline the
  hypothesis is about.
- **The pack is whole-item, banded, and skip-not-break.** `_pack` takes whole memories in
  rank order; weight >= 0.6 (`ALWAYS_INCLUDE_WEIGHT`) is taken whatever the budget says and
  may overspend it; below the band a memory is taken only while it fits whole, a miss is
  skipped (never truncating the scan), and a later smaller memory may still fit. Because
  ADR-091's weight bands are exactly the `WEIGHT_BOUNDS` tier ladder, the always-include
  band **is** REGRET/AFFIRMATION/WISDOM: a budget cut can only ever land on OPINION- and
  LESSON-tier memories. That consequence is measured below, not assumed.
- **Layer 2 (rolling compression, SPEC-189) ships as an explicit `""` placeholder**, so
  every summarizer in this leaf is a hypothetical, clearly labeled, and a candidate for a
  future Layer 2 — never a third authority. Ranking feeding the pack is
  `(keyword_overlap + cosine) * weight` (ADR-080 part D / SPEC-243) with the shipped
  no-credential vector term (`no_vector = 0.0`) — the configuration
  `ScoredEpisodicRetrieval` actually ships in deterministic CI — and the lexical term's raw
  word-split (no stopword handling) is kept: generic words like "the" match every memory
  containing them, and the budget policies below pay for that shipped behavior.

## Record

No provider experiment exists: the deterministic CI environment holds no model credentials,
no real Workspace histories, and no judged answer-quality corpus; manufacturing any was out
of scope, and absent evidence is recorded rather than simulated (M8 guardrail 3). No product
code, flag, or authority path changed.

What this leaf adds is the reproducible measurement machinery the issue's benchmark demands,
as evidence-only research code:
`packages/maistro-rsi/tests/test_m8c3_context_budgeting_research.py` (41 checks). It imports
no maistro module — research evidence, never an authority (epic contract) — and replicates,
for measurement only, `_estimate_tokens` (`len // 4`), `_pack` (bands, whole items,
skip-not-break), `ranking.score`/`rank` (zero-score drop, stable descending sort), the
Layer 3 wisdom band (two zero-overlap adversarial WISDOM memories force-seeded into every
context, overspending every tight budget exactly as the shipped layer does), and the
production tier ladder. Against a pinned, hand-checked corpus (30 memories across five
topics on the SPEC-240 ladder, 4 near-duplicate paraphrase pairs, in-band noise, 12 labeled
critical facts — 7 in the always-include band, 5 budget-cuttable in OPINION/LESSON — each
with a verbatim probe and, for five of them, required qualifier tokens), it measures the
issue's full list: critical-fact recall, evidence sufficiency (the deterministic stand-in
for answer quality: a fact counts only if its probe text reaches the prompt), lost-
critical-fact rate, token cost (production `len // 4` accounting including band overspend),
work-unit latency (structural orderings only, never wall-clock), summary distortion (a
served probe whose required qualifier tokens a summarizer dropped) and fabrication (summary
text that is not a verbatim substring of a source memory — zero by construction for an
extractive pipeline, and checked), and stability across three model-window stand-ins
(512 / 4096 / 16384 tokens at the shipped ~30% memory share).

Policies compared: the fixed budget (a sweep — 4096 is one point the hypothesis asks to
beat), complexity-scaled budget (distinct query tokens → 0.5x / 1.25x / 1.75x of a 90-token
base), an evidence-density saturation stop (select while marginal new-token share >= 0.35),
a score-margin stop (sub-band selection stops at the first candidate below 0.45x the top
score), near-duplicate omission (token Jaccard >= 0.6), window-pressure packing with a
hierarchical fallback, and the combination. The hierarchical tier reserves 25% of the
window budget for extractive cluster summaries — the reservation is a measured necessity,
not a tuning choice: the shipped pack is skip-not-break, so a summary tier waiting for
leftovers never gets any (measured: zero remainder at every window).

Main table (12 queries, 20 fact askings; mean tokens include the forced wisdom seed's
overspend; distortion is 0.000 everywhere for the qualifier-safe summarizer):

| policy | mean tokens | recall | sufficiency | lost-fact rate | overspend q | work units |
|---|---|---|---|---|---|---|
| fixed 40 | 148.5 | 0.800 | 0.667 | 0.333 | 12 | 720 |
| fixed 60 | 161.0 | 0.800 | 0.667 | 0.333 | 12 | 720 |
| fixed 90 | 172.4 | 0.900 | 0.833 | 0.167 | 11 | 720 |
| fixed 120 | 179.8 | 0.950 | 0.917 | 0.083 | 9 | 720 |
| adaptive complexity | 167.8 | 0.950 | 0.917 | 0.083 | 12 | 720 |
| density stop (cap 157) | 173.3 | 0.950 | 0.917 | 0.083 | 8 | 841 |
| margin stop (cap 157) | 118.5 | 0.850 | 0.750 | 0.250 | 4 | 895 |
| omission at 90 | 163.6 | 0.900 | 0.833 | 0.167 | 11 | 841 |
| full adaptive | 173.9 | 0.900 | 0.833 | 0.167 | 12 | 1115 |

Findings (synthetic hand-checked corpus — mechanism evidence, **not** evidence about real
models or real Workspaces):

1. **The band, not the budget, decides where losses can land.** At every swept budget,
   every weight >= 0.6 fact is served (pinned per budget x query); all losses are confined
   to the five OPINION/LESSON facts. Any budget debate that ignores ADR-091's always-include
   band is debating a knob that cannot touch REGRET-and-above memory. The same band
   overspends every tight budget on every query (the forced wisdom seed alone is 35 tokens),
   which is why fixed-40 and fixed-60 mean spends differ by only 12 tokens despite a 50%
   budget gap.
2. **Complexity scaling is the one adaptation that paid, and only at the margin.** Scaling
   the budget by query surface (45 / 112 / 157 tokens) matches the 120-token fixed point's
   recall (0.950) at 167.8 mean tokens (vs 179.8) and beats its own 90-token base point
   outright (0.950 vs 0.900): at the medium bucket the extra 22 tokens land exactly where
   the fixed policy's crowd-out dropped the chargeback fact. It does **not** rescue the
   rollback fact on the adversarial query — that fact sits at the lexical ranker's noise
   floor (it shares only a stop word with the query), and no budget, however large, retrieves
   what ranking buried. Budget adaptivity shifts the frontier; it does not conjure evidence.
3. **Selective omission bought tokens, not facts.** Dropping near-duplicates cuts mean spend
   (163.6 vs 172.4 at the same 90 budget) with **identical** recall: the shipped pack is
   skip-not-break, so the next banded memory consumes whatever the duplicate freed. Omission
   is a cost lever under band crowd-out, not a quality lever. The density stop subsumes it
   and holds the 120-point recall at its cap — the two levers overlap almost entirely on
   this corpus.
4. **The margin stop is a measured negative.** Ending sub-band selection at the first
   candidate below 0.45x the top score loses mid-score facts the plain pack keeps (recall
   0.850 vs 0.900): score plateaus on a raw-split lexical ranker are not evidence
   boundaries. Recorded as the leaf's clearest don't-ship.
5. **Hierarchical compression needs a reserved allowance, and even then it is recall-neutral
   here.** With 25% of the window budget reserved for extractive cluster summaries, the
   summaries engage under pressure (8 of 12 queries at the smallest window) and carry
   verbatim probes with zero fabrication — but recall is exactly the fixed policy's at every
   window (0.950 / 1.000 / 1.000 on both): the one fact the cut dropped sits at the ranker's
   noise floor, and a summary tier ordered by the same ranker is blind to it too. This is
   C2's boundary ("reranking cannot promote a memory the recall stage never returned")
   re-found one layer up: **compression can only repackage what ranking surfaces**. What
   the summaries did change: +23 mean tokens at the small window (the tier costs at most its
   allowance over the fixed policy — pinned) and a real distortion hazard (next finding).
6. **Summary distortion is real and summarizer-shaped.** The qualifier-safe summarizer
   (first sentences plus any negation/condition-marked sentence, label-free) serves every
   qualifier-bearing probe undistorted with zero fabricated text; the naive
   first-sentence-only summarizer serves the same probes with every qualifier dropped
   ("the freeze **only** lifts **after** the all-clear" becomes "deploys freeze on Friday")
   — a served fact inverted in meaning, undetectable by any recall metric. Any Layer 2
   compression proposal must carry a distortion check of exactly this shape.
7. **Policy composition has a tax.** Stacking complexity scaling + omission + density +
   the summary allowance lands at the 90-point fixed policy's recall (0.900) — the allowance
   carves its reserve out of the item budget and at the medium bucket that reserve is
   precisely the slot the chargeback fact needed. Composition gave back the win that
   complexity scaling alone made. Where the reserve is charged (crowd vs facts) is the open
   engineering question this measurement hands forward.
8. **High-weight noise displaces; nothing budget-shaped fixes it.** Injecting ten off-topic
   fillers (two just inside the always-include band, eight at observation weight) drops
   recall 0.950 -> 0.850 and raises lost-fact rate 0.083 -> 0.250 at fixed 120; the banded
   fillers alone force ~22 tokens into every context. No policy in the table improves under
   injection (pinned for 5 and 10 fillers); the density stop absorbs it best (it skips the
   near-identical fillers wholesale). The fix for noise is upstream in what earns weight
   (SPEC-240), as C1/C2 also concluded.

Executed probe record (head af7996883, 2026-10-08):
`uv run pytest packages/maistro-rsi/tests/test_m8c3_context_budgeting_research.py -q`
-> 41 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module; the
full `packages/maistro-rsi/tests` suite passes (1236). Mutation checks — each pinned finding
fails when its cause is removed: deleting the always-include band from `_pack` flips the
band-overspend, band-confinement, margin-negative and composition pins (6 failures);
freezing the complexity multiplier flips the two adaptivity findings; disabling omission
(tau -> 2) flips the omission savings; removing the summary allowance flips both summary-
engagement pins and the composition tax; stripping the qualifier-safe summarizer's marker
sentences flips 19 summary/distortion/stability pins; injecting one fabricated summary
sentence flips exactly the fabrication check; turning skip-not-break into break flips the
density, omission and composition findings; disabling the density stop flips its mechanic
pin; padding zero-score memories back into the rank flips the rank identity, the density
finding and the window token bound.

## Benchmark procedure (what a real experiment must do)

1. Export real assembly traces: for a fixed query set, capture the ranked candidates, the
   packed selection, and the final prompt at the shipped 4096 budget, plus judge labels for
   which memories were load-bearing (the evidence that actually served the answer, per
   ADR-017 traces). Labels are the experiment.
2. Sweep the fixed budget across model context sizes (4k / 8k / 32k / 128k windows) to map
   the real quality-cost frontier of the constant; then run the adaptive policies against
   the matched-mean-spend points on that frontier, with a real LLM summarizer (logging its
   own outputs) in the hierarchical tier and a real judge scoring answer quality and
   summary distortion, not just probe presence.
3. Measure the issue's full list per policy: task quality, evidence recall, token cost,
   wall-clock latency p50/p95, lost-critical-fact rate, summary distortion against judge
   labels, and stability (variance of quality) across context sizes.
4. Report the dominance frontier and the failure classes the winner still ships; update
   this disposition with the numbers; route any adoption to the SPEC-244/ADR-091 owner —
   the budget knob, the band, and Layer 2 are that spec's surface, and a budget policy that
   reads anything beyond `budget_tokens` changes the `ContextAssemblyPolicy` protocol, so it
   needs that spec amended, not a parallel implementation.

## Trust boundary

The harness is test-only code that imports no maistro module (AST-pinned by its own contract
test): it cannot become a second assembly authority, budget authority, or compression
authority (epic contract). No product code, flag, model call, or cache is added; the
canonical assembly path, its bands, and its fixed budget are untouched. Any adoption —
complexity-scaled budgets, a density/margin stop, omission, a Layer 2 summarizer — routes to
the SPEC-244 owner and must pass the normal architecture and evidence gates; a summarizer
that rewrites rather than extracts additionally changes the distortion surface measured here.

## Disposition

**WATCH.** The mechanisms are real and now measured on a pinned corpus, but the evidence
base is synthetic and the two largest measured wins carry recorded boundaries: complexity
scaling paid only at the margin band (and cannot recover rank-buried facts), and
hierarchical compression was recall-neutral here while introducing the distortion hazard
finding 6 quantifies. Negative findings are recorded as first-class: the margin stop should
not ship; omission is a cost lever only under band crowd-out; naive summarization inverts
served facts.

Escalate to **INCUBATE** when a real-trace experiment (procedure above) shows on the
canonical seam that (a) complexity-scaled budgets hold answer quality at a measured token
saving across at least two window sizes, and (b) a qualifier-safe extractive Layer 2 holds
judge-scored distortion at or below a pinned bound while cutting prompt tokens — with the
distortion check from finding 6 as part of the evidence. Escalate to **REJECT** if the real
experiment shows the wins were corpus artifacts or the summary tier cannot beat the
distortion bound. The band-confinement finding (1) is worth carrying into the SPEC-244
discussion regardless of disposition: it is a property of the shipped ADR-091 ladder, not of
this leaf's prototypes.
