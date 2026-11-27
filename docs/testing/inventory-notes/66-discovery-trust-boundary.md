---
inventory-delta:
  packages/maistro-core/tests: +9
---
# 66-discovery-trust-boundary

Nine maistro-core node IDs put the discovery pipeline (#1051) on issue #66's
trust boundary. The develop sync shipped an unattended product path — fetch
declared feed sources, scout, curate with a model, surface into the
Workspace — whose content crossed no Warden at all: fetched feed rows went
straight into the curator's model prompt, and the curator's completion folded
into surfaced items unscanned. That is exactly the class #66 closes: every
untrusted external result and every model answer is an explicit scan
boundary, and a missing gate must fail closed, not become allow-all.

The tests pin both boundaries through the production seams (governed egress
with the canonical Binding/Invocation authorities, fake HTTP transport,
mirroring `test_discovery_pipeline.py`):

- `test_discovery_trust_boundary.py` (8 of the 9): a poisoned feed refuses
  the cycle at the fetch node (refusal is the node's honest output; the
  second declared source is never queried), a clean feed still passes intact,
  an explicitly unavailable fetch warden fails closed, the fetch scan is the
  canonical `scan_inbound` composition with a `discovery_source` boundary
  label, a poisoned curator completion cannot fold into surfaced items (the
  refusal uses the node's established `refused:` strategy channel), a clean
  completion still surfaces, an unavailable curator warden fails closed, and
  a poisoned feed yields zero surfaced items through the seed's full
  fetch→scout→curate chain. One A2A-regression guard pins
  `scan_inbound`'s default boundary label for existing callers.

Red-first evidence: all eight boundary tests fail against the pre-fix nodes
(poisoned rows flowed into entries with `refusal == ""`; the poisoned
completion folded into a `CuratedItem`); the clean-path contrasts passed
throughout, so the boundary refuses content, not the mechanism.
