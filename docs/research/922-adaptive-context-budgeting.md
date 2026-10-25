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
`packages/maistro-core/src/maistro/memory/context_assembly.py` plus its caller-side delivery
gate `packages/maistro-core/src/maistro/agents/context_builder.py`. Five shipped facts define
the experiment space:

- **The budget is a constant.** `ContextBuilder.build` hands every assembly a fixed
  `system_token_budget = 4096` tokens (`_DEFAULT_SYSTEM_TOKEN_BUDGET`) — the same budget for
  a one-clause question and a multi-constraint audit, for an 8k window and a 200k window.
  Nothing in the shipped path turns that knob. That constant is exactly the baseline the
  hypothesis is about.
- **The pool is floored.** The layer-1 store reads filter on `min_weight =
  BUDGET_INCLUDE_WEIGHT` (0.3): a memory below the floor never reaches the score, the pack,
  or the token bill. Budget policy operates on what the floor let through.
- **The pack is whole-item, banded, and skip-not-break.** `_pack` takes whole memories in
  rank order; weight >= 0.6 (`ALWAYS_INCLUDE_WEIGHT`) is taken whatever the budget says and
  may overspend it; below the band a memory is taken only while it fits whole, a miss is
  skipped (never truncating the scan), and a later smaller memory may still fit. Because
  ADR-091's weight bands are exactly the `WEIGHT_BOUNDS` tier ladder, the always-include
  band **is** REGRET/AFFIRMATION/WISDOM: a budget cut can only ever land on OPINION- and
  LESSON-tier memories. That consequence is measured below, not assumed.
- **Layer 3 force-feeds the wisdom band.** `layer3` reads every project-scoped memory at or
  above `WISDOM_WEIGHT` (0.9, bounded limit 20) into every context — band-derived, not
  query-derived. A wisdom row the layer-1 pool also returns is therefore served **twice**
  (packed item + forced seed), exactly as production ships; the harness reproduces that
  double-serve rather than idealizing it away.
- **Delivery is all-or-nothing.** `context_builder._apply_memory` wraps the assembled text
  in a `<maistro:memory>` block and drops the **entire block** when the wrapper pushes it
  past the remaining char budget (`budget_tokens * _CHARS_PER_TOKEN`): a tripped check
  delivers no memory at all — no overspend, no partial block. This gate, not the pack, is
  what an overspend answer meets in production, and it re-measured every finding below.

Layer 2 (rolling compression, SPEC-189) ships as an explicit `""` placeholder, so every
summarizer in this leaf is a hypothetical, clearly labeled, and a candidate for a future
Layer 2 — never a third authority. Ranking feeding the pack is
`(keyword_overlap + cosine) * weight` (ADR-080 part D / SPEC-243) with the shipped
no-credential vector term (`no_vector = 0.0`) — the configuration `ScoredEpisodicRetrieval`
actually ships in deterministic CI — and the lexical term's raw word-split (no stopword
handling) is kept: generic words like "the" match every memory containing them, and the
budget policies below pay for that shipped behavior.

## Record

No provider experiment exists: the deterministic CI environment holds no model credentials,
no real Workspace histories, and no judged answer-quality corpus; manufacturing any was out
of scope, and absent evidence is recorded rather than simulated (M8 guardrail 3). No product
code, flag, or authority path changed.

What this leaf adds is the reproducible measurement machinery the issue's benchmark demands,
as evidence-only research code:
`packages/maistro-rsi/tests/test_m8c3_context_budgeting_research.py` (41 checks). It imports
no maistro module — research evidence, never an authority (epic contract) — and replicates,
for measurement only, `_estimate_tokens` (`len // 4`), the floored pool read, `_pack` (bands,
whole items, skip-not-break), `ranking.score`/`rank` (zero-score drop, stable descending
sort), the layer-3 wisdom force-feed (band-derived seed, double-serve included), and —
decisively — the shipped whole-block delivery gate (wrapper chars included; a tripped gate
delivers nothing and spends nothing). Against a pinned, hand-checked corpus (30 memories
across five topics on the SPEC-240 ladder, 4 near-duplicate paraphrase pairs, in-band noise,
12 labeled critical facts — 7 above the always-include band, 5 budget-cuttable in
OPINION/LESSON — each with a verbatim probe and, for five of them, required qualifier
tokens), it measures the issue's full list: critical-fact recall, evidence sufficiency (the
deterministic stand-in for answer quality: a fact counts only if its probe text reaches the
prompt), lost-critical-fact rate, token cost (production `len // 4` accounting; a dropped
block costs zero), work-unit latency (structural orderings only, never wall-clock), summary
distortion (a served probe whose required qualifier tokens a summarizer dropped) and
fabrication (summary text that is not a verbatim substring of a source memory — zero by
construction for an extractive pipeline, and checked), and stability across three
model-window stand-ins (512 / 4096 / 16384 tokens at the shipped ~30% memory share).

Policies compared: the fixed budget (a sweep — 4096 is one point the hypothesis asks to
beat), complexity-scaled budget (distinct query tokens → 0.5x / 1.25x / 1.75x of a 90-token
base), an evidence-density saturation stop (select while marginal new-token share >= 0.35),
a score-margin stop (sub-band selection stops at the first candidate below 0.45x the top
score), near-duplicate omission (token Jaccard >= 0.6), window-pressure packing with a
hierarchical fallback, and the combination. The hierarchical tier reserves 25% of the window
budget for extractive cluster summaries.

Main table (12 queries, 20 fact askings, base budget 90). **The gate re-measured the
question**: at the swept budgets the shipped whole-block check, not the budget, decides
delivery — every row's spend is what survived the gate, and a 0.0 row delivered nothing at
all:

| policy | mean tokens | recall | sufficiency | lost-fact rate | overspend q | work units |
|---|---|---|---|---|---|---|
| fixed 40 | 0.0 | 0.000 | 0.000 | 1.000 | 0 | 720 |
| fixed 60 | 0.0 | 0.000 | 0.000 | 1.000 | 0 | 720 |
| fixed 90 | 0.0 | 0.000 | 0.000 | 1.000 | 0 | 720 |
| fixed 120 | 8.3 | 0.050 | 0.083 | 0.917 | 0 | 720 |
| adaptive complexity | 0.0 | 0.000 | 0.000 | 1.000 | 0 | 720 |
| density stop (cap 157) | 27.8 | 0.150 | 0.250 | 0.750 | 0 | 830 |
| margin stop (cap 157) | 64.1 | 0.400 | 0.500 | 0.500 | 0 | 884 |
| omission at 90 | 0.0 | 0.000 | 0.000 | 1.000 | 0 | 830 |
| full adaptive | 0.0 | 0.000 | 0.000 | 1.000 | 0 | 1078 |

Window sweep (fixed = the window's ~30% memory share; pressure = the same share with the
hierarchical fallback): fixed 512 → 17.7 mean tokens at 0.100 recall; 4096 and 16384 →
331.7 at 1.000; **pressure ties fixed exactly at every window** — delivered set, spend, and
zero surviving summaries.

Findings (synthetic hand-checked corpus — mechanism evidence, **not** evidence about real
models or real Workspaces):

1. **The whole-block delivery gate dominates every budget debate at this corpus scale.** At
   budgets 40/60/90 the wrapped block exceeds the check on every query: nothing is served,
   nothing spent, all asked facts lost. At 120 a sliver survives (8.3 mean tokens, 0.050
   recall). The always-include band still overspends at the pack (pinned per
   budget x query at the pack level), but its production consequence is all-or-nothing: the
   seed alone (three wisdom rows, one double-served through layer 1) plus any real pack
   exceeds a tight budget's chars. A budget policy helps only by keeping the **wrapped
   block** under `budget * 4` chars — budget arithmetic on items alone is debating a knob
   upstream of the one that fires.
2. **Complexity scaling cannot recover a tripped gate.** Every complexity bucket (45 / 112 /
   157) trips the check at the base sweep: identical zeros to fixed_90, recall 0.000, spend
   0.0, lost-fact rate 1.000. The knob the shipped caller never turns is **inert below gate
   fit** — it prices evidence the delivery gate then refuses wholesale.
3. **Selective omission is indistinguishable below the gate.** Dropping near-duplicates
   frees tokens, but freed tokens are unobservable through a dropped block: omission at 90
   posts identical zeros to fixed_90 (recall, spend, lost rate). Measured honestly as an
   equality — under band crowd-out plus the gate, omission is neither a quality nor, at
   this scale, even a cost lever. It can only matter where blocks already fit.
4. **The density stop is the first policy that delivers what the fixed sweep loses.** Its
   saturation cap keeps blocks small enough to fit the whole-block check where fuller packs
   drop: recall 0.150 vs the best fixed row's 0.050, with fixed_120's served set a strict
   subset of density's — at 27.83 mean tokens (pinned; disabling the stop packs past the
   delivered set at 29.4 without serving one additional fact).
5. **The margin stop nets the sweep's best recall — the gate inverted the pre-gate
   verdict.** Ending sub-band selection at the first candidate below 0.45x the top score
   sacrifices plateau members, but the sacrificed members are exactly what fattened blocks
   into the gate: the lighter frontier fits where fuller packs refuse. Recall 0.400 at 64.1
   mean tokens (pinned), every fixed row's served fact among its served facts. The same
   mechanism that made the margin stop a don't-ship before the gate was modeled makes it
   the frontier here — which finding survives is a property of the delivery gate, not of
   the stop.
6. **The hierarchical tier is a tie everywhere and never delivers a summary.** The
   band-derived wisdom seed rides in **both** policies' blocks (and double-serves through
   layer 1 on incident queries), so the summary reservation no longer buys a block small
   enough to fit where the fixed pack does not: pressure ties fixed at all three windows.
   Its summaries engage on the pre-gate drop set and spend inside the same block, so no
   summary text ever reaches a prompt (pinned at every window). The tier's distortion
   hazard is still measured at the summarizer level (finding 7), but under the shipped gate
   the tier currently cannot deliver at all.
7. **Summary distortion is real and summarizer-shaped.** The qualifier-safe summarizer
   (first sentences plus any negation/condition-marked sentence, label-free) serves every
   qualifier-bearing probe undistorted with zero fabricated text; the naive
   first-sentence-only summarizer serves the same probes with every qualifier dropped ("the
   freeze **only** lifts **after** the all-clear" becomes "deploys freeze on Friday") — a
   served fact inverted in meaning, undetectable by any recall metric. Any Layer 2
   compression proposal must carry a distortion check of exactly this shape.
8. **Composition is a total loss at this scale.** Stacking complexity scaling + omission +
   density + the summary allowance trips the gate everywhere the same cap without the
   reserve delivers: recall 0.000, spend 0.0 — not a tax on the win but the absence of any
   win. Where a reserve is charged (crowd vs facts) only becomes answerable once blocks
   fit; at production's 4096-token budget that question reopens.
9. **High-weight noise is masked by gate fit.** Injecting ten off-topic fillers (two just
   inside the always-include band, eight at observation weight) changes neither recall nor
   lost-fact rate at fixed 120: displacement changes which memories fit a block the gate
   then refuses, so delivery is identical. The pre-gate degradation story (crowd-out)
   re-enters only where blocks fit; the density stop still absorbs noise at least as well
   as fixed (pinned). The fix for noise remains upstream in what earns weight (SPEC-240).

Executed probe record (head bbb23f583, 2026-10-08):
`uv run pytest packages/maistro-rsi/tests/test_m8c3_context_budgeting_research.py -q`
-> 41 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module; the
full `packages/maistro-rsi/tests` suite passes (1236) and
`scripts/check-suite-inventory.py --suite packages/maistro-rsi/tests` matches the recorded
inventory. Mutation checks — each pinned finding fails when its cause is removed (11
mutations, exact flipped pins measured at this head):

- deleting the always-include band from `_pack` flips the band-overspend identity pin (the
  benchmark-level pins are gate-masked by design: with no band the blocks still trip);
- freezing the complexity multiplier flips the complexity-budget monotonicity pin;
- disabling omission flips the omission drops-only pin (its positive direction — a trailing
  flagged duplicate behind a kept original must actually be dropped);
- removing the summary allowance flips **nothing** — recorded as the pin set's one honest
  blind spot: the tier never delivers under the gate, so its allowance is
  measurement-invisible; the never-survives pin holds trivially without it;
- stripping the qualifier-safe summarizer's marker sentences flips the marker-retention pin;
- injecting one fabricated summary sentence flips exactly the fabrication pin;
- turning skip-not-break into break flips three pins (omission drops-only, the
  omission-equality finding, and density's recovery);
- disabling the density stop flips density's pinned 27.83-token spend (29.4 without it);
- padding zero-score memories back into the rank flips seven pins (rank identity, density,
  margin, sub-gate complexity, composition, the window tie, and the naive-distortion
  contrast);
- reverting the seed to an ID list (dropping the band derivation and the double-serve)
  flips four pins including the corpus-shape seed assertion and the window tie — the seed's
  production fidelity is itself mutation-guarded;
- removing the margin cliff flips the margin frontier pin (0.400/64.1 -> 0.200/33.5).

## Benchmark procedure (what a real experiment must do)

1. Export real assembly traces: for a fixed query set, capture the ranked candidates, the
   packed selection, the wrapped block, and the final prompt at the shipped 4096 budget,
   plus judge labels for which memories were load-bearing (the evidence that actually served
   the answer, per ADR-017 traces). Labels are the experiment.
2. Sweep the fixed budget across model context sizes (4k / 8k / 32k / 128k windows) to map
   the real quality-cost frontier of the constant — and of the **gate**: at production's
   4096-token budget the whole-block check rarely fires, so the interesting swept axis is
   how much budget must be reserved (or how early the gate fires) before it starts dropping
   whole blocks in real Workspaces; then run the adaptive policies against the
   matched-mean-spend points on that frontier, with a real LLM summarizer (logging its own
   outputs) in the hierarchical tier and a real judge scoring answer quality and summary
   distortion, not just probe presence.
3. Measure the issue's full list per policy: task quality, evidence recall, token cost,
   wall-clock latency p50/p95, lost-critical-fact rate, summary distortion against judge
   labels, and stability (variance of quality) across context sizes.
4. Report the dominance frontier and the failure classes the winner still ships; update
   this disposition with the numbers; route any adoption to the SPEC-244/ADR-091 owner —
   the budget knob, the band, the gate, and Layer 2 are that spec's surface, and a budget
   policy that reads anything beyond `budget_tokens` changes the `ContextAssemblyPolicy`
   protocol, so it needs that spec amended, not a parallel implementation.

## Trust boundary

The harness is test-only code that imports no maistro module (AST-pinned by its own contract
test): it cannot become a second assembly authority, budget authority, or compression
authority (epic contract). No product code, flag, model call, or cache is added; the
canonical assembly path, its bands, its pool floor, and its fixed budget are untouched. Any
adoption — complexity-scaled budgets, a density/margin stop, omission, a Layer 2 summarizer,
or a change to the whole-block delivery gate — routes to the SPEC-244 owner and must pass
the normal architecture and evidence gates; a summarizer that rewrites rather than extracts
additionally changes the distortion surface measured here.

## Disposition

**WATCH.** The mechanisms are real and now measured on a pinned corpus against the shipped
gate, but the evidence base is synthetic, and the gate re-shaped every answer the hypothesis
asks for: at this corpus scale the whole-block delivery check — not budget arithmetic —
decides what any policy can deliver, the two policies that beat the fixed sweep (density
cap, margin stop) win **by fitting the gate**, and the hierarchical tier cannot deliver a
summary at any swept window. Negative findings are first-class: complexity scaling is inert
below gate fit; omission is indistinguishable there; composition is a total loss; the
summary tier's allowance is currently measurement-invisible.

Escalate to **INCUBATE** when a real-trace experiment (procedure above) shows on the
canonical seam, at production-scale budgets where blocks genuinely fit, that (a) a budget
policy holds answer quality at a measured token saving across at least two window sizes,
and (b) a qualifier-safe extractive Layer 2 holds judge-scored distortion at or below a
pinned bound while cutting prompt tokens — with the distortion check from finding 7 as part
of the evidence. Escalate to **REJECT** if the real experiment shows the wins were corpus
artifacts or the summary tier cannot beat the distortion bound. Two findings are worth
carrying into the SPEC-244 discussion regardless of disposition: the whole-block gate turns
assembly overspend into total memory loss (finding 1 — a delivery semantics question, not a
budget one), and layer 3's band force-feed double-serves wisdom rows the pack already chose
(finding 6's cause — a redundancy the shipped path ships today).
