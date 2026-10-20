# Upgrade preflight

Before applying a host upgrade, evaluate the installed extensions against the
target release: which are compatible, which are deprecated, which need a
manifest migration, and which would block the upgrade. The preflight exists so
incompatibility is discovered **before** cutover, never after.

```
maistro extensions preflight ~/.maistro/extensions.db 2.0.0 \
    --contract-version 2.0.0 \
    --capability workspace.read --capability tool.invoke \
    --deprecated-capability 'memory.read=read workspace projections instead' \
    --removed-capability 'secrets.read=removed in contract 2.0.0' \
    --policy strict
```

## What it reads

Two inputs, both data:

1. **The installed lock state** — the durable install records (#952) in the
   SQLite database. For each extension, the latest install record is the
   installed version; its manifest snapshot carries the public contract
   metadata the evaluation reads (`contract` range, `capabilities`,
   `dependencies`). Registry or catalog churn cannot reach a report.
2. **The target release's public contract metadata**, supplied on the command
   line (or as a `TargetHostContract` in code): the target host version, the
   manifest-contract version it enforces, the capability vocabulary it
   supports, and which capability names are deprecated or removed.

The preflight imports nothing from the target release and nothing from any
extension — evaluating an upgrade never activates the new host version, and
the store is opened read-only.

## What it reports

One row per installed extension, with a total verdict:

| Verdict | Meaning |
|---------|---------|
| `compatible` | Validates against the target contract; nothing to do. |
| `deprecated` | Works, but declares a capability the target deprecates. The warning names the replacement. |
| `migration-required` | Works, but needs an operator action — typically a manifest contract range that spans more than one major (see the [manifest reference](manifest-reference.md#contract-versioning-and-deprecation) pin-one-major rule), or a dependency that itself needs migration. |
| `blocking` | Would not function on the target: contract range excludes the target contract version, a declared capability was removed (or is unknown to a declared vocabulary), a dependency is missing or out of range, or a dependency of its own is blocking. |

Blockers and warnings are separate sections, and each conflict message names
the exact contract or dependency conflict.

## Policy

- `--policy permissive` (default) — report blockers, exit 0. For review.
- `--policy strict` — exit non-zero while any **enabled** blocking extension
  remains. That exit is the upgrade gate: an upgrade flow must treat it as
  "cannot proceed".

`--enabled NAME` (repeatable) names the extensions the host currently has
enabled. Omit it to treat every installed extension as enabled — the
conservative default. A disabled extension is still reported, but cannot
block: an operator who disabled an extension is not told the upgrade is
impossible because of it.

## Reproducibility

`--json` prints the canonical report: sorted keys, no wall clock, one row per
installed extension. The same installed lock state evaluated against the same
target and policy produces byte-identical output — across repeated runs and
across fresh re-reads of the database — so a report made before an upgrade
window can be compared against one made during it.
