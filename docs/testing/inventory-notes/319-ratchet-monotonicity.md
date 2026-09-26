---
inventory-delta:
  tests/: +2
  scripts/: +1
  quality/: +1
---
# Issue 319 ratchet monotonicity

The starting tree already contains the #534/#542 trusted-base resolver and
JSON-ledger adapters. Review found that the provenance inventory's own
candidate-authored and adapter maps were candidate-controlled: a change could
add a consumer and its exception in the same tree. The committed policy map is
now loaded from the trusted base (with a first-landing fallback to the prior
literal maps), while the candidate copy is used only for stale-entry hygiene.
Mutation coverage proves a candidate-added exception cannot self-approve a new
consumer.
