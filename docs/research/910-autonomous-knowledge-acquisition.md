# M8-K research charter — autonomous knowledge acquisition, monitoring, and evidence graphs

Epic: #910. Initiative: #879. No leaf issues are open yet; this charter fixes
the question, the canonical seams, the measurement plan, and the
observed-facts-versus-synthesis rule every future leaf must use.

## Research question

Can MAIstro continuously acquire, validate, connect, and refresh external
knowledge in a way that materially improves Workspace Agents without flooding
memory with low-quality or stale information?

## Canonical seams (verified in reachable production code)

A leaf may only run its experiment through these seams. Anything that needs a
new fetch path, a new store, or a new authority is production work and routes
through GRADUATE, not through this epic.

- **Egress / connector seam.** All outbound fetches ride the shared outbound
  policy: `OutboundPolicy`, `enforce_outbound_policy`, and
  `GuardedTransport`/`guarded` in
  `packages/maistro-core/src/maistro/security/outbound.py`, with URL admission
  from `maistro.security.ssrf.avalidate_outbound_url`
  ([ADR-082326-5386](../adr/ADR-082326-5386-outbound-http-policy-at-the-shared-client-seam.md)).
  The browser tool is already governed at its own boundary
  (`maistro.tools.browser.guard.BrowserNetworkGuard`, `#855`); a source monitor
  must not become a second, ungoverned client.
- **Untrusted-content boundary.** Fetched text enters as wrapped DATA, never as
  instructions: `wrap_external_content`, `detect_injection`, and
  `ContentSource` (WEB_FETCH/WEB_SEARCH/API/BROWSER/…) in
  `packages/maistro-core/src/maistro/security/external_content.py`. The same
  rule that already governs webhooks applies to every monitored source.
- **Knowledge ladder.** External material becomes a claim only through the
  Memory → Learning → Validated → Repertoire ladder
  (`maistro.types.memory.LearningStage`,
  `maistro.memory.learnings.lifecycle`;
  [ADR-103](../adr/ADR-103-knowledge-stage-ladder.md)). A stage is metadata
  and never grants authority — the Sentinel never reads it. Fresh external
  evidence lands at MEMORY with producer provenance; only the lifecycle's
  transitions may promote it, and VALIDATED requires an independent evaluator
  recorded in `Learning.validated_by` (Gauntlet provenance, `#118`).
- **Provenance axes.** Every stored fact names its producing execution:
  `run_id`/`node_run_id`/`attempt_id` on episodic and Learning records
  (`#709`; [ADR-090226-9c3f](../adr/ADR-090226-9c3f-episodic-memory-names-its-producing-run.md)),
  and every stage transition names its actor — anonymous provenance is no
  provenance (`lifecycle.py` raises rather than record one).
- **Evidence ledger, contradiction, and decay.** The lifecycle already carries
  the evidence ledger (`EvidenceLink` required on observe/advance), conflict
  tracking (`record_contradiction`, `find_conflicts`, `resolve_conflict`,
  `supersede`), and decay sweeps (`decay`,
  `EMPIRICAL_HALF_LIFE_DAYS`). Episodic records carry
  `contradiction_count`/`reinforcement_count`, and the contradiction review
  queue is never auto-resolved ([ADR-080](../adr/ADR-080-memory-dynamics.md)).
- **Change detection.** A monitor is a schedule that fires Runs; each firing is
  claimed by its occurrence with exactly one canonical `run_id`
  ([ADR-082426-82c7](../adr/ADR-082426-82c7-the-occurrence-is-the-claim-not-the-cursor.md)),
  which is the existing deduplication story for re-ingestion. "New" is a
  property of the occurrence, not of the crawler's cursor.

## Observed facts versus model synthesis

The epic's central trust rule maps onto the ladder directly: observed source
facts are occurrences — wrapped external content stored with
`ContentSource`, injection scan results, fetch URL, and producer provenance —
while any generalization, summary, or relationship extracted by a model is a
claim that starts at LEARNING and may only reach VALIDATED through an
evaluator distinct from its producer. An evidence graph that merges the two
(a node that is both the fetched sentence and the model's inference from it)
violates ADR-103 and is a REJECT finding, not a design option.

## Candidate leaves (to be opened with their own hypotheses and dispositions)

| Direction | Seam it must ride | First measurable question |
|---|---|---|
| Source monitors (repos, papers, docs, feeds, APIs) | outbound policy + schedules/occurrences (ADR-082426-82c7) | What fraction of firings yield a *new* occurrence rather than a duplicate? |
| Source credibility / provenance scoring | evidence ledger + `Learning.validated_by` axes | Does a credibility prior improve end-task accuracy, or only reorder retrieval? |
| Knowledge-graph construction / relationship extraction | ladder (claims) + episodic store (facts) | Do extracted relations improve retrieval/task impact over flat episodic recall at equal budget? |
| Freshness/decay and contradiction tracking | `decay` sweeps + `contradiction_count` / ADR-080 queue | Do lifecycle-native decay and conflict queues bound staleness without operator review growth? |
| Change detection and targeted re-ingestion | occurrence claiming per firing | Can re-ingestion be restricted to changed sources without missing silent updates? |
| Query-driven vs proactive acquisition | cost/quota seam vs the governed model path | Same retrieval/task impact at what relative cost? (Feeds #1051's bounded curation.) |
| Evidence bundles attached to Goals/decisions | EvidenceLink provenance axes | Do bundles change decision quality, or only add storage? |

## Measurement contract (per leaf)

Each leaf reports: retrieval/task impact (baseline vs treatment on a
representative Workspace workload — no benchmark-only adoption), freshness
(age of cited evidence at use), noise (bad claims per ingested source),
duplicate ingestion (duplicate occurrences per firing), provenance quality
(fraction of records with named producer and evaluator), cost (model calls,
fetches, storage), and operator burden (review-queue growth per 1,000
ingestions).

## Guardrails

1. Research code stays out of `packages/*/src`; experiments run against the
   seams above from tests, tools, or research harnesses.
2. No leaf may add a fetch path that bypasses the outbound policy, a store
   parallel to the memory stores, or a new promotion authority. ADR-103 already
   decided what a validated claim is; M8-K does not re-decide it.
3. A GRADUATE result routes production adoption to the connector/knowledge/
   memory owners and the earliest owning milestone — it does not authorize
   adoption inside M8.

## Record

No experiment has been run under this charter yet; the epic has no leaves.
This note adds no product code, no store, and no flag. The canonical seams
named above were verified present in the tree at the time of writing.

Disposition: WATCH
