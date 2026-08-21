---
id: SPEC-178
title: Legacy snapshot directories — retention and removal
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-05-13
accepted: 2026-06-02
implemented: 2026-06-02
substrate:
  - maistro-engine#ADR-002
implements: []
related:
  - maistro-engine#SPEC-175
  - maistro-engine#SPEC-177
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Accepted
    date: 2026-06-02
  - status: AC Defined
    date: 2026-06-02
---

# SPEC-178: Legacy snapshot retention and removal

## Context

The repo keeps **large, non-canonical trees** under **`potential-dead-code/`** only. That includes **`code-worth-implementing-from-*`** workspace snapshots (legacy hyperagent bundle, Project_mAIstro gateway snapshot, Conductor, HiveConductor, and full-site duplicates), plus **`legacy-maistro-site/`** and **`superseded-by-SPEC-175/`**. **Nothing** named `code-worth-implementing-from-*` lives at the **repository root** anymore; if those paths reappear at root, treat them as mistakes (see root `.gitignore`).

These directories are **not** on `PYTHONPATH`. They exist for **provenance and porting** until behavior is captured in **numbered specs** (`docs/specs/SPEC-*.md`) and/or shipped under **`packages/`**.

Goal: once a row’s “Superseded when” condition is met, remove the matching paths from version control in a normal commit so blobs are **not re-added**, without losing intent already recorded in specs and ADRs.

## Decision

1. **Single source of truth for “what to build”** is **`docs/specs/SPEC-*.md`** plus ADRs — not the snapshot folders.
2. **Snapshot folders are disposable** after their superseding spec reaches **Implemented** (or **Abandoned** with rationale).
3. **Removal is a normal commit** that deletes paths from the tree (preferred). Keeping files only locally is optional and not required by this spec.

## Directory matrix

| Path | Purpose | Superseded when |
|------|---------|-----------------|
| `potential-dead-code/superseded-by-SPEC-175/` | Archived `ProgressReporter` | **Now** — behavior in `maistro.tasks.progress_webhook` ([SPEC-175](./SPEC-175-task-progress-webhook.md)). Safe to delete after confirming no doc links require the verbatim file. |
| `potential-dead-code/code-worth-implementing-from-legacy/` | Curated hyperagent port bundle | [SPEC-177](./SPEC-177-hyperagent-graph-execution.md) **Implemented**. |
| `potential-dead-code/code-worth-implementing-from-legacy-site-complete/` | Full `cp -R` duplicate of legacy site | Same as SPEC-177 + team sign-off; prefer delete before or with `potential-dead-code/legacy-maistro-site/`. |
| `potential-dead-code/legacy-maistro-site/` | Full pre-monorepo `src/maistro` | SPEC-177 **Implemented** + grep shows no remaining port references. |
| `potential-dead-code/code-worth-implementing-from-Conductor/` · `potential-dead-code/code-worth-implementing-from-HiveConductor/` | Optional sibling snapshots | Prefer live sibling repos; if re-vendored at **repo root**, root `.gitignore` blocks accidental commit — prefer documented clone or submodule instead. |
| `potential-dead-code/code-worth-implementing-from-Project-mAIstro/` | Frozen gateway / conductor snapshot (TS + related trees) | **Not** removed from disk — archived here. For active product work use a sibling checkout of `Project_mAIstro`; do not treat this tree as the live contract. Safe to delete from git only when no open porting work references it (same hygiene as other rows). |
| **Repo root `.gitignore` patterns** | Legacy names `code-worth-implementing-from-*` at **root** | Prevents re-committing old snapshot layout; canonical retained copies live only under `potential-dead-code/`. |

## Git hygiene (remove from tracking)

From repo root, after backup if needed:

```bash
# Example: remove implemented reference bundles in one commit (paths under potential-dead-code/)
git rm -r potential-dead-code/code-worth-implementing-from-legacy \
           potential-dead-code/code-worth-implementing-from-legacy-site-complete \
           potential-dead-code/superseded-by-SPEC-175
# Optional later, when SPEC-177 is done:
# git rm -r potential-dead-code/legacy-maistro-site
```

Commit with a message that cites **SPEC-177** / **SPEC-175** / **SPEC-178** so history explains why the blobs left.

**Policy:** Do not re-add multi-megabyte `cp -R` snapshots without an ADR; prefer submodule, documented clone path, or CI artifact.

## Acceptance Criteria

1. This matrix is referenced from [AGENTS.md](../../AGENTS.md) or root [README.md](../../README.md) “legacy” pointer (one sentence + link).
2. When a row’s “Superseded when” condition is met, the matching paths are removed in a dedicated PR and `git grep` for the old path returns no hits (or only intentional changelog mentions).
