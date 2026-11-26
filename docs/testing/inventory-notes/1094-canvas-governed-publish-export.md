---
inventory-delta:
  packages/maistro-canvas/tests: +26
  packages/maistro-server/tests: +7
---

# Governed Design Studio publish/export for Canvas-backed artifacts (#94, M3-B4)

Replaces the `/v2/canvas` 501 publish stub and the direct-compositor export
with the governed `design.export` capability (`maistro_canvas.canvas.publishing`),
crossed through Binding -> Governed/InvocationExecutionService -> Invocation,
with append-only `ExportVersion` artifacts carrying full provenance.

**+26** in `packages/maistro-canvas/tests/test_publishing.py` (new) exercise
the capability owner against the real `InvocationExecutionService` over
`InMemoryInvocationStore`:

- state pinning: `canvas_state_digest` is stable for identical accepted state,
  changes on layer/text/canvas edits, and deliberately ignores volatile audit
  timestamps so a non-visual touch cannot fork export versions.
- provider truthfulness: `pdf`/`svg` raise `EXPORT_FORMAT_UNSUPPORTED`;
  `png` passes the pinned composite through; `webp`/`jpg` require (and use) a
  compositor `encode` backend, raising `EffectNotApplied` when provably absent;
  `html` keeps text editable; `pptx` is honest about the python-pptx
  dependency (`ExporterDependencyError` when absent, real zip bytes when not).
- governed versions: a successful export appends one `ExportVersion` with
  invocation_id/binding_id/run/node/attempt provenance and a
  `ResolvedBinding` snapshot (`canvas-fixed-page-exporter`) on the COMPLETED
  Invocation; request-scoped canonical identity is deterministic per
  (org, canvas, format, state) so same-state re-export replays the completed
  Invocation and returns the identical version; an edit produces a NEW
  version while the historical row stays byte-identical; publish flags the
  version and records the DesignProject link.
- truthful failure: a crashing encoder records UNKNOWN (discoverable via
  `discover_ambiguous` semantics) and saves no version; a provably
  non-applied effect records FAILED; unsupported formats never create an
  Invocation at all.
- policy: a DENY verdict through `GovernedInvocationExecutionService` refuses
  the export, saves no version, and appends a
  `capability.invocation.policy_decision` event; an ALLOW verdict completes.
- isolation: an in-flight export (provider blocked on a gate) does not block
  an unrelated binding's export — dispatch happens outside the effect
  admission lock. A fake run spine lands canonical Run/NodeRun/Attempt ids on
  the version. The append-only store refuses duplicate export ids.

**+11/-4** in `packages/maistro-server/tests/api/test_canvas.py` rewire the
`/v2/canvas` contract: unconfigured governance stays a truthful 501 (no
ungoverned fallback); export streams bytes with
`X-Maistro-Export-Id`/`X-Maistro-Invocation-Id`/`X-Maistro-State-Digest`
headers; pdf/svg are an explicit 422 before any compositing work; re-export
after an edit yields a second version and the historical one re-downloads
byte-exactly; provider crashes surface as 502 naming the failure; policy
denials surface as 403; publish returns the governed version dict plus
`download_url`, emits exactly one `design.published` event (export emits
`design.exported`), and a publish-then-download round-trip delivers the exact
published bytes.
