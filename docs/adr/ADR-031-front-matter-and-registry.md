---
id: ADR-031
title: Front-Matter and Registry Conventions
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate: [maistro-engine#ADR-030]
implements: []
related:
  - maistro-engine#ADR-000
  - maistro-engine#ADR-032
  - maistro-engine#ADR-033
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-031: Front-Matter and Registry Conventions

## Context

Across the four repos, ~270 ADR/spec artifacts (~160 unique after de-duplicating the `AgentTuring` ↔ `stronghold` mirror) need machine-checkable cross-references. Today there are no required fields, no link validator, and the canonical inventory (`maistro-engine/docs/INVENTORY-ADRS-SPECS.md`) is hand-maintained. The existing ADR-000 template is unstructured and has no front-matter.

## Decision

### 1. Front-matter schema (required on every ADR and spec)

```yaml
---
# Identity
id: ADR-NNN | SPEC-NNN
title: <human-readable title>
repo: maistro-engine | Project_mAIstro | AgentTuring | stronghold
kind: adr | spec

# Lifecycle — status vocabulary and transitions are governed by ADR-097
status: Proposed | Accepted | Implemented | Superseded | ...  # full per-kind list in ADR-097
created: YYYY-MM-DD
accepted: YYYY-MM-DD       # optional until status >= Accepted
implemented: YYYY-MM-DD    # optional until status == Implemented

# Relationships (each is a list of <repo>#<id>)
substrate: []     # engine ADRs/specs this rests on
implements: []    # product specs this implements
related: []       # see-also
supersedes: []    # ADRs/specs replaced by this one
blocks: []        # ADRs/specs that cannot proceed until this is accepted
blocked-by: []    # ADRs/specs that must accept first

# Contracts and tests (see ADR-032)
contracts: [boundary | behavioral | cross-service]
tests:
  - path/to/test_file.py::test_func

# Acceptance-criteria waiver (added by #164; specs only)
non-measurable: <why this spec declares no acceptance criteria>   # optional

# Classification
# (Evolve/Crypto/Connectivity/Ability/Identity added by ADR-098.)
layer: Foundation | Orchestration | Agents | Tools | Memory | Observability | Reliability | Governance | UserClient | Evolve | Crypto | Connectivity | Ability | Identity
owners:
  - '@github-handle'
---
```

All fields are required. Empty lists (`[]`) are valid for relationship and contracts/tests fields.

`non-measurable` is the one optional field, and it exists because an empty list
was *too* valid. `implements: []` and an absent acceptance-criteria section were
both clean under this contract, so a spec implementing nothing and a spec owing
criteria were indistinguishable from ones that had been examined and found not
to need either. The waiver is that distinction: a reason, reviewed in the diff
that adds it, which `scripts/check-ac-state.py` accepts in place of criteria.
The schema refuses an empty or token reason, and refuses the field on an ADR —
a decision is owed an implementing spec, not criteria of its own.

### 2. Status lifecycle

The status vocabulary and the per-kind transition machine are defined by
`engine#ADR-097` and enforced by `tools/lint_lifecycle.py`; this ADR only
requires that every document carry a `status` from that machine.

This section originally defined its own smaller machine, including `Blocked`
and `Abandoned`. Those two states appeared in zero documents across the
system and in no transition table once ADR-097 landed — vocabulary the
schema could parse but never reach — and were removed from
`maistro_registry.schema.Status` rather than kept as dead members
(`blocked-by:` still exists as a *relationship*; it never needed a status).
A deliberately-not-taken decision is `Denied` (pre-acceptance) or
`Deprecated`/`Superseded` (post-acceptance) in the ADR-097 machine.

- `Superseded` requires a populated `supersedes:` field on the successor.

### 3. Numbering

- All ADRs use `<repo>#ADR-NNN`
- All specs use `<repo>#SPEC-NNN`
- Existing schemes (`ADR-K8S-NNN` in stronghold, `S-NNN` in `Project_mAIstro`, `epic-N/story-N` in `AgentTuring`) migrate **on touch** — any artifact edited gets renumbered in the same PR.
- Each repo carries a `RENUMBERED.md` table at its root mapping old → new IDs. Cross-refs in old PRs and issues remain searchable via this table.

### 4. Cross-references

Front-matter relationship fields are the **source of truth**. A CI job in `maistro-engine` (the registry generator) reads front-matter across all four repos via the GitHub API and:

1. Validates that every `<repo>#<id>` resolves to an existing artifact
2. Validates DAG-ness on `supersedes:` and `blocks:` (no cycles)
3. Generates `maistro-engine/registry/registry.json` (canonical) and `registry.md` (human-readable)
4. Fails CI if dangling refs exist (after the rollout window — see §6)

### 5. Inventory becomes derived

`maistro-engine/docs/INVENTORY-ADRS-SPECS.md` is regenerated from the registry. Hand-edits to that file fail CI. The inventory format may evolve; the front-matter does not.

### 6. Rollout

- **Day 0** — schema published; registry CI runs in **warn-only** mode. Every PR touching ADRs/specs must migrate the touched files.
- **Day 30** — CI flips to **hard fail** on schema violations and dangling refs. From this point, an unmigrated artifact blocks any PR that touches it.
- During the warn window, repos with high spec counts (`Project_mAIstro` 91, `AgentTuring` ~92) run scripted bulk migrations as separate PRs.

### 7. ADR-000 template

The ADR-000 template is regenerated to match this schema. The regeneration is a follow-up PR within the warn-only window.

## Consequences

- The inventory becomes derived, not hand-maintained. Drift between front-matter and inventory is a CI failure.
- `substrate:` and `implements:` fields make the four-repo dependency graph visible. Memory/catalog drift becomes detectable as multiple ADRs claiming the same `layer:` without `substrate:` linkage (see ADR-034, ADR-035).
- The 30-day window is tight but bounded. The cost of a longer window is sustained drift and confusion about which scheme is canonical.
- Tooling becomes an engine concern: the validator, link-checker, and registry generator live in `maistro-engine` and run from there against all four repos.

## Out of scope

- Spec body conventions (sections, headings) beyond front-matter — covered by ADR-032 for AC, otherwise per-product.
- Per-spec tests-manifest format — left to product specs (e.g., `AgentTuring`'s `epic-N/tests-manifest.md`).
- Specific YAML linter / CI runner choice — implementation detail of the registry CI.
