---
id: SPEC-005
title: "Medley full — publish, versions, signed VC trust chain, dependency resolution"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-03-23
substrate:
  - maistro-engine#ADR-024
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-03-23
---

# SPEC-005: Medley full

See `blakematthews-dev/project_maistro` specs/tools/S-111-clawhub-full.md for full spec.

## Acceptance Criteria

- [ ] `medley publish` produces a signed publisher VC + uploads plugin tarball + updates publisher DID document
- [ ] Installed plugins pin to a semver range; `medley update` respects the range
- [ ] `depends_on` plugins auto-installed transitively; conflicts reported clearly
- [ ] Every install verifies the publisher VC against the DID document (signature + hash + revocation status)
- [ ] Unsigned plugin install blocked unless `--allow-unsigned` + admin signature
- [ ] Revocation re-check on each `medley install` / `medley update` / `medley trust` invocation is the default; opt-in daily background re-check (`medley.daily_revocation_check = true`) covers plugins not recently touched; detected revocations emit a `PLUGIN_VC_REVOKED` alert to the dashboard and block further use of the plugin pending operator review
- [ ] `medley info <name>` displays publisher DID, VC fingerprint, content hash, install date, version, trust tier
- [ ] Lockfile is operator-readable + version-controlled
