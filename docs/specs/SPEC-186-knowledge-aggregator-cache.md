---
id: SPEC-186
title: "Knowledge aggregator + three-layer cache (answer / result / relational graph) with news monitoring"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-29
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-185
  - maistro-engine#SPEC-005
  - maistro-engine#SPEC-014
  - maistro-engine#ADR-016
  - maistro-engine#ADR-034
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-185
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

# SPEC-186: Knowledge Aggregator + Three-Layer Cache

## Context

SPEC-184 defines the `web_search` slot; SPEC-185 defines the federated canonical-source connectors
that fill it. This spec defines the **aggregator** that orchestrates those connectors (SearXNG-scope
breadth, but over keyless canonical APIs instead of scrapers) and the **three-layer cache** in front
of it that cuts cost and latency and accretes a private, navigable knowledgebase. It also specifies
**comprehensive news coverage**: an opt-in publisher-RSS catalog and standing **topic monitors** that
continuously track subjects of interest.

The aggregator is a `web_search` slot provider; with the cache disabled it degrades to live
fan-out; with all connectors disabled it falls back to the opt-in keyed general-web provider.

## Goals

1. Reduce search cost (collapse repeat/near-repeat queries to cache hits — no metered API, no LLM).
2. Reduce latency (a hit is one indexed lookup vs. connector fan-out + synthesis).
3. Accrete a curated, relationship-navigable knowledgebase over time.
4. Comprehensive, user-curated news: select publisher feeds + define topic monitors that keep
   constant track of chosen subjects.
5. Source-agnostic **standing monitors** that nightly-track the operator's own sources (specific repos
   like LiteLLM/OpenClaw/Hermes, arXiv AI categories, news topics) into the pre-cached knowledgebase.

## Non-goals

- A general-web crawler/index (explicitly rejected in SPEC-184/185).
- A graph database (see L3 — relational now; documented upgrade trigger only).
- Storing copyright-restricted full text (link + summary only).

## Decision

### Aggregator kernel

A `web_search` slot provider with a SearXNG-shaped kernel, but over SPEC-185 connectors:
**receive → classifier routes domain(s) → fan out to the matched connectors → normalize → dedupe by
URL → rank by `canonical_tier` then recency**. Routing (not blind fan-out) keeps a query to its 2–3
relevant connectors. Returns normalized `SourceResult`s (SPEC-185).

### Three-layer cache

All layers live in the existing Postgres (pgvector + relational); embeddings via
`protocols/embeddings.py` using a pinned free/local model.

**L1 — Curated-answer cache.** `query → {answer, citations, source_ids, model, created_at,
freshness_class, hit_count}`, keyed by semantic similarity. A hit avoids **both** search and LLM —
cheapest and fastest. Returned only when similarity ≥ τ **and** the entry is fresh for its
`freshness_class`.

**L2 — Result-pair cache.** `query → normalized SourceResults`, keyed by semantic similarity. A hit
avoids live search (still re-synthesizes), serving rephrased questions with the same information need
and fresh synthesis over still-valid sources.

**L3 — Relational knowledge graph.** A property graph expressed as fixed relational tables + FK
junction tables (no graph DB). Provides recall-by-relationship that L1/L2 (recall-by-similarity)
cannot: temporal threading, corroboration, entity/outlet/author/topic traversal. A retrieval can
gather a connected subgraph and feed it as richer grounding into synthesis.

```sql
article(id, url, title, summary, published_at, outlet_id→outlet, author cache, fetched_at, freshness_class)
outlet(id, name, region, language)
author(id, name)
entity(id, name, type, wikidata_qid)          -- grounded to Wikidata (SPEC-185)
topic(id, name)
keyword(id, term)
-- edges = junction tables (FKs), all indexed
article_author(article_id, author_id)
article_entity(article_id, entity_id, salience)
article_topic(article_id, topic_id)
article_keyword(article_id, keyword_id)
article_link(from_article_id, to_article_id)  -- references / same-event clustering
```

Query mapping (all 0–2 hop indexed joins): by day → `published_at::date`; by outlet/author → FK/join;
mentioning entity → `article_entity`; same topic → `article_topic`; co-occurring entities →
self-join `article_entity`; story thread → order by `published_at` within a topic/entity;
corroboration → cluster on `article_link`.

**Edge cost split — most of the graph is free:**
- **Free from RSS/connector metadata (no extraction):** `outlet`, `author`, `published_at`/day,
  `keyword`/category. Insert + FK.
- **Optional async enrichment (NER/LLM):** `entity` mentions, `topic` clustering. Off the hot path;
  toggleable capability; entities resolved to Wikidata QIDs.

**Upgrade trigger (documented escape hatch):** the FK schema *is* a property graph and projects
directly into a graph model. **If multi-hop variable-length traversal or graph algorithms (community
detection for story-clustering, centrality for source-influence, path analysis for narrative-spread)
become a product requirement**, light up **Apache AGE** (openCypher + graph algos inside this same
Postgres — no second service). Stand up a dedicated graph DB (Neo4j/Memgraph) only on measured need.
No re-architecture in either case.

### Cache-first flow

```
query → embed
  ├─ L1 lookup (similar ∧ fresh) ── HIT ─▶ return answer+citations        [~ms, $0, no LLM]
  └─ MISS
     ├─ L2 lookup (similar ∧ fresh) ── HIT ─▶ reuse sources (skip search)
     └─ MISS ─▶ classifier routes ─▶ fan out to connectors ─▶ normalize/dedupe/rank
                ─▶ write-through L2 ─▶ async: enrich L3 (edges)
     ─▶ synthesize (grounded + cited; may pull an L3 subgraph for context)
     ─▶ write-through L1 ─▶ return
```

### Policies

- **Similarity threshold τ** — central knob; conservative default to avoid serving a cached answer to
  a *different* question. Measured/tuned.
- **Freshness classes** (SPEC-185): `volatile` (news/markets/weather → minutes or no-cache),
  `semi_stable` (docs → days/weeks), `stable` (definitions/history → long-lived, accretes).
- **Embedding stability** — pin the embedding model; a change invalidates the vector space.
- **Negative caching** — remember "no good answer" to avoid re-fan-out of dead queries.
- **Eviction** — LRU + freshness expiry; `stable` entries persist as the knowledgebase.

### Comprehensive news coverage

News is the priority domain and gets dedicated machinery on top of the SPEC-185 news layers.

**1. Opt-in publisher-RSS catalog.** A curated catalog of top-X outlets across categories (world,
US/regional, business/finance, tech, science, politics, sports), each
`{name, rss_url, category, region, language, paywall?, license}`, shipped in the maintainer registry
(refreshed via SPEC-005). **The user selects which outlets are their canonical news defaults** via the
SPEC-185 catalog UI; selection persists in SPEC-184 capability settings (per-install/per-user). RSS
gives headline+summary+link (publisher-sanctioned); the metadata populates L3 edges for free.

**2. News topic monitors.** News topics are tracked via the general **Standing monitors** mechanism
(below), materialized as **Google News RSS query feeds** (`news.google.com/rss/search?q=<query>`,
keyless), **GDELT DOC queries** (global, 15-min), and **keyword-filtered slices** of the selected
publisher feeds — building a time-threaded, corroboration-scored corpus per subject that L3 exploits
("how has this story developed; which outlets corroborate it").

**3. Full text.** From the Guardian Open Platform where available (free, full body); else on-demand
Jina Reader fetch for summarization. **Full text is never stored** — store snippet + own summary +
URL (copyright).

### Standing monitors (scheduled source tracking)

Monitors are **source-agnostic** — news is just one instance. A monitor tracks *any* SPEC-185
connector that exposes a pollable feed or query, on a schedule (default **nightly**), auto-ingesting
new items into the cache/graph so they are pre-cached and relationship-navigable. The operator's own
recurring interests (specific repos, arXiv categories, news topics) are first-class.

A monitor: `{name, connector, query/filter, interval, freshness, retention}`.

**Refresh interval is per-monitor configurable, with `freshness_class`-driven defaults** — not a single
fixed run. News (`volatile`) defaults to frequent polling (e.g. **hourly**, or finer for breaking
topics); repos/papers (`semi_stable`) default to **nightly**; rarely-changing sources can poll weekly.
The operator may override any monitor's interval. The scheduler respects shared rate limits and backs
off when a feed reports no changes.

Examples — all keyless feeds, all through one poller:
- **Repo commits/releases** — GitHub Atom feeds: `github.com/{owner}/{repo}/commits/{branch}.atom`,
  `/releases.atom`, `/tags.atom`. E.g. track **LiteLLM, OpenClaw, Hermes-agent** and other repos for
  new commits/releases.
- **arXiv** — category/query Atom feeds, e.g. `export.arxiv.org/api/query?search_query=cat:cs.AI`
  (also `cs.LG`, `cs.CL`) — **new AI papers**, nightly.
- **News** — Google News RSS query + GDELT (above).
- **Packages / Q&A** — PyPI / npm release feeds; Stack Exchange tag feeds.

A scheduler/poller (reuse `tasks/runner.py`) fetches each monitor's feed at its configured interval,
dedupes against the cache, and ingests new items into **L2** (sources) and **L3** (edges — repos: author/date/repo/tag come free;
papers: author/date/category free, entities/topics via optional enrichment), optionally updating a
rolling **L1** digest per monitor. Monitors honor `retention` (prune/archive) and `freshness`
(cadence). This turns recurring interests into a self-maintaining, pre-cached, time-threaded
knowledgebase — L3 then answers "what changed in LiteLLM this week" or "new cs.AI papers on X" by
traversal, not re-search. (Synergy: this is the substrate the conductor's morning-digest feature can
read from instead of searching live.)

## Acceptance criteria

- [ ] The aggregator is a valid `web_search` slot provider (SPEC-184); routing hits only the
      classifier-matched SPEC-185 connectors, not a blind fan-out; results normalize/dedupe/rank.
- [ ] L1 hit returns answer+citations with **no** connector call and **no** LLM call (asserted via
      spies); L2 hit skips the live connector call but still synthesizes.
- [ ] Cache lookups are semantic (embedding similarity ≥ τ) **and** freshness-gated; a `volatile`
      entry past its TTL is never served (test with a clock fixture).
- [ ] L3 schema exists as relational tables + FK junctions; the listed queries (by day/outlet/author/
      entity/topic, co-occurrence, temporal thread, corroboration) run as indexed SQL; a test asserts
      day/outlet/author/keyword edges populate from RSS metadata with **no** NER.
- [ ] Entity/topic enrichment is an optional async job (toggleable); entities resolve to Wikidata
      QIDs; disabling it leaves L1/L2 + the free L3 edges fully functional.
- [ ] A documented `// upgrade-trigger: Apache AGE` note exists where multi-hop/graph-algorithm needs
      would arise; no graph DB is a dependency.
- [ ] **News:** a user can select publisher RSS feeds from the catalog as defaults, and create a
      **topic monitor** that polls Google-News-RSS/GDELT/filtered-feeds on a schedule and ingests new
      articles into L2/L3 (verified end-to-end with a fake feed); full text is fetched-not-stored.
- [ ] **Standing monitors are source-agnostic:** a monitor over a **GitHub commits/releases Atom feed**
      (e.g. LiteLLM) and one over an **arXiv category feed** (cs.AI) both run on the scheduler at their configured interval (news hourly / repos nightly by `freshness_class` default, operator-overridable) and
      ingest into L2/L3 via the same code path as news (verified with fake feeds); repo/paper metadata
      edges (author/date/repo-or-category) populate with **no** NER.
- [ ] Embedding model is pinned; a model change is flagged as a cache-invalidating migration.
- [ ] With the cache disabled the aggregator still serves via live fan-out; with all connectors
      disabled it falls back to the opt-in keyed general-web provider or `safe_noop`.

## Testing

- Unit: cache-key embedding + τ threshold; freshness gating per class; negative cache; eviction;
  L3 query builders; monitor → feed-URL materialization.
- Contract: aggregator conforms to the `web_search` slot Protocol; `SourceResult` normalization.
- Integration: full cache-first flow against fake connectors (L1/L2 hit + miss paths, no restart);
  topic-monitor poll → dedupe → ingest → L3 edges, against a fake RSS/GDELT feed.
- Property (formal/): "a stale `volatile` entry is never served"; "full text is never persisted for a
  copyright-restricted source"; "discovery/enrichment never raises into a consumer".

## Open questions

- τ defaults per domain (news vs reference) — single global vs per-domain thresholds.
- L1 digest maintenance for topic monitors — recompute on each poll vs on read.
- Monitor scaling — poll cadence vs feed count; shared scheduler limits (reuse `tasks/runner.py`).
- Whether topic-monitor corpora are per-user isolated or shareable within an install (SPEC-184 scopes).

## References

- [SPEC-184: Modular capability platform](SPEC-184-modular-capability-platform.md)
- [SPEC-185: Canonical source registry](SPEC-185-canonical-source-registry.md)
- [SPEC-005: Medley (publish/trust/update)](SPEC-005-clawhub-full.md)
- [ADR-016: episodic store](../adr/ADR-016-episodic-store.md)
- [ADR-034: memory canonical ownership](../adr/ADR-034-memory-canonical-ownership.md)
- Upgrade path: Apache AGE (openCypher graph queries inside Postgres) — only on measured multi-hop /
  graph-algorithm need.
