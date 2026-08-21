---
id: SPEC-185
title: "Canonical source registry — federated domain connectors for the web_search slot"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-29
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-014
  - maistro-engine#SPEC-005
  - maistro-engine#ADR-016
  - maistro-engine#ADR-034
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-184
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

# SPEC-185: Canonical Source Registry

## Context

SPEC-184 establishes that the `web_search` slot is **not** a general-web search engine but a
**federated set of typed domain connectors**, each pointing at the *canonical authoritative source*
for its data type, with the intent classifier routing queries to the right connector(s). This spec
defines the connector contract and the concrete source registry.

Rebuilding Google (web-scale crawl + inverted index + behavioral-ranking flywheel) is infeasible and
unnecessary. The goal is **authoritative answers from trusted sources for an agent**, where a curated
set of canonical connectors beats open-web search on quality (no SEO spam, controlled trust) and is
tractable per-source for license/ToS review.

## Decision

### Canonical tiers

Every source is classified into one tier, which drives default trust and routing priority:

- **`system_of_record`** — *the* definitive source for its data; not "a source" but "the source"
  (SEC EDGAR for US filings, USPTO for patents, NVD for CVEs, IANA for timezones, MusicBrainz for
  music metadata). Highest trust.
- **`authoritative_aggregator`** — high-quality curated secondary source (Wikipedia, GDELT,
  Semantic Scholar).
- **`marketplace_vertical`** — transactional domains where the data *is* the business (travel fares,
  commerce, tickets). Usually keyed/affiliate/B2B; a few keyless community/government exceptions.

### Connector contract (boundary)

Each connector implements the `CapabilitySource` Protocol (a `web_search` slot provider per SPEC-184):

```
class CapabilitySource(Protocol):
    id: str
    domains: list[str]            # e.g. ["news"], ["chemistry","science"]
    canonical_tier: Tier          # system_of_record | authoritative_aggregator | marketplace_vertical
    access: Access                # keyless | free_key | oauth | commercial | open_protocol
    billing_model: BillingModel   # free_tier | subscription | subscription_capped | metered (per SPEC-184)
    license: str                  # data license / reuse terms (e.g. "CC-BY-SA", "public-domain", "ToS-restricted")
    freshness_class: Freshness    # volatile | semi_stable | stable
    rate_limit: RateLimit | None
    async healthcheck() -> Health
    async query(q: SourceQuery) -> list[SourceResult]
```

`SourceResult` is the normalized shape every connector returns:
`{title, url, snippet, source_id, published_at?, license, raw?}`. The curated index (SPEC-184 #9)
caches `SourceResult`s and sits in front of all connectors; copyright-restricted full text is
**linked, not stored** (store snippet + own summary + URL).

### Classifier → connector routing

Reuse the existing intent classifier (`packages/maistro-core/src/maistro/classifier/`). The
`task_type` / detected domain maps to an ordered connector list via a routing table in settings.
Multi-domain queries fan out to multiple connectors and merge (dedupe by URL, rank by
`canonical_tier` then recency). When no connector matches a query, the slot falls back to the
**opt-in keyed general-web provider** (Tavily/Exa) or `safe_noop` if none is enabled.

### The registry

Access: ✅ keyless · 🔑 free key · 🌐 open protocol · 🔐 oauth · 💳 commercial.
Tier: **SoR** system_of_record · **Agg** aggregator · **Mkt** marketplace_vertical.
Sources marked **⟲verify** have free tiers that drift — re-confirm access/limits at build time.

#### Knowledge & reference
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Encyclopedia/facts | Wikipedia, Wikidata, Wiktionary (MediaWiki API) | ✅ | Agg/SoR | CC-BY-SA |
| Dictionary/words | Free Dictionary API, Datamuse, Wiktionary | ✅ | Agg | mixed |
| Language/translation | LibreTranslate (self-host) 🌐; DeepL/Google 🔑⟲verify | 🌐/🔑 | Agg | mixed |
| Math | OEIS (sequences) ✅; Wolfram Alpha 🔑💳 | ✅/🔑 | SoR | mixed |

#### Science
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Chemistry | PubChem (NIH), ChEMBL | ✅ | SoR | public-domain |
| Biology/genetics | UniProt, RCSB PDB, Ensembl ✅; NCBI GenBank 🔑 | ✅/🔑 | SoR | open |
| Astronomy | NASA APIs 🔑, JPL Horizons ✅, SIMBAD ✅, Exoplanet Archive ✅ | ✅/🔑 | SoR | public-domain |
| Earth/climate | USGS (quakes/water) ✅, NOAA 🔑, NASA EarthData 🔑, Copernicus 🌐 | ✅/🔑 | SoR | public-domain |
| Constants | NIST CODATA | ✅ | SoR | public-domain |

#### Academic
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Papers/preprints | arXiv ✅, Crossref ✅, Semantic Scholar ✅, PubMed/E-utilities ✅; OpenAlex 🔑⟲verify | ✅/🔑 | Agg/SoR | open metadata |

#### Health & medicine
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Drugs | openFDA, RxNorm/DailyMed (NIH) | ✅ | SoR | public-domain |
| Clinical trials | ClinicalTrials.gov | ✅ | SoR | public-domain |
| Conditions | MedlinePlus (NIH) ✅, ICD/WHO ✅ | ✅ | SoR | open |
| Nutrition | OpenFoodFacts ✅; USDA FoodData Central 🔑 | ✅/🔑 | SoR | ODbL/public |
| Public-health stats | WHO GHO ✅, CDC WONDER ✅, Our World in Data ✅ | ✅ | Agg | open |

#### Economy, finance, business
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Indicators | FRED, World Bank, IMF, OECD, Eurostat, BLS, BEA | ✅ | SoR | public-domain |
| Filings/companies | SEC EDGAR ✅ (SoR); Companies House 🔑, OpenCorporates 🔑⟲verify | ✅/🔑 | SoR | mixed |
| FX rates | ECB / Frankfurter ✅, exchangerate.host ✅ | ✅ | SoR | open |
| Crypto | CoinGecko 🔑⟲verify, mempool.space ✅, explorers 🔑 | ✅/🔑 | Agg | mixed |
| Markets (real-time) | Alpha Vantage / Finnhub / Polygon 🔑💳⟲verify | 🔑💳 | Mkt | ToS-restricted |

#### Forecasting & prediction markets (estimative, not fact)
These return **crowd/forecaster probability estimates** for future or uncertain events — a distinct
query type ("what's the probability X happens by Y"). They are **not** `system_of_record`; results
carry `result_kind: estimate` with provenance (market, liquidity, timestamp) and a calibration
caveat (thin-market noise, longshot bias, manipulation risk on illiquid markets). Real-money markets
(Polymarket/Kalshi) are generally better-calibrated than play-money (Manifold).
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Prediction markets | Polymarket (read ✅), Kalshi (read ✅), Manifold (✅ play-money), Metaculus (✅ forecasts) | ✅ reads | Agg | ToS-restricted |
| Aggregators | FinFeedAPI, PolyRouter, Prediction Hunt v2 🔑⟲verify | 🔑 | Agg | ToS-restricted |

#### Government, legal, civic
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Legislation | Congress.gov 🔑, GovInfo ✅, eCFR/Federal Register ✅, EUR-Lex ✅, legislation.gov.uk ✅ | ✅/🔑 | SoR | public-domain |
| Case law | CourtListener/RECAP ✅, Caselaw Access Project ✅ | ✅ | SoR | public-domain |
| Patents/IP | USPTO PatentsView ✅; EPO OPS 🔑 | ✅/🔑 | SoR | public-domain |
| Spending/elections | USAspending.gov ✅, FEC ✅; Google Civic 🔑 | ✅/🔑 | SoR | public-domain |
| Open-data portals | data.gov ✅, data.europa.eu ✅, data.gov.uk ✅ | ✅ | SoR | open |

#### Developer & technical
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Packages | PyPI, npm, crates.io, pkg.go.dev, Docker Hub, Maven, RubyGems, Packagist | ✅ | SoR | open |
| Security/vulns | NVD (NIST) ✅, OSV (Google) ✅; GitHub Advisory 🔑 | ✅/🔑 | SoR | public-domain |
| Standards/docs | IETF RFCs ✅, MDN ✅, caniuse ✅, W3C ✅ | ✅ | SoR | open |
| Q&A/code | Stack Exchange ✅(rate-limited), GitHub 🔐(60/hr unauth), HN Algolia ✅ | ✅/🔐 | Agg | CC-BY-SA |
| Network/DNS | RDAP/WHOIS ✅, DoH (Cloudflare/Google) ✅, RIPEstat ✅; Shodan 💳 | ✅/💳 | SoR | mixed |
| IP geo | ip-api ✅; ipinfo 🔑⟲verify | ✅/🔑 | Agg | mixed |

#### Geography, transport, travel
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Places/maps | OSM Nominatim ✅(usage policy), GeoNames ✅, OSRM/OpenRouteService ✅ | ✅ | SoR | ODbL |
| Countries | REST Countries ✅, CIA World Factbook ✅ | ✅ | Agg | open |
| Flights (live) | OpenSky Network ✅, OurAirports ✅ | ✅ | SoR/Agg | open |
| Vehicles | NHTSA vPIC (VIN/recalls) ✅, fueleconomy.gov ✅, CarQuery ✅ | ✅ | SoR | public-domain |
| Transit | GTFS feeds 🌐; Transitland 🔑 | 🌐/🔑 | SoR | open |
| **Airfare/hotels (Mkt)** | Amadeus Self-Service 🔑⟲verify (flights+hotels+cars, free dev tier), Duffel 🔑 (self-serve, pay-per-order); Skyscanner 💳 (partner-only) | 🔑/💳 | Mkt | ToS-restricted |

#### Media, culture, entertainment
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Music | MusicBrainz ✅(CC0, SoR), ListenBrainz ✅; Discogs/Last.fm 🔑; Spotify 🔐 | ✅/🔑 | SoR | CC0/mixed |
| Books/texts | Open Library ✅, Project Gutenberg ✅(full public-domain texts); Google Books 🔑 | ✅/🔑 | Agg | open |
| Art/museums | Met Museum ✅, Art Institute Chicago ✅, Smithsonian Open Access ✅; Europeana/Rijksmuseum 🔑 | ✅/🔑 | SoR | CC0/open |
| Movies/TV | TMDB 🔑⟲verify, OMDb 🔑, Wikidata ✅ | ✅/🔑 | Agg | mixed |
| Video | YouTube Data API v3 🔑(quota); Invidious 🌐(gray fallback) | 🔑/🌐 | Mkt | ToS-restricted |
| Games (video) | RAWG/IGDB 🔑; Steam ✅ | ✅/🔑 | Agg | mixed |
| **Board games** | BoardGameGeek XML API2 | ✅ | SoR | ToS (non-commercial) |
| **TCG/cards** | Scryfall (MTG) ✅, YGOPRODeck ✅; Pokémon TCG 🔑 | ✅/🔑 | SoR | mixed |
| Anime/manga | Jikan (MAL) ✅, AniList ✅ | ✅ | Agg | open |
| Podcasts | Podcast Index ✅ | ✅ | Agg | open |
| Images (CC) | Openverse ✅, Wikimedia Commons ✅, NASA Image Library ✅; Unsplash 🔑 | ✅/🔑 | Agg | CC/public |

#### Social sphere (per SPEC-184)
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Open social (default) | Nostr 🌐, Bluesky (public AppView ✅; search free-auth 🔐), Mastodon ✅, Lemmy ✅, HN ✅ | ✅/🌐/🔐 | Agg | mixed |
| Restricted (opt-in) | Reddit 🔐(free OAuth, non-commercial) | 🔐 | Mkt | ToS-restricted |
| Platform-closed | X (metered, $0.005/read) 💳; Facebook/Instagram — no public search (Meta Content Library = vetted researchers) | 💳/✖ | Mkt | unavailable |

#### News (the priority domain)
No single keyless full-text canonical exists (copyright), so news is a **layered strategy** whose
**default is a user-selected list of publisher RSS feeds** (see below).

| Layer | Source | Access | Tier | Notes |
|---|---|---|---|---|
| Publisher RSS (**default**) | curated top-X outlets (Reuters, AP, BBC, Guardian, NPR, Al Jazeera, …) | ✅ | Agg | publisher-sanctioned syndication; headline+summary+link |
| Full text (free) | **The Guardian Open Platform** | 🔑 free (500/day) | SoR | rare — returns full article body, 1999–present |
| Global discovery | GDELT DOC 2.0 + GKG | ✅ | Agg | global, 15-min, multilingual; links/metadata, no full text |
| Query-able headlines | Google News RSS (`news.google.com/rss`) | ✅ | Agg | keyless topic/query/geo feeds; ToS-gray |
| CC-licensed | Wikinews ✅ (CC-BY), Wikipedia Current Events ✅ | ✅ | Agg | freely reusable |
| Aggregator APIs (opt-in) | TheNewsAPI, WorldNewsAPI, NewsData.io, GNews (full-text extract) | 🔑⟲verify | Mkt | check commercial-use allowance; NewsAPI.org free = dev/localhost only |
| Financial news | Alpha Vantage / Finnhub / Marketaux | 🔑⟲verify | Mkt | sentiment-tagged |

**User-selectable news defaults.** The news connector's primary source is a **curated catalog of
publisher RSS feeds**, each `{name, rss_url, category, region, language, paywall?, license}`, shipped
in the maintainer registry (refreshed per SPEC-005). **The user selects which outlets form their
canonical news defaults** via the SPEC-185 catalog UI; the selection persists in SPEC-184 capability
settings (per-install/per-user). RSS yields headline+summary+link (sanctioned); full text comes from
the Guardian API where available, else on-demand Jina Reader fetch (summarize/link, **never store
full text** — copyright). GDELT + Google News RSS backstop coverage beyond the selected feeds.

#### Commerce, jobs, events, local
| Domain | Source | Access | Tier | License |
|---|---|---|---|---|
| Shopping/products | eBay Browse 🔑⟲verify; Amazon PA-API 💳(affiliate); OpenFoodFacts ✅(barcode); UPCitemdb 🔑 | ✅/🔑/💳 | Mkt | ToS-restricted |
| Jobs | USAJOBS (gov) ✅; Adzuna 🔑⟲verify | ✅/🔑 | Mkt | mixed |
| Events/tickets | Ticketmaster Discovery 🔑⟲verify, SeatGeek 🔑, Bandsintown 🔑 | 🔑 | Mkt | ToS-restricted |
| Local/reviews | OSM ✅; Yelp Fusion 🔑⟲verify; Google Places/Foursquare 🔑💳 | ✅/🔑 | Mkt | ToS-restricted |
| Recipes | TheMealDB 🔑; Spoonacular/Edamam 🔑⟲verify | 🔑 | Agg | mixed |
| Real estate | mostly 💳 (ATTOM); county records vary | 💳 | Mkt | restricted |

### Registry distribution, refresh & trust (rides on SPEC-005 / Medley)

The registry is **not** a static in-repo manifest — it is a **living catalog refreshed from a remote
source**, so that a source's changed free tier, new endpoint, or retirement (the `⟲verify` drift
problem) is fixed *centrally* by maintainers instead of every instance shipping stale data. This
reuses the SPEC-005 (Medley) publish/trust/update mechanism wholesale — no new distribution system.

Layered precedence (later layers override earlier by source `id`):

1. **Built-in defaults** — a minimal keyless catalog shipped in core so a fresh install works offline
   (Wikipedia, GDELT, arXiv, NVD, …).
2. **Maintainer remote catalog** — the canonical registry, published as a **signed Medley artifact**
   and refreshed by each instance (semver-pinned, revocation re-checked per SPEC-005). This is where
   free-tier corrections and new sources land between mAIstro releases.
3. **Community sources** — third-party connectors published as Medley plugins with a publisher VC +
   DID trust chain; surfaced in the catalog with their `trust_tier`. Unsigned community sources are
   blocked unless `--allow-unsigned` + admin signature (SPEC-005 default).
4. **User-imported / private** — local manifest entries (a private internal API, a niche or personal
   corpus) the operator adds directly; never published, admin-gated like any local source.

**Selection UI.** Hive Conductor exposes the catalog (modeled on the existing `skills.py` / `mcp.py`
routes): browse by domain, see `canonical_tier` / `access` / `billing_model` / `license` /
`trust_tier`, toggle a source on (which activates its connector per SPEC-184) or **import your own**.
Refresh is on a schedule + on demand, reconciling into the live `CapabilityRegistry` without restart.

### Gaps with no open canonical

Real-time markets, live sports (mostly), products/commerce pricing, real estate, and licensed media
(lyrics, streaming catalogs) have **no keyless canonical** — the data is the vendor's business. These
stay `marketplace_vertical` keyed/opt-in, or fall back to the opt-in keyed general-web provider.

**General web search** has no clean canonical (you cannot rebuild Google). The general-web fallback
`web_search` provider is filled by one of these **opt-in** options:
- **SearXNG (self-hosted)** — a meta-search aggregator the operator runs themselves. Offered as an
  opt-in provider **for those who want it**, tagged **`license: AGPL-3.0` / self-host-only /
  do-not-bundle**: mAIstro calls it over HTTP (arm's-length — no AGPL obligation on mAIstro) but never
  ships or modifies it. Reliability is best-effort (it scrapes upstream engines). The operator already
  runs one on the homelab (85 engines) that can fill this slot directly.
- **Tavily / Exa** — keyed metered APIs with clean, LLM-ready results.
- **`llm_native_search` models** — Perplexity Sonar, Gemini Google-Search grounding, OpenRouter
  `:online`, xAI Grok live search: search **and** synthesis in one call (a "smart search" — reasoned,
  cited answer, not raw links). `billing_model` metered/subscription; the SPEC-186 L1 answer cache
  means each such smart-search is paid for once then served free.

## Acceptance criteria

- [ ] A `CapabilitySource` Protocol exists (per the contract above), `mypy --strict` clean; it is a
      valid `web_search` slot provider under SPEC-184.
- [ ] The registry is a declarative manifest (one entry per source) carrying domain(s),
      `canonical_tier`, `access`, `billing_model`, `license`, `freshness_class`, `rate_limit`,
      endpoint, and `auth_env`; loadable without code changes.
- [ ] At least these **keyless** connectors are implemented and return normalized `SourceResult`s
      against live endpoints: Wikipedia, GDELT, arXiv, NVD, PubChem, MusicBrainz, BoardGameGeek,
      Scryfall, OpenSky, SEC EDGAR.
- [ ] The classifier routes a domain-typed query to the correct connector(s); a multi-domain query
      fans out and merges (dedupe by URL, rank by tier then recency); a no-match query falls back to
      the opt-in keyed general-web provider or `safe_noop`.
- [ ] Copyright-restricted sources (news, social) return snippet + URL only; full text is fetched
      on demand (Jina Reader) and **not persisted** — asserted by a test.
- [ ] Every `🔑`/`💳` source is tagged with its `billing_model` and flagged for build-time
      free-tier re-verification (the `⟲verify` set); a CI/doc check lists them.
- [ ] Platform-closed sources (Facebook) are present in the registry marked `unavailable` so they are
      not retried.
- [ ] The registry refreshes from a remote maintainer catalog over Medley (SPEC-005): an updated
      source entry (e.g. a changed free-tier limit) propagates to a running instance via refresh
      without a mAIstro release or restart; built-in defaults work offline.
- [ ] A user can **import a private source** via a local manifest entry that never publishes; a
      community source installs only with a verified publisher VC (or `--allow-unsigned` + admin).
- [ ] The catalog is browsable/toggleable in Hive Conductor (per `skills.py`/`mcp.py` patterns),
      showing `canonical_tier`/`access`/`billing_model`/`license`/`trust_tier` per source.

## Testing

- Unit: registry manifest validation; routing table (domain → ordered connectors); merge/dedupe/rank.
- Contract: `CapabilitySource` Protocol conformance per connector; normalized `SourceResult` shape.
- Integration: live `query()` for the keyless connector set (network-gated, skippable offline).
- Property (formal/): "a copyright-restricted connector never returns stored full text"; "no-match
  query never raises into the consumer."

## Open questions

- Connector freshness/refresh cadence vs the SPEC-184 #9 cache TTLs — single freshness policy or
  per-connector override? (Working assumption: per-connector `freshness_class` wins.)
- Whether `marketplace_vertical` connectors ship in core (disabled) or live only as opt-in plugins
  (leaning opt-in plugins, to keep the shipped artifact license-clean).
- Per-region source variants (EU vs US gov/legal sources) — registry tagging vs separate connectors.

## References

- [SPEC-184: Modular capability platform](SPEC-184-modular-capability-platform.md)
- [SPEC-014: LiteLLM free-tier auto-configuration](SPEC-014-litellm-freetier.md)
- [ADR-016: episodic store](../adr/ADR-016-episodic-store.md)
- [ADR-034: memory canonical ownership](../adr/ADR-034-memory-canonical-ownership.md)
- Verified source landscape (2026): GDELT (keyless), Amadeus/Duffel (free dev / self-serve),
  Skyscanner (partner-only), BoardGameGeek XML API2 (keyless), Scryfall (keyless), X API
  (pay-per-read), Meta Content Library (researcher-gated).
