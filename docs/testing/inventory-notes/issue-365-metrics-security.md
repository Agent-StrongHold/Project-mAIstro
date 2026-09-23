---
inventory-delta:
  packages/maistro-server/tests: +5
  packages/maistro-core/tests: +8
---

# Issue 365 metrics security

The metrics endpoint tests replace the former anonymous exposition-only test
with coverage for anonymous denial, the dedicated `admin:metrics` service
scope, wrong-scope denial, forwarded-header non-bypass, and a scoped scraper
behind proxy headers. Health tests retain readiness dependency coverage while
asserting that public probes return only status. SLO tests also verify that
credential-shaped service keys are represented by an opaque digest rather than
raw metric label text.

Repair follow-up (#365 registry backstop): the core registry tests now also
cover the family-level cardinality backstop — the overflow counter's `metric`
label is series-capped against dynamically minted metric names, brand-new
families past `DEFAULT_MAX_METRICS_PER_REGISTRY` are refused with a dropping
sink and counted in the unlabeled `metrics_registry_overflow_total`, the new
metric name is reserved, and a family cap below 1 is rejected.
