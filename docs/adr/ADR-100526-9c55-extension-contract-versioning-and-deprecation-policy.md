---
id: ADR-100526-9c55
title: "Extension contract versioning, feature negotiation, and deprecation policy are host-enforced metadata contracts"
repo: maistro-engine
kind: adr
status: Implemented
created: 2026-10-05
accepted: 2026-10-05
implemented: 2026-10-05
history:
  - status: Proposed
    date: 2026-10-05
  - status: Accepted
    date: 2026-10-05
  - status: Implemented
    date: 2026-10-05
substrate:
  - maistro-engine#ADR-073126-c4e1
  - maistro-engine#ADR-076
implements: []
related:
  - maistro-engine#ADR-032
  - maistro-engine#ADR-093
supersedes: []
blocks: []
blocked-by: []
contracts: [behavioral]
tests:
  - packages/maistro-core/tests/extensions/test_compat.py
  - packages/maistro-core/tests/extensions/test_cli_compat.py
ac-modules:
  AC-1: maistro.extensions.compat
  AC-2: maistro.extensions.compat
  AC-3: maistro.extensions.compat
  AC-4: maistro.extensions.compat
  AC-5: maistro.extensions.compat
source:
  - packages/maistro-core/src/maistro/extensions/compat.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-100526-9c55: Extension contract versioning, feature negotiation, and deprecation policy are host-enforced metadata contracts

**Status:** Implemented

## Context

Issue #955 (M9-C1, epic #940) asks how MAIstro and extensions negotiate
supported public contracts over time "without relying on private
implementation compatibility." The pieces that make this decidable already
exist on adjacent lanes: M9-A1 defines the extension manifest (parsed strictly,
never importing extension code), and M9-B1 (#952) durably records installs
with publisher and trust evidence. What was missing is the *policy*: which
contract versions mean what, how required and optional features negotiate
against a host, when unsupported combinations are refused and with what
information, and how deprecations carry their removal commitments.

Two versioning decisions already in force constrain the answer.
[ADR-073126-c4e1](ADR-073126-c4e1-release-and-versioning-process.md) pins
*published package* versions to a single lockstep axis sourced from the root
`VERSION` file — but a lockstep application version says nothing about whether
a manifest written last year still means what its author meant, and letting
application patch versions decide compatibility would make every patch
release a compatibility event. [ADR-076](ADR-076-http-api-versioning.md)
resolved the same tension for the HTTP surface with an independently
versioned, negotiated contract; extensions need the equivalent for their
manifest/SDK contract, decided by the host from metadata, before any
extension code is imported.

## Decision

The extension contract versions on its own semantic axis, and the host
enforces the whole policy from metadata alone, in
`maistro.extensions.compat`:

1. **The contract version is a literal host policy constant** (`CONTRACT_VERSION`),
   never derived from the package version, the root `VERSION` file, or any
   installed distribution. Major bumps mark breaking changes to the contract
   vocabulary; minor bumps add features backward-compatibly; patch bumps
   change nothing. This is the ADR-073126-c4e1 reconciliation: lockstep governs
   published artifacts, not contract semantics — exactly the split ADR-076
   made for the HTTP surface.
2. **Compatibility is negotiated, never assumed.** An extension declares a
   contract *range* (`>=X,<X+1` capping convention over strict
   `MAJOR.MINOR.PATCH`, the monorepo's existing convention) plus
   *required* and *optional* feature names. The host declares the contract
   versions it supports and the features it implements. `negotiate()` is a
   pure function over the two metadata structures.
3. **The contract gate short-circuits.** A range that excludes the host's
   contract version is an `incompatible` verdict with one actionable reason
   naming the declared range, the host's version, the supported majors, and
   which boundary was missed — a contract-major break ("a breaking boundary
   no host patch can bridge") or a same-major floor the manifest requires.
   The feature declarations are not interpreted further: they were written
   against a contract this host does not implement, and evaluating them
   against this host's vocabulary would be fiction.
4. **Required features gate activation; optional features degrade
   explicitly.** A required feature the host will not provide (unknown,
   removed, or introduced by a contract newer than the host speaks — the
   minor-version axis) is an `incompatible` verdict with a per-feature
   actionable reason. An optional feature miss is a recorded *degradation*:
   named in the report and **absent from `supported_features`**, the set a
   runtime grants from. Pretending support is structurally impossible; a
   degraded verdict is the explicit, machine-readable record that the
   extension must run without the feature.
5. **Deprecations are machine-readable with enforced support windows.** A
   feature moves through the closed status set `supported → deprecated →
   removed`. A `deprecated` row *must* declare a `removal_target` and
   migration prose, and the removal target must be a future contract **major**
   (removal is a breaking change; breaking changes land only at major
   boundaries) — so the deprecation window is enforced by construction, not
   promised in prose. A `removed` row stays in the host table with its
   `removed_in` version and migration path, so a manifest still naming the
   feature is told when it went away and where to go, not just "unknown
   feature." Nothing is deprecated today; the machinery is table-driven, so
   the first real deprecation adds a row, not code.
6. **Failure is actionable.** `ensure_compatible()` raises
   `IncompatibleContract` carrying exactly the report's reasons;
   `CompatibilityReport.to_dict()` is the JSON-safe projection for tooling.
   Feature-gate failures accumulate within one negotiation, so an author
   fixes everything in one pass.
7. **Compatibility never depends on the application version or private
   module paths.** `HostContractMetadata` has no application-version field;
   two hosts implementing the same contract decide identically regardless of
   which application release carries them. The extension metadata model has
   no module-path/entrypoint field at all, and report text names versions and
   feature names only — an import path cannot enter the decision.

The host exposes its side read-only: `HostContractMetadata.current()` (the
policy constants as metadata) and the `maistro extensions compat` preflight
command, which negotiates a metadata JSON file against this host — exit 0 for
compatible/degraded, exit 1 for incompatible — and `--json` for the
machine-readable report. Both are metadata-only by construction: negotiation
completes with Python's import machinery disabled (test-enforced).

## Consequences

- **Contract-version bumps are rare and loud.** Additive evolution ships as
  new features (rows), not new contracts; the major increments only for a
  breaking change to the vocabulary itself, and the same change must extend
  `SUPPORTED_CONTRACT_MAJORS` policy deliberately.
- **The feature vocabulary is host-owned.** A name the host has never heard
  of is a negotiation outcome (incompatible when required, degraded when
  optional), not a parser crash — a newer SDK may declare features an older
  host does not define. Feature names are lowercase slugs; dotted or
  underscored names would blur into module paths, the channel this policy
  closes.
- **The deprecation ledger is auditable.** Because every deprecated row
  carries a removal major and migration prose, "what are we removing and
  when" is queryable from host metadata, and M9-C3's upgrade preflight can
  report installed extensions against it without new machinery.
- **Host-side range/semver parsing is deliberately tiny and duplicate of the
  SDK lane's grammar, on purpose.** The author-facing SDK (M9-A1) validates
  the same syntax at authoring time; the host re-derives the decision from
  metadata rather than trusting a validator it cannot see. Convergence into
  one shared parser is follow-up work once both lanes are co-installed.

## Evidence

- Negotiation and policy behavior:
  `packages/maistro-core/tests/extensions/test_compat.py` — including the
  structural proofs: negotiation completes with `builtins.__import__` banned
  (AC-1), degraded features are absent from the granted set (AC-2), major and
  same-major misses produce boundary-naming reasons (AC-3), deprecated rows
  require future-major removal targets and migration prose (AC-4), and no
  host-metadata field can carry an application version or module path (AC-5).
- Host read surface: `packages/maistro-core/tests/extensions/test_cli_compat.py`
  (`maistro extensions compat`, machine-readable `--json`, non-zero exit on
  incompatible).
- Mutation checks (each reverts before landing): muting the contract gate
  fails the major/window tests; degrading unknown *required* features fails
  six activation-gate tests; dropping the future-major removal-target rule
  fails the support-window test.
