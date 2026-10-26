---
id: SPEC-102426-976a
title: "Extension identity, version, publisher, and provenance in canonical telemetry (issue #976 / M9-I1)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-10-24
accepted: 2026-10-24
substrate:
  - maistro-engine#ADR-083026-1cb1
implements:
  - maistro-engine#ADR-104
related:
  - maistro-engine#SPEC-083026-20b2
  - maistro-engine#ADR-100526-9c55
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/extensions/test_attribution.py
  - packages/maistro-core/tests/capabilities/test_provider_adapters.py
ac-modules:
  AC-1: maistro.capabilities.providers.extension_attribution
  AC-2: maistro.capabilities.providers.extension_attribution
  AC-3: maistro.observability.correlation
  AC-4: maistro.capabilities.providers.extension_attribution
  AC-5: maistro.events.envelope
  AC-6: maistro.capabilities.provider_adapters
source:
  - packages/maistro-core/src/maistro/capabilities/providers/extension_attribution.py
  - packages/maistro-core/src/maistro/extensions/attribution.py
layer: Observability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-24
  - status: Accepted
    date: 2026-10-24
---

# SPEC-102426-976a: Extension identity, version, publisher, and provenance in canonical telemetry

## Context

Epic M9 makes the platform governed-extensible, and ADR-104 fixes the
extension-side contract: an extension mediates effects only through
least-authority seams over the governed effect plane. What that contract did
not yet say is what an extension-mediated effect *names* after it happened.
Before this spec, an adapter-mediated model call or an installed extension's
activation could be traced to a Workspace, a Run, a NodeRun, an Attempt, and
an Invocation — and to nothing about the extension that caused it. The
acceptance in issue #976 is the missing half: every extension-mediated
operation must be traceable to the exact extension package, version, and
publisher — with the digest provenance that makes the identity reproducible —
**beside** the canonical caller identity, never instead of it.

This spec pins that evidence contract to measurable criteria. The carrier is
the closed, version-tagged attribution payload in
`maistro.capabilities.providers.extension_attribution` (re-exported unchanged
by `maistro.extensions.attribution`, which adds the constructors that read the
canonical install record). The evidence rides Binding snapshots,
`EventEnvelope.provenance`, Invocation records, and structured log fields.
Three boundaries are part of the contract rather than commentary:

- **Attribution is not a correlation ID.** ADR-083026-1cb1 makes correlation
  ambient: one execution context holds the canonical ids, and the envelope's
  correlation vocabulary is closed. An extension identity cannot join that
  namespace, and stamped attribution leaves every canonical id untouched —
  it is provenance, carried beside the correlation fields.
- **Attribution is not a registry read path.** The payload is self-contained
  and format-versioned; decoding consults no store, no registry, and no
  installed extension, which is exactly the property that keeps historical
  evidence readable after the active version moves, is disabled, or is
  removed. Unknown format versions and corrupted payloads refuse loudly
  instead of guessing.
- **Attribution is not a secret carrier.** The field set is closed — there is
  no free-form mapping an extension could tuck credential material into — and
  the canonical envelope redacts the provenance fragment independently on the
  way in.

## Acceptance criteria

- [x] **AC-1**: An extension-mediated effect is attributed to the exact
      four-field identity — extension id, strict-semver version, publisher,
      and both package and manifest SHA-256 digests — keyed the same way as
      the install record the identity came from, and joined to the canonical
      caller scope (org/Workspace) rather than replacing it. A governed
      install's records, an adapter's declared identity on Invocation
      evidence and terminal events, and an activation's structured log fields
      all carry that identity; partial, malformed, or uninstalled identities
      are refused rather than guessed.
- [x] **AC-2**: The attribution evidence survives hops: the payload is plain
      JSON that round-trips through an asynchronous delegation's metadata and
      decodes equal on the other side; adapter-mediated calls that log through
      the gateway render the declared identity; a programmatically registered
      declaring adapter still leaves full attribution evidence; and an
      undeclared adapter's records claim no extension identity at all.
- [x] **AC-3**: No extension-defined universal correlation ID exists beside
      the canonical ones: the canonical execution-correlation namespace
      refuses an extension identity as a key, a stamped event keeps its
      canonical correlation fields and carries the extension only in
      `provenance`, and an undeclared binding emits no extension provenance.
- [x] **AC-4**: Historical evidence stays readable when the active installed
      version changes, is disabled, or is removed: a stored payload decodes
      with no registry, no store, and no extension present; unknown payload
      format versions refuse loudly; and decoding fails closed on corruption
      or a non-object payload instead of fabricating an attribution.
- [x] **AC-5**: Telemetry contains no extension secrets by default: the
      attribution field set is closed, an attribution built from manifest
      bytes containing secret-shaped fields carries none of them, and the
      canonical envelope redacts whatever a caller smuggles into the
      provenance fragment.
- [x] **AC-6**: The shipped reference extension proves the correlation end to
      end against a real out-of-tree package: the host bootstraps the shipped
      gallery adapter with the exact installed identity (manifest id, version,
      publisher, digests), one governed call runs under canonical
      Run/NodeRun/Attempt ids, the terminal audit event names the extension
      package beside — never inside — the canonical correlation fields, and
      the stored Invocation still decodes the exact package identity with the
      extension long since gone.
