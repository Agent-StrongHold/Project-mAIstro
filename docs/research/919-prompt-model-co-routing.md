# M8-B5 research note — prompt-model co-routing and per-Agent/per-capability specialization

Leaf: #919. Epic: #900. Initiative: #879. Cross-referenced: #904 (M8-E — its leakage
rule governs the calibration fit this leaf defines).

## Hypothesis

The best model may depend on the prompt/role/tool contract as much as the task label;
jointly selecting (model, prompt template) — co-routing — and specializing pairs per
Agent/capability role may beat model-only routing.

## Canonical seams

The two axes the hypothesis joins are shipped as two separate, orthogonal seams:

- **Model axis — `CostAwareRouter`**
  (`packages/maistro-core/src/maistro/providers/router.py`): filters by budget,
  prefers the lowest-latency candidate, and walks ADR-038 fallback chains. Its
  `RoutingTask` carries only `task_type`/`description` — model choice today is
  task-conditioned at best and never sees the prompt. Cost/latency units are
  `ModelMetadata`'s (cents per 1k input/output tokens, p50 milliseconds,
  `packages/maistro-core/src/maistro/providers/types.py`).
- **Prompt axis — the prompt library**
  (`packages/maistro-core/src/maistro/prompts/store.py`): `InMemoryPromptManager`
  resolves a template name + label to content. The lookup is model-blind; the router
  is prompt-blind. Co-routing studies exactly this orthogonality.

Per-capability specialization partially exists today as the hand-pinned
`Binding.provider_name` (`packages/maistro-core/src/maistro/capabilities/binding.py`):
an operator-chosen static pin that outranks the router. Governed inference runs
Binding → Invocation → the single approved gateway provider
(`packages/maistro-core/src/maistro/capabilities/model_chat.py`,
`packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`). Co-routing
would be a *policy for deriving* such pins — plus the template label — from evidence.
Per the epic exit, production adoption belongs to the routing/prompt owners, not M8.

Outcome ground truth for any real run comes from the outcome store (ADR-017), which
records the served model per outcome; a paired (item × pair) corpus — the same item
answered under several (model, template) pairs — requires a deliberate multi-pair
export and cannot be reconstructed from production traffic alone. Direct egress
callers frozen in `quality/model-egress.json` remain outside the governed seam; any
co-routing experiment must either cover those paths or scope itself to the governed
seam and record the rest as migration debt (the same caveat the #935 note records).

## #904 signal availability at this head

At this head (31d891a561) no #904 harness exists in-tree. The co-routing fit therefore
carries the leakage rule by construction: the mapping is fitted on a strictly
prior-period calibration slice only, and the evaluation slice is a disjoint parameter
of the comparison, never an input to the fit. A role with no calibration rows gets no
inferred choice — it falls back to the baseline pair and the fallback is recorded in
the measurement, loudly. When the #904 harness lands, its estimators can replace the
raw frequency argmax without touching the accounting.

## Record

This note does not report a provider experiment. The deterministic CI environment holds
no provider credentials and no real paired (item × model × template) outcome corpus
exists in-tree; manufacturing one was out of scope, and absent evidence is recorded
rather than simulated (M8 guardrail 3). This change adds no product code, no flag, and
touches no authority path.

What it adds is the reproducible measurement machinery the benchmark demands, as a
separated research artifact:
`packages/maistro-rsi/tests/test_m8b5_corouting_benchmark_research.py` (test suite
only; it imports no maistro module, so it cannot become an authority by accident — M8
guardrails 1-2). Validated on deterministic hand-checked fixtures (30 checks), it
implements:

- pair-level cost/latency accounting in `ModelMetadata` units with stated rules: a
  template's added input tokens are priced on every call, and its prefill latency is
  charged as `added_tokens / 1000 × p50 × 0.5` (a stated, deterministic stand-in for
  measured prefill timings);
- the **fixed (model, template) baseline pair as the only judge**: quality is read
  from the row of the pair actually served on each item, never relabeled from another
  pair's rows; a corpus cell an arm needs but the corpus lacks is a loud error;
- the full arm set: fixed baseline, model-only (today's shape), prompt-only,
  hand-picked per-role pairs, and the bounded co-routing fit with a catalog bound
  (default 4 pairs) and deterministic lexicographic tie-break;
- structured-output/tool-call validity as a first-class measure alongside success,
  cost, and mean/p95 latency;
- **prompt maintenance burden** (distinct templates kept correct + active version
  surface that must survive review and label promotion);
- **overfitting across benchmark families**: a generalization gap between the fit
  family and a disjoint held-out family scored under the same mapping;
- **portability across model versions**: regret of the stale mapping vs a refit on a
  post-bump grid;
- curation evidence: catalog pairs never optimal for any role on the calibration
  slice (advisory only — the baseline pair is retained by policy regardless).

What the fixtures demonstrate (synthetic arithmetic, **not** evidence about real
models). The fixture grid encodes the interaction the hypothesis is about — a cheap
model that follows scaffolds (nimbus-fast), one that chokes on long scaffolds
(helios-fast, the provider-specific prompt sensitivity the issue asks to include), a
strong expensive floor (titan-strong), and a drifted family:

- The fixed baseline (titan-strong+plain) is perfect but bills 109.056¢ per 24-item
  grid at 2544 ms mean.
- **Model-only routing ships structure failures**: one template everywhere plus
  per-role cheap models costs 6.032¢ but drops structured validity to 1/3 and success
  to 1/6 — it misroutes the half of the interaction it cannot see.
- **Prompt-only specialization pays the overhead trap**: scaffolding every role on the
  strong model holds validity at 1.0 but costs 131.52¢ — *more than the baseline* —
  at 3480 ms mean, while tripling the active version surface (3 versions maintained).
- **The bounded co-routing fit routes the interaction**: summarizer → helios-fast+plain
  (prose, no scaffold), extractor and tool_agent → nimbus-fast+role_rich (scaffold
  recovers structure). Validity 1.0, success 20/24 (the only shipped failures are the
  drifted family's helios prose items), at 7.5776¢ — **14.4× cheaper than the fixed
  baseline** and **5.2× cheaper than the hand-picked static role pairs** (39.51¢), mean
  latency 1358.7 ms, two templates / four active versions maintained.
- **Overfitting is visible, not hidden**: the fitted mapping carries a generalization
  gap of 0.333; on the drifted held-out family its success falls to 8/12 while the
  fixed baseline holds 1.0 — the stale cheap pick ships failures exactly where the
  fit never looked.
- **Portability has a price**: after a model-version bump that removes the scaffold
  benefit, the stale mapping's regret vs a refit is 0.282 utility, and the refit moves
  the structure-bearing roles back to the strong pair — specialization must be
  re-derived when the model substrate changes.
- Curation arithmetic: on the calibration slice, nimbus-fast+plain and the baseline
  titan-strong+plain are never optimal for any role — the baseline is retained by
  policy anyway (a calibration slice cannot see tail risk).

Executed probe record (head 31d891a561, 2026-10-05):
`uv run pytest packages/maistro-rsi/tests/test_m8b5_corouting_benchmark_research.py -q`
→ 30 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module;
the frozen run record is byte-identical across invocations (asserted by a test).

## Benchmark procedure (what a real experiment must do)

1. Export a paired grid corpus from the outcome seam: representative MAIstro
   Agent/capability workload items across benchmark families, each answered under
   every (model, template) pair in a bounded catalog, with observed outcomes,
   structured/tool-call validity, token counts, and latencies. Populate pair profiles
   from the provider registry (`ModelMetadata`) and template profiles from the prompt
   library (added tokens, active versions).
2. Measure the fixed baseline pair over the identical item set.
3. Fit the bounded co-routing mapping on a strictly prior-period calibration slice
   only (#904 leakage rule); record every no-fit fallback.
4. Evaluate all arms on the disjoint evaluation slice; report success, structured
   validity, cost, mean/p95 latency, maintenance burden, and per-role fallbacks.
5. Report the family generalization gap, the model-version-bump regret against a
   refit, and the dead-catalog curation evidence; include provider-specific prompt
   sensitivity explicitly (at least one model whose scaffold tolerance differs).
6. Update the disposition here. Quality must always be read from the served pair's
   own rows; no arm may borrow another arm's outcomes.

## Trust boundary

Co-routing research and routing/prompt authority stay separate — this leaf's own
contract sentence and the epic's. Every number the harness produces is advisory
evidence: it reads no Goal, writes no Run authority, makes no routing decision, and
touches no Warden/HITL/delegation control (ADR-068). A co-routing policy that survives
a real experiment reaches production only as a change to the canonical seams owned by
the routing owner (`CostAwareRouter` for the model axis, the prompt library for the
template axis) and as derived `Binding` pins — never through this harness, whose
outputs are frozen measurements, not actions.

## Disposition

- #919 (prompt-model co-routing, per-Agent/per-capability specialization): **WATCH** —
  the measurement machinery is reproducible and its arithmetic is validated, but no
  real paired-grid experiment exists, so the hypothesis is unevidenced on MAIstro
  workloads. Move to **INCUBATE** when a real run on representative workloads shows
  the joint (model, template) choice materially beating both single-axis arms on
  stated utility at bounded maintenance burden, with the generalization gap and the
  version-bump regret reported and acceptable to the routing/prompt owners. **REJECT**
  if real runs show the specialization's maintenance burden or version-bump regret
  consuming the utility advantage, or if the advantage fails to survive a disjoint
  family (pure benchmark overfitting). Provider-specific prompt sensitivity must be
  reported either way.

No adoption is authorized by this note.
