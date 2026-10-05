# M8-F research plan — inference systems, open-model fleets, caching, batching, and specialization

Epic: #905. Initiative: #879. Leaves: #934 (M8-F1), #935 (M8-F2, already
dispositioned in [935-cross-agent-batching-kv-reuse.md](935-cross-agent-batching-kv-reuse.md)).

## Hypothesis

A heterogeneous inference architecture — local/open-weight models mixed with
hosted and provisioned capacity, plus serving-side techniques (batching,
prefix/KV reuse, semantic caching, speculative decoding, quantization,
parameter specialization, MoE routing, admission control, small-model
routers) — can beat a single-vendor deployment on throughput, cost, tail
latency, and reliability **if and only if** the technique rides the canonical
provider/capability seams instead of opening a second model-serving path.
The null hypothesis the epic guards against: any throughput or cost win whose
mechanism requires coupling canonical execution to one vendor, one engine, or
one accelerator fleet.

## The seam rule (epic contract, operationalized)

The issue's contract sentence — "Experimental inference engines remain behind
canonical provider/capability seams" — is already the shape of the shipped
tree, from both sides:

- **Governed serving path.** Model chat is one governed egress: Binding →
  Invocation → the single approved gateway provider
  (`maistro.capabilities.model_chat`, whose module docstring opens "One
  governed model egress: Binding -> Invocation -> approved Provider (#56)").
  The approved provider is `maistro.capabilities.providers.llm_gateway`, the
  only module allowed to hold the HTTP client for governed model egress; it
  talks to a LiteLLM-compatible gateway (`MODEL_GATEWAY_CREDENTIAL_PROVIDER
  = "litellm"`) and registers models through the gateway admin API. Model
  selection policy lives behind the same boundary: a Binding pin selects
  exactly that model and refuses rather than falls back when it is
  unavailable (fallback cannot widen authorization, ADR-081226-6b46); a
  request-named alias is kept; an unpinned request is selected by
  `CostAwareRouter` (`packages/maistro-core/src/maistro/providers/router.py`)
  over the provider registry. Token usage and cost are read off the gateway
  response and persisted on the canonical Invocation
  (`maistro.quota.usage_report`, `InvocationUsage`).
- **Everything else is recorded debt, not a second authority.**
  `quality/model-egress.json` freezes the set of modules that call a model
  endpoint directly over HTTP (23 entries at this head, enforced by
  `scripts/check-model-egress.py` as a two-way ratchet). Exactly one entry is
  the approved provider; the rest are direct callers awaiting governed
  migration (`maistro.agents.conductor`, `maistro.events.handlers`,
  `maistro_bootstrap.builders.responses_callable`, `maistro_rsi.*`,
  `maistro_evolve.providers.openai_compatible`, the `services.*` legacy
  snapshots). Notably, `maistro.agents.conductor._call_gateway` accepts a
  `governed_egress: ModelChatEgress` — the production server wires it so the
  call crosses canonical Binding → Invocation — and keeps an explicitly
  marked ungoverned raw-HTTP fallback that still records usage evidence on
  the process usage log (#718). Any M8-F experiment must either ride the
  governed seam, or run inside the explicitly-marked research loops
  (RSI/evolve) whose egress is already ledgered — never open a twenty-fourth
  unledgered caller.

## Canonical seams (verified against the shipped tree at head 31d891a56)

| Serving concern | Shipped seam | Governing spec/ADR |
|---|---|---|
| Fleet declaration | YAML provider config → `InMemoryProviderRegistry` (`maistro.providers.config.load_provider_registry`, wired in `maistro.container` at `provider_config_path`); `ModelMetadata` carries provider, cost per 1k input/output, `latency_p50_ms`, tier (`fast`/`balanced`/`powerful`), `reasoning_capable`, `max_tokens`, `fallback_to` chain; embeddings get their own metadata + cheapest-fitting selection | SPEC-070226-cb8d (shipped loader); ADR-079 (model registry/routing/embeddings — **Proposed**, not yet Accepted) |
| Model selection / failover | `CostAwareRouter.select`: budget filter (cost ceiling, latency ceiling, reasoning capability), lowest-latency-first, breadth-first `fallback_to` chains skipping unavailable/cyclic/dangling entries; fail-closed `NoEligibleModelError` when nothing eligible is available | ADR-038 (**Accepted**), ADR-079 (Proposed) |
| Per-call authorization | Binding (workspace/project/capability/credential refs) → Invocation record with usage/cost → credential routing → gateway call (`maistro.capabilities.model_chat.ModelChatEgress`) | #56, ADR-081226-6b46 |
| Task-difficulty → model policy | Compute tiers `QUICK`/`STANDARD`/`THOROUGH`/`ULTRA` with per-tier model, retries, and `parallel_generations` for ensemble voting (`maistro.config.models.TierConfig`); an unset tier inherits `DEFAULT_MODEL`, so local models are opted into, never a hidden fallback | tier system shipped; SPEC-194 (Ultra Think tiered parallel generation) **Proposed** |
| Resilience substrate | `maistro.resilience`: error classifier (rate-limit/billing/auth/timeout/…), backoff, P1 retry budgets + attempt compaction + per-agent policies (ADR-066/SPEC-070226-af02), SLO error budgets with burn-rate throttle signal; `RateLimitCoordinator` records provider rate-limit reset times; `resilience.fallback` declares `ProviderEndpoint`-priority failover | ADR-038 (Accepted). Note: `RateLimitCoordinator` and the `resilience.fallback` failover module have **zero consumers in shipped src** — primitives without a fleet consumer |
| Rate-limit signals | `docs/model-rate-limit-headers.md`: pace from response headers (`llm_provider-`-prefixed upstream headers preferred over router estimates), never from hardcoded rpm/tpm | shipped doc contract; no pacer consumer wired |
| Quota / admission | `maistro.quota` (usage tracker, billing cycles, rate profile, reconciliation) with per-process usage log for ungoverned evidence; task-ingress concurrency ceiling surfaces as HTTP 429 on `POST /tasks` (#1828/#1182) — a Run-admission seam, distinct from model-serving saturation | #718, #1182 |
| Local/open models | Ollama rides the OpenAI-compatible endpoint (`maistro.config.model_resolver` maps `ollama/<model>` to `openai:<model>` + JSON-mode fallback; `OllamaSettings` with base URL); conductor ships an Ollama JSON-schema prompt fallback for weak tool-schema support | shipped |
| Open-weight fleet research loop | `maistro_rsi.free_router`: resolves OpenRouter's random `openrouter/free` pick, registers the concrete `:free` model on the gateway admin API as a stable alias, pins it onto genome nodes — an existing open-model-fleet experiment path (research loop, ledgered egress) | shipped (research substrate) |
| Prefix/KV caching | One opt-in, provider-gated mechanism: `maistro_bootstrap.builders.responses_callable.prompt_cache` marks the stable tools+system prefix with an Anthropic ephemeral cache breakpoint (off by default, no-op off-Anthropic, "needs one live gateway validation before default-on"); RSI/evolve bodies explicitly send `cache: {no-cache: true, no-store: true}` because workspace state changes every turn | shipped, single-caller; everything cross-Agent is absent (leaf #935) |
| Batching | Absent. No request is batched with another anywhere in shipped src; the governed path is one non-streaming call per Invocation | leaf #935 |
| Speculative decoding / quantization / LoRA / MoE | Absent. Zero matches in shipped `packages/*/src` for speculative decoding, quantization, LoRA, or mixture-of-experts; no local inference engine (vLLM/SGLang/llama.cpp) is configured anywhere | open directions |
| Small-model routing/classification | `maistro.classifier`: keyword scoring → complexity estimation → LLM fallback above a threshold; the `QUICK` compute tier names a "fast, cheap" model; no small *local* classifier model is deployed for tool/intent routing | shipped pipeline, LLM fallback not small-model |
| Inbound OpenAI-compat surface | `maistro_server.api.chat_completions` exposes `/v1/chat/completions` translated to canonical runs (MAIstro *as* a provider) — relevant to portability, not an egress seam | shipped |

## Candidate research directions

Status against the shipped tree: **exists**, **partial**, or **absent**. Each
becomes a leaf ending GRADUATE / INCUBATE / REJECT / WATCH. The epic's
metrics: quality regression, throughput, tail latency, memory/accelerator
requirements, operational complexity, provider portability.

- **A. Local + cloud mixed routing — partial.** The registry's `provider`
  field is free-form, the router is provider-blind (it sees only cost/latency/
  capability metadata), and Ollama models work today — but an unset tier
  inherits `DEFAULT_MODEL`, so local capacity is operator-opted-in and nothing
  measures when local-first routing preserves quality. Leaf question: on
  representative workloads, does difficulty-aware local-first routing (local
  for `fast`-tier work, hosted for `powerful`) hold quality within a fixed
  regression budget while cutting cost and hosted-tail latency? Baseline:
  single-model `DEFAULT_MODEL` deployment on the same workloads, measured on
  Invocation cost + duration + `RunEvalScore`.
- **B. Open-weight model fleets — partial.** Fleet declaration, fallback
  chains, and availability probing exist; the RSI free-router already proves
  an open-weight fleet can be pinned and scored on the gateway. What does not
  exist is any fleet comparison for canonical Agent work. Leaf question:
  which open-weight fleet composition (per tier) matches hosted quality on
  agent/tool-heavy workloads, and what is the failover behavior under
  provider outage/capacity pressure (the router's declared `fallback_to`
  chains vs observed gateway behavior)? Baseline: the hosted-only fleet at
  identical budgets. This is leaf #934's experiment; no result exists yet.
- **C. Batching across independent Agent work — absent.** Leaf #935's
  territory; the shipped serving path is one call per Invocation and no
  scheduler batches across Agents. See
  [935-cross-agent-batching-kv-reuse.md](935-cross-agent-batching-kv-reuse.md)
  — disposition **WATCH**: not evidenced on the governed seam, and the
  direct-egress callers recorded in `quality/model-egress.json` must be
  covered or explicitly scoped out by any future work.
- **D. Prefix/KV and semantic caching — partial (single caller).** The
  bootstrap builders' opt-in Anthropic prefix breakpoint is the only shipped
  cache, it is gateway-native (no MAIstro-owned cache layer), and response
  caching is *affirmatively disabled* for RSI/evolve because freshness beats
  cost there. Cross-Agent prefix/KV reuse and any semantic response cache do
  not exist; tenant/context-leakage-safe cache identity is #935's hard
  requirement. Disposition today: **WATCH** (per the #935 note).
- **E. Speculative decoding/inference — absent.** No draft/target model
  pairing, no engine support in the gateway configuration, and the governed
  path's request/response contract carries no draft-acceptance surface. A
  leaf must first answer whether a *gateway-side* deployment (e.g. a
  speculative-capable serving engine behind the same OpenAI-compat seam) can
  deliver acceptance-rate gains without changing the Invocation contract —
  if it can, the seam rule is satisfiable without product code; if not, the
  direction couples to engine internals and likely dead-ends at REJECT.
- **F. Quantization trade-offs for agent/tool use — absent.** Nothing in the
  tree expresses precision, quantization, or engine options; the registry
  metadata (`ModelMetadata`) has no quantization field, so a quantized
  variant can only enter a fleet as a distinct registry entry whose
  operator-declared scalars (cost, latency, token ceiling, capability flags)
  differ from its parent — which is workable: the leaf benchmarks it as a
  fleet entry without code changes. Leaf question: do quantized variants of
  open-weight fleet members hold tool-call validity and quality on canonical
  workloads at their cost/latency points? Baseline: unquantized variants on
  the same registry.
- **G. LoRA / domain-specialized models — absent.** No adapter training,
  storage, or loading surface; nothing binds a specialized variant to a
  capability slot. Any leaf must route specialization through the existing
  Binding pin (a specialized model is a new registry entry pinned to a
  capability), not a parallel model path.
- **H. MoE expert-routing experiments — absent.** No MoE-capable engine is
  deployed or configured; expert routing is inside an engine behind the
  gateway, so the only measurable MAIstro-side questions are fleet-level
  (cost/latency/quality of an MoE model entry vs a dense equivalent) — which
  collapses into #934's benchmark matrix rather than its own architecture.
- **I. Provisioned-throughput saturation and admission — partial.** The
  substrate exists in pieces that were never joined: `RateLimitCoordinator`
  (per-provider reset times, zero consumers), `resilience.fallback`
  (`ProviderEndpoint` priority failover, zero consumers), the header-grounded
  pacing contract (`docs/model-rate-limit-headers.md`, no pacer wired), the
  SLO burn-rate throttle signal (ADR-038 §4), and 429 admission backpressure
  on task ingress (Run concurrency, #1828). What is missing is the
  model-serving-side consumer that reads provider rate-limit headers,
  coordinates across Workspaces, and sheds or queues load *before* 429s.
  Leaf question: does header-grounded cross-Workspace pacing measurably
  reduce 429/timeout rates and tail latency under saturation vs the current
  retry-and-backoff behavior (P1 policies), without becoming a second
  execution authority? Baseline: today's P1 retry/escalate/fail decisions on
  the same traffic. Note the boundary: pacing may *delay* an egress attempt;
  it must never *decide* run/node lifecycle — that stays with the canonical
  execution model.
- **J. Small-model routers/tool classifiers — partial.** Intent
  classification is keyword-first with an LLM fallback above an ambiguity
  threshold (`maistro.classifier`, `LLM_FALLBACK_THRESHOLD = 3.0`); the
  router selects by static metadata, not by a learned difficulty model. A
  small-model router would replace the LLM fallback (and potentially
  `CostAwareRouter`'s static ordering) with a cheap local classifier in front
  of the governed seam. Leaf question: does a small local router match
  keyword+LLM classification quality at lower latency/cost, and does its
  error profile stay inside the same escalation path (ambiguous → LLM →
  human)? Baseline: the shipped keyword+LLM pipeline on recorded traffic.

## Measurement contract

The six epic metrics map onto stores that already persist — a leaf that
cannot name its source for a metric is not reportable:

- **Quality regression** → terminal `RunStatus` + append-only `RunEvalScore`
  against Goal/Rubric revisions; per-leaf rubrics must be fixed *before* the
  benchmark run.
- **Throughput** → completed Invocations per wall-clock unit, read from
  canonical Invocation records (workspace/project/capability rows), never
  from side logs.
- **Tail latency (p50/p95/p99)** → Invocation durations derived from the
  canonical run identity the egress already binds (run_id/node_run_id/
  attempt_id) plus the usage report; the epic's fleet experiments must record
  these per model *entry*, not per gateway aggregate.
- **Memory/accelerator requirements** → no canonical store today; the infra
  capability slot (`maistro.capabilities.slots.infra`: `docker_logs`,
  `ollama_list`, restart actions) is the sanctioned probe surface for
  experiment *operator* evidence — a leaf claiming accelerator numbers must
  record its collection procedure in the leaf.
- **Operational complexity** → no canonical store; instrument as a counted,
  checkable artifact (config deltas, new running processes, new failure
  modes in the resilience classifier's categories) in the leaf itself.
- **Provider portability** → the registry's `provider` field plus
  `quality/model-egress.json` row count: a technique that forces a new
  direct caller fails the seam rule outright (`scripts/check-model-egress.py`
  ratchets both ways).

## Executed probe record

Head 31d891a561, 2026-10-05. Procedure: in-process probe against
`maistro.providers.registry` + `maistro.providers.router` (no network; the
registry's availability set is the outage injection point), plus a YAML
fleet-declaration load via `load_provider_registry`, plus a
`quality/model-egress.json` shape check. Executed results:

- default selection returns the lowest-latency available candidate
  (`qwen2.5:7b`, p50 350 ms) — P1;
- marking the local model unavailable reroutes the same unpinned request to
  the hosted fallback (`gpt-4o-mini`) — P2; `fallback_chain` returns the
  full breadth-first chain `[qwen2.5:7b, gpt-4o-mini, claude-sonnet]` — P3;
- `RouterBudget(reasoning=True)` restricts selection to the one
  reasoning-capable entry (`claude-sonnet`) — P4;
- a $0-cost local entry legitimately satisfies a 0.001¢/1k cost ceiling
  (budget filtering is a ceiling, not a ranking) — P5;
- with every fleet entry unavailable the router refuses with
  `NoEligibleModelError` rather than routing to air — P6;
- embedding selection returns the cheapest entry whose `max_input_tokens`
  fits the request — P7;
- a mixed local+hosted YAML fleet (2 models + 1 embedding) loads through
  `load_provider_registry` — P8;
- `quality/model-egress.json` lists 23 frozen modules with the approved
  `maistro.capabilities.providers.llm_gateway` present — P9.

Absence scan (same head): zero matches for speculative decoding,
quantization, LoRA, mixture-of-experts, SGLang, or llama.cpp across shipped
`packages/*/src`; the single vLLM mention is a comment
(`maistro_bootstrap/builders/responses_callable.py:325`) naming engines that
gateway-native auto-cache a stable prefix — no engine is configured
anywhere. The only caching seams are the bootstrap Anthropic prefix
breakpoint and the RSI no-cache bodies.

## Record

This note reports no experiment. No fleet composition, batching scheme,
cache, or specialization has been measured against a canonical MAIstro seam
under the epic's six metrics. What exists — the governed Binding →
Invocation → gateway path, the `CostAwareRouter` fleet policy over the YAML
registry, compute tiers, the resilience substrate, the rate-limit header
contract, the RSI open-weight research loop, and the single-caller prefix
breakpoint — is prior substrate that defines the baselines. Leaf #935 is
dispositioned **WATCH** in its own note; leaf #934 has no experiment and
therefore no disposition beyond this epic-level WATCH. Gaps worth naming for
whoever picks leaves up: ADR-079 (registry/routing/embeddings) is still
**Proposed** while `CostAwareRouter` ships as its implementation — a
fleet-benchmark leaf that produces adoption pressure should either accept
ADR-079 first or record why the Proposed status does not block it; and the
resilience substrate's fleet primitives (`RateLimitCoordinator`,
`resilience.fallback`) are shipped with zero consumers, so direction I is
*joining* primitives, not building new authorities. This change adds no
product code, no flag, no cache, no engine, and no second model-serving
path.

## Disposition

WATCH at epic level. Directions A–J (with C/D owned by leaf #935, B owned by
leaf #934) become leaves ending individually in GRADUATE / INCUBATE /
REJECT / WATCH. Any GRADUATE result routes production adoption to
model/provider/infrastructure owners per the epic's exit contract; it can
never authorize a second governed model path, because the seam rule is both
the thing being tested and the boundary the result must respect. The epic is
done when every leaf carries a documented disposition.
