---
id: SPEC-184
title: "Modular capability platform — slots, providers, runtime toggles, and the conductor capability port"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-29
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#SPEC-014
  - maistro-engine#SPEC-009
  - maistro-engine#SPEC-011
  - maistro-engine#SPEC-176
  - maistro-engine#SPEC-180
  - maistro-engine#SPEC-015
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
---

# SPEC-184: Modular Capability Platform

## Context

A production "Conductor" AI stack (`/root/docker/conductor-router` + the `conductor-host-health`
systemd service + `browser-agent` + LiteLLM) currently drives the operator's dev server: LLM
routing, smart-home control, infrastructure monitoring, family chores, learning, and more.
maistro-engine is the intended replacement, but its capabilities are wired ad-hoc:

- Tools use a `ToolRegistry` protocol (`packages/maistro-core/src/maistro/protocols/tools.py:26-44`)
  but are registered statically; the conductor agent does not inject them dynamically.
- Integrations are standalone classes with **no shared protocol or registry**
  (`packages/maistro-core/src/maistro/integrations/__init__.py` — static imports).
- The router's filter/score/scarcity/speed stages are pure functions, **not pluggable**.
- There is **no `importlib.metadata` entry-point discovery** anywhere; the closest pattern is the
  graph node registry's decorator + hardcoded importlib sweep
  (`packages/maistro-core/src/maistro/graph/nodes/__init__.py:127-155`).
- Settings persist globally in-memory with optional SQLite backing
  (`packages/hive-conductor/backend/stores.py:90,135-142`; `routes/settings.py:48-53`).

The operator's requirement is explicit: **every capability must be an optional module that can be
imported, added after install, and toggled on/off at runtime**, with a **fallback baseline** when a
capability is absent. Install-time selection is a *starting snapshot*, not a cage.

This spec defines the unifying abstraction — **capability slots filled by swappable providers** —
that all conductor capabilities port onto. It deliberately reuses the registry, trust-tier, and
settings patterns maistro-engine already has rather than inventing parallel machinery.

## Goals

1. One abstraction (**slot + provider**) that subsumes tools, integrations, MCP bridges, and LLM
   providers, so any capability is an installable, toggleable, swappable unit.
2. **Late-add without restart**: install a provider after first-run and activate it live.
3. **Honest degradation**: when a capability is off or absent, behavior is a declared baseline or a
   typed "unavailable" — never a crash, never a silent wrong answer.
4. **Tiered autonomy** for host actions ("auto for safe, approve risky") expressed as composition of
   an `infra_action` slot consulting an `approval` slot — not bespoke code.
5. A clear **port map** from the running conductor's capabilities to slots/providers.

## Non-goals

- Re-implementing the curl|sh installer from scratch — Section "Onboarding" extends **SPEC-180**'s
  existing plan engine with its deferred remote-fetch + preflight layer.
- Re-specifying the free-tier default bundle, OAuth onboarding, sovereignty mode, or privacy
  disclosure — those are **SPEC-014**; this spec only *refines* the provider catalog with a
  `billing_model` taxonomy and a usage-aware weighting optimizer.
- Secrets storage mechanism — provider credentials use the **SPEC-011 vault**; never disk, never
  plaintext in config.
- A microkernel rewrite. The router/classifier/agent core stays; capabilities plug into it.

## Decision

### 1. Slots and providers (`maistro-core/capabilities/`)

- **`CapabilitySlot`** — a named seam with a typed `Protocol`, a `trust_tier`, and a declared
  `fallback_policy` (below). The slot defines *what*, never *how*. Initial slots:
  `llm_gateway`, `web_search`, `smart_home`, `notify`, `infra_monitor`, `infra_action`,
  `approval`, `self_repair`, `learning_store`, `browser`.
- **`CapabilityProvider`** — a concrete implementation of a slot's Protocol. Mirrors the existing
  `ToolExecutor` shape: `name`, `slot`, `trust_tier`, `requires` (env vars + reachable services),
  `async healthcheck() -> Health`, plus the slot-specific methods. Multiple providers may exist per
  slot; **at most one is active**.
- **`CapabilityRegistry`** — modeled on `InMemorySkillRegistry`
  (`packages/maistro-core/src/maistro/skills/registry.py:19-85`): thread-safe, trust-tier aware,
  in-memory with the same optional SQLite backing the settings store already uses. Tracks per slot:
  installed providers, the active provider, and the enabled flag.

**Consumers depend only on the slot Protocol.** Swapping `ha_rest` for `alexa_plus`, or adding
`crypto_did` approval later, requires zero change to callers.

### 2. Discovery and late-add

Three install vectors, one registry:

- **Python providers via entry points (new seam).** Provider packages declare
  `[project.entry-points."maistro.capabilities"]` in their `pyproject.toml`. The registry runs an
  `importlib.metadata.entry_points(group="maistro.capabilities")` sweep at startup and on demand.
  This generalizes the node-registry pattern from a hardcoded module list to metadata-driven
  discovery.
- **Declarative providers via the skills path.** HTTP-endpoint-backed providers (host-health API,
  browser-agent, CoinSwarm, SearXNG) need no Python package — a `SKILL.md`-style manifest through
  `FilesystemSkillLoader` (`packages/maistro-core/src/maistro/skills/loader.py:23-66`) +
  `merge_into_tools()` registers them, reusing the existing trust-tier + enable/disable machinery.
- **Live reconcile.** `POST /v1/capabilities/discover` re-runs both sweeps and reconciles the
  registry without restart (modeled on the MCP `/discover` route).

**Discovery only ever registers a provider as `installed, inactive`.** Activation is a separate
runtime decision (Section 3). Re-running the bootstrap wizard or `maistro capability add <name>`
performs the install; the answers file gains **merge/delta semantics** (it is install-once today,
`packages/maistro-bootstrap/src/maistro_bootstrap/resolver.py`) so adding a provider later does not
clobber the existing selection.

### 3. Runtime toggles, settings, and baseline policy

- **State split.** The registry holds *what is installed*; the settings store holds *what is
  active*. Extend `SettingsModel` with:
  `capabilities: dict[slot, {enabled: bool, active_provider: str | None, provider_settings: dict}]`.
  Toggling rides the existing `PATCH /v1/settings` `model_copy(update=...)` path plus a thin
  `PATCH /v1/capabilities/{slot}` convenience route. Effective on next call; no restart.
- **Resolution order** on every slot call:
  1. slot `enabled` is false → fallback policy;
  2. else `active_provider` (or first healthy provider by trust tier);
  3. `healthcheck()` (cached, short TTL) — unhealthy falls through to fallback and emits a
     degraded-mode event;
  4. fallback policy runs.
- **Fallback policy — declared per slot. A slot may declare `baseline_provider` only if a
  dependency-free implementation can live inside core.**
  - `baseline_provider` — built-in, needs nothing external. Example: the `approval` slot's baseline
    is a **built-in approval inbox** (pending-actions queue in the Hive Conductor UI + `maistro
    approvals` CLI + API). `ha_push`, `alexa`, email/SMS, and `crypto_did_signature` are *enhanced*
    providers for the same slot. For headless no-UI installs the slot may be configured to fall
    further to `deny-by-default` — a boot-time choice, not a surprise.
  - `safe_noop` — no dependency-free implementation exists; returns a typed "capability unavailable"
    the caller branches on. Applies to `web_search`, `smart_home`, `notify`, `infra_*`, `browser`.
  - `hard_required` — system refuses to start without an active provider. Applies to `llm_gateway`.

**Tiered autonomy is composition, not bespoke code.** The `infra_action` slot tags each action with
a blast-radius tier (`reversible` vs `destructive`/host-level). Before a `destructive`-tier action
it calls the `approval` slot — whatever provider fills it. "Auto for safe, approve risky" is
`infra_action` consulting `approval`; the operator chooses *how* approval happens by choosing the
provider (built-in inbox baseline, HA push, or wallet signature if installed).

### 4. Onboarding (delta on SPEC-180)

SPEC-180 already produces a structured install plan (`build_install_plan`), shares it across CLI and
Hive API, and lists `curl | bash` remote fetch and automatic OS-package install as **out of scope**.
This spec specifies that deferred layer, optimizing **time-from-discovery-to-running**:

- **Downloader** — a small, auditable POSIX script (`get.maistro.*`) whose only job is detect
  OS/arch, verify prerequisites, fetch the pinned installer payload, and hand off to SPEC-180's
  engine. The inspect-first path (`curl -o install.sh && less && sh`) is documented.
- **Preflight / dependency apps** — detect-and-reuse container runtime (Docker *or* Podman; SPEC-180
  already emits both) and `uv`/pinned Python; install only the minimum if absent. Everything else
  runs in containers.
- **Fast path (default, KPI-optimal)** — non-interactive profile: core + `llm_gateway`
  (hard_required) + Hive Conductor UI, nothing infra-specific. One unavoidable input: a single LLM
  provider key (or detected local Ollama). Brings the stack up, polls `/health/ready`, prints UI URL
  + initial admin credential. **The KPI clock stops here.**
- **Guided path (`--interactive`)** — the existing Questionary wizard selects the initial provider
  set and collects optional config.
- **Idempotent re-run** — a second invocation detects an existing install and becomes the
  add-capability / upgrade path (Section 2), never a clobber.

Onboarding seeds the *minimal viable instance*; all growth uses the Section-2 late-add loop.

### 5. Provider catalog and weighting optimizer (delta on SPEC-014)

SPEC-014 owns the free-tier default bundle, OAuth onboarding, sovereignty mode, and privacy
disclosure. This spec adds the missing **billing-model dimension** and a usage-aware optimizer.

- **`billing_model` field** on each catalog entry:
  `free_tier | subscription | subscription_capped | metered`.
- **Default free bundle (free-tier, role-based)** — confirmed against the operator's cost model:

  | Provider | billing_model | role |
  |---|---|---|
  | cerebras | free_tier | central routing speed (fast first-hop default) |
  | mistral | free_tier | bulk free tokens (~1B/mo) |
  | google | free_tier | fast free vision |
  | openrouter | free_tier | the small amount of free Opus / frontier reach |
  | sambanova | free_tier | fast large-open reasoning — DeepSeek R1, Llama 405B (100+ tok/s) |
  | zhipu | subscription (flat, GLM coding) | code — opt-in personal sub |
  | perplexity | subscription_capped → metered | search — $5/mo included credits, then real spend |

  Subscriptions are **per-install personal modules** (the operator's own accounts), never universal
  defaults.

- **Optimizer logic forks on `billing_model`** — this is the core insight:
  - `free_tier` → **conserve**: stay under cap; shift weight off providers nearing their limit.
  - `subscription` (flat) → **exploit**: marginal cost ≈ $0 within rate limits, so *prefer* routing
    matching task types here (code→zhipu) up to rate limits.
  - `subscription_capped` (perplexity) → exploit the included allotment, then **flip to metered:
    conserve + alert** once exhausted, so the operator never silently burns past included credits.
  - `metered` → **minimize spend**.
  - Output feeds the existing `quality^(qw·p)/cost^cw` formula + scarcity adapter
    (`packages/maistro-core/src/maistro/router/`). Recommender by default; `--apply` mode mirrors
    the conductor's `discover_provider.py --apply` and respects the "approve risky" stance.
- **Telemetry source** — live quota usage (the conductor's analogue is `quota.db`) + task-mix from
  the observability backend.

### Conductor → slot/provider port map

| Conductor capability | Slot | Baseline / providers |
|---|---|---|
| LiteLLM routing | `llm_gateway` | hard_required; LiteLLM provider |
| `web_search` (SearXNG) | `web_search` | safe_noop; SearXNG, vision-browser providers |
| `ha_control` / device enum | `smart_home` | safe_noop; HA-REST + Alexa+ are both providers (no core baseline — HA is external) |
| `ha_notify` | `notify` | safe_noop; HA-notify, (email/SMS later) |
| Host Health API metrics | `infra_monitor` | safe_noop; host-health-API provider (:8150) |
| `infra_action` | `infra_action` | safe_noop; host-health-API provider; tiered, calls `approval` |
| HITL approval | `approval` | built-in inbox baseline; ha_push, crypto_did enhanced |
| RCA / remediation | `self_repair` | safe_noop; detect→diagnose→propose; acts via `infra_action` |
| learnings + auto-promotion | `learning_store` | baseline in-memory; persistent + skill-mutation provider |
| browser-agent / Alexa / IMAP | `browser` | safe_noop; browser-agent provider (:8200) |
| family chores | (tool, not a slot) | ported as a tool on the existing ToolRegistry |

The peripheral services (host-health API, browser-agent, SearXNG, CoinSwarm, HA, LiteLLM) are reused
as-is; providers are thin clients pointing at them.

## Decomposition (follow-on specs this enables)

This spec is the **framework**. Each capability port is a small downstream spec that plugs in:

1. **SPEC-184** (this) — slot/provider framework, registry, discovery, runtime toggles, baseline
   policy. *Foundational; everything below depends on it.*
2. Entry-point discovery + answers-file merge/delta (extends SPEC-180 resolver).
3. `infra_monitor` + `infra_action` + `approval` slots + host-health-API provider (tiered autonomy).
4. `self_repair` slot (detect→diagnose→propose→act-via-infra_action) — the net-new headline loop.
5. `smart_home`/`notify`/`browser` providers (HA, Alexa+, browser-agent).
6. `learning_store` persistent provider + skill mutation.
7. Onboarding curl|sh + preflight (extends SPEC-180 out-of-scope items).
8. Provider `billing_model` catalog + weighting optimizer (extends SPEC-014).
9. **Curated approved-source index + answer cache** — a clean-room hybrid index (pgvector
   semantic + keyword FTS) over an allowlist of trusted domains, fetched on demand via Jina Reader
   (`r.jina.ai`, keyless) and chunked/embedded through `protocols/embeddings.py`. Doubles as the
   write-through cache for live search results. Reuses ADR-016 episodic store + ADR-034 memory
   ownership; no AGPL (own code), no scraping (approved sources only). Becomes the primary
   `web_search` provider. Full design in [SPEC-186](SPEC-186-knowledge-aggregator-cache.md).
10. **Federated canonical-source connectors** — see refinement below; full registry in
    [SPEC-185](SPEC-185-canonical-source-registry.md).

### Refinement: federated canonical sources, not general web search

The `web_search` slot is **not** a general-web search engine and does not try to be one (rebuilding
Google's crawl + index + behavioral-ranking flywheel is infeasible and unnecessary). Instead it is a
**federated set of typed domain connectors**, each pointing at the *canonical authoritative source*
for its data type, with the existing intent classifier routing a query to the right connector(s).
This is higher quality than open-web search (no SEO spam, curated trust) and tractable per-source for
license/ToS review.

Connector tiers by data type (each a provider; `billing_model` + license tagged):

| Data type | Canonical source(s) | Access | Notes |
|---|---|---|---|
| Encyclopedia / facts | Wikipedia, Wikidata, Wiktionary | MediaWiki API, **keyless** | CC-BY-SA |
| News | GDELT DOC 2.0 (**keyless**) + curated publisher RSS + Wikinews | keyless | discovery + link-out; no full-text storage (copyright) |
| Social sphere | **Open web (default):** Nostr (relays/NIP-50), Bluesky (`public.api.bsky.app`; search needs free app-password), Mastodon (public timelines keyless), Lemmy, Hacker News | keyless/free-auth | **Opt-in:** Reddit (free OAuth, non-commercial). **Excluded by the platforms:** X (pay-per-read $0.005, metered opt-in only), Facebook/Instagram (no public search; Meta Content Library = vetted researchers only) |
| Video | YouTube Data API v3 (free key, quota) | key, opt-in | Invidious public instances as keyless-but-gray fallback |
| Academic | arXiv, PubMed/E-utilities, Crossref, Semantic Scholar | **keyless** | open metadata |
| Code / dev | Stack Exchange, GitHub (60/hr unauth), HN | keyless (rate-limited) | CC-BY-SA (SE) |
| Weather | Open-Meteo, NWS `api.weather.gov` | **keyless** | public domain (NWS) |
| Finance / gov / law | SEC EDGAR, FRED, Federal Register, data.gov | **keyless** gov APIs | public domain |
| Geo / places | OSM Nominatim, GeoNames | keyless (usage policy) | ODbL |
| General open web (gap) | Tavily / Exa | keyed, **opt-in** | only when a query needs broad web beyond the connectors |

Connector #10's spec defines the connector Protocol (query → normalized `{title, url, snippet,
source, published_at, license}`), the classifier→connector routing table, and the per-connector
freshness/rate/license metadata. The curated index (#9) caches connector results and sits in front
of all of them.

## Acceptance criteria

- [ ] A `CapabilitySlot` Protocol and `CapabilityProvider` Protocol exist in
      `packages/maistro-core/src/maistro/capabilities/`, with `mypy --strict` clean.
- [ ] `CapabilityRegistry` registers providers as `installed, inactive`; activation is a separate
      settings-driven step; both states survive a restart via the existing SQLite backing.
- [ ] Entry-point discovery loads at least one provider declared via
      `[project.entry-points."maistro.capabilities"]` in a separate package, **and** one declared via
      a `SKILL.md` manifest.
- [ ] `POST /v1/capabilities/discover` registers a newly-installed provider **without a restart**;
      `PATCH /v1/capabilities/{slot}` toggles enabled/active and takes effect on the next slot call.
- [ ] Each slot declares exactly one `fallback_policy`; a disabled or unhealthy provider degrades to
      that policy. `safe_noop` returns a typed unavailable result (asserted, not an exception);
      `hard_required` (`llm_gateway`) fails fast at boot when unfilled.
- [ ] The `approval` slot's built-in inbox baseline works with **no external service** (UI queue +
      `maistro approvals` CLI + API), and an `infra_action` `destructive`-tier call is blocked until
      approval resolves.
- [ ] Re-running the bootstrap wizard with a second provider **adds** it without removing the first
      (merge/delta), verified by a `packages/maistro-bootstrap/tests` case.
- [ ] The optimizer classifies each provider by `billing_model` and emits a weighting recommendation;
      a `subscription_capped` provider past its included allotment is recommended for conserve+alert,
      not exploit (unit-tested with a synthetic usage fixture).
- [ ] Consumers reference only slot Protocols — a test swaps a slot's active provider and asserts the
      consumer is unchanged.
- [ ] Provider credentials are read from the SPEC-011 vault; a test asserts no credential is written
      to `maistro.yaml` or any on-disk config in cleartext.

## Testing

- Unit: registry state machine (install/activate/disable/healthcheck-fallthrough); each
  `fallback_policy`; optimizer billing-model branches with usage fixtures.
- Contract: slot Protocols (boundary contract) — providers conform; consumers depend only on the
  Protocol (behavioral contract).
- Integration: discover → activate → call → toggle-off → baseline, against a fake provider; no
  restart between steps.
- Property (formal/, per repo convention): "a disabled or absent capability never raises into a
  consumer" (invariant); "discovery never auto-activates."

## Open questions

- Per-user vs global capability state — settings are global today; multi-tenant scoping is deferred
  to the Stronghold layer unless a single-install per-user need surfaces.
- Whether `family_chores` and other HA-REST tools stay tools or graduate to a slot once a second
  provider appears.
- Optimizer cadence: on-demand vs scheduled (and whether `--apply` is ever allowed unattended given
  the "approve risky" stance — default: never).

## References

- [ADR-031: front-matter and registry](../adr/ADR-031-front-matter-and-registry.md)
- [SPEC-014: LiteLLM free-tier auto-configuration](SPEC-014-litellm-freetier.md)
- [SPEC-009: setup wizard](SPEC-009-setup-wizard.md)
- [SPEC-011: vault](SPEC-011-vault.md)
- [SPEC-176: Hive Conductor package](SPEC-176-hive-conductor-package.md)
- [SPEC-180: maistro-install bootstrap contract](SPEC-180-maistro-install-bootstrap.md)
- [SPEC-015: hyperagent graph runtime](SPEC-015-hyperagent-graph-runtime.md)
- Seams: `protocols/tools.py:26-44`, `skills/registry.py:19-85`, `skills/loader.py:23-66`,
  `graph/nodes/__init__.py:127-155`, `hive-conductor/backend/stores.py:90,135-142`,
  `hive-conductor/backend/routes/settings.py:48-53`, `router/` (filter/scorer/scarcity/speed).
