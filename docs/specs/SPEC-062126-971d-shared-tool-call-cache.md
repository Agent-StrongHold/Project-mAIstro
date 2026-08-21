---
id: SPEC-062126-971d
title: "Shared widget/chat tool-call protocol and cached Airtable data plane"
repo: maistro-engine
kind: spec
status: In Progress
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related: []
implements: []
supersedes:
  - maistro-engine#SPEC-070126-b2e4
blocks: []
blocked-by: []
contracts:
  - behavioral
  - cross-service
tests:
  - tests/hive_conductor/test_tool_primitives.py
  - tests/hive_conductor/test_airtable_cache.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062126-971d: Shared Tool-Call Protocol and Cached Airtable Data Plane

## Finding addressed

The deep dive found that widget routes and chat tools accessed the same product systems through separate ad-hoc paths. Follow-up review clarified that Airtable widgets were likely issuing similar concurrent API calls and should reuse a local copy until explicit refresh or TTL expiry.

## Problem

Dashboard widgets and chat tools are different transports over the same tool calls. Without shared primitives, they duplicate credential lookup, provider ordering, fallback user behavior, and upstream Airtable requests. Concurrent widgets can stampede Airtable even when requesting the same table and parameters.

## Current partial implementation

- `ToolCallContext`, `ToolCredentialResolver`, provider constants, and `ToolCallTTLCache` exist in `services/tool_primitives.py`.
- Airtable records and metadata wrappers exist in `services/airtable_cache.py`.
- Airtable widget routes and chat Airtable tools use the cached wrappers and accept refresh flags.
- Unit tests cover credential resolver behavior, TTL reuse, concurrent miss coalescing, and Airtable forced refresh.

## Design

1. Treat chat tools and widget endpoints as tool-call clients over common primitives.
2. Use one credential-resolution contract for all shared providers.
3. Cache external tool-call responses by provider, token fingerprint, base/resource id, table/path, and normalized params.
4. Return defensive copies from cache so consumers cannot mutate shared state.
5. Coalesce concurrent misses per key so only one upstream request runs for identical cold calls.
6. Expose an explicit `refresh`/`force_refresh` path for user-driven refresh and admin invalidation.
7. Keep TTL configurable by environment, with a safe default of 60 seconds.
8. Extend the same primitive to Jira/Confluence only after Airtable semantics are stable.

## Acceptance criteria

- [x] Shared credential/context primitives exist for widgets and chat.
- [x] Airtable records use TTL caching with defensive copies.
- [x] Concurrent identical Airtable record misses coalesce to one upstream call.
- [x] Widget routes expose a refresh flag for Airtable data.
- [x] Chat Airtable tools expose a refresh argument.
- [ ] Cache metrics/logging record hit, miss, refresh, and load-error counts.
- [ ] A documented invalidation hook exists for credential changes and base/table config changes.
- [ ] Integration tests prove two widgets requesting the same Airtable table share one upstream fetch.
