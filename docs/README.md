# Documentation map

**Start here** for planning and architecture; use the registry CLI for ADR/spec validation.

## Authority hierarchy

When documents disagree, resolve in this order:

1. **[ROADMAP.md](../ROADMAP.md)** — release horizons and v1.0 contract
2. **[BACKLOG.md](../BACKLOG.md)** — item-level work (`engine-NNN`, `conductor-NNN`, …)
3. **[architecture/WORKSPACE-CUTOVER-PLAN.md](architecture/WORKSPACE-CUTOVER-PLAN.md)** — Workspaces replaces legacy Conductor UI
4. **Accepted ADRs** in [adr/](adr/) — architectural decisions (front matter is canonical)
5. **SPECs with AC Defined** in [specs/](specs/) — implementation contracts
6. **[quality-gates.md](quality-gates.md)** + **[architecture/CONVERGENCE-MATRIX.md](architecture/CONVERGENCE-MATRIX.md)** — what CI enforces

Historical snapshots ([DECISION-BACKLOG.md](adr/DECISION-BACKLOG.md), [testing/inventory-notes/](testing/inventory-notes/)) are audit trails, not current truth.

## Folder guide

| Folder | Files | Purpose |
|--------|------:|---------|
| [adr/](adr/) | ~206 | Architecture Decision Records + [ADR-INDEX.md](adr/ADR-INDEX.md) |
| [specs/](specs/) | ~216 | Engine design specs + [README.md](specs/README.md) |
| [architecture/](architecture/) | 12 | Convergence matrix, feature-parity matrix, cutover plan, foreign-harness nodes, persistence/ontology contracts |
| [ci/](ci/) | 11 | Branch protection, merge queue, autonomous merges, ratchets |
| [install/](install/) | 17 | Bootstrap, Copier answers, deployment topology |
| [product/](product/) | 4 | Terminology, deployment stance, Design Studio |
| [security/](security/) | 7 | Identity/sandbox matrices, rendering hardening, DAG-shape admission |
| [testing/](testing/) | ~760 | Suite inventory + per-change `inventory-notes/` (CI ratchet evidence) |
| [extensions/](extensions/) | 5 | Extension SDK boundary: authoring guide, manifest reference, lifecycle, capabilities |
| [persistence/](persistence/) | 1 | Durable vs ephemeral container state |
| [research/](research/) | 32 | M8 research program ([README](research/README.md), charter + note index) — research notes, not governance |
| [exploratory-sessions/](exploratory-sessions/) | 3 | Manual probing session logs |

Root guides: [WAYS-OF-WORKING.md](WAYS-OF-WORKING.md), [quality-gates.md](quality-gates.md), [EXPLORATORY-TESTING.md](EXPLORATORY-TESTING.md).

## Product naming

**Workspaces** is the v1.0 product surface in `packages/hive-conductor`. **Hive Conductor** remains the internal name for the UI/BFF layer; see [product/TERMINOLOGY.md](product/TERMINOLOGY.md).

## Validation commands

```bash
uv run python scripts/check-backlog-consistency.py
uv run python scripts/check-adr-index.py          # index ↔ ADR front matter
uv run python -m maistro_registry.cli lint .
uv run python scripts/check-convergence-matrix.py
```

## Ephemeral vs durable docs

- **Durable:** ADRs, SPECs, architecture/, ci/, product/, root guides
- **Ephemeral (CI-owned):** `testing/inventory-notes/` — one note per suite-count delta; do not hand-edit for navigation
- **Removed:** `docs/analysis/` — content merged into [architecture/CONVERGENCE-MATRIX.md](architecture/CONVERGENCE-MATRIX.md), [ROADMAP.md](../ROADMAP.md), and git history
