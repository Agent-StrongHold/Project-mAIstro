---
name: repo-mine
description: Durable, crash-safe sweep of a large repo (or cross-repo comparison) using the mining-orchestrator + repo-scout agent pair. Partitions the target into haiku-sized slices, checkpoints every finding to docs/mining/ and commits after each slice so nothing is lost to crashes, stalls, or session limits; resumable at any point. Produces a ranked INVENTORY.md. Use for repo-scale audits, gap-mining a sibling codebase, or any search too big for one context. Args - source path/repo, optional diff target, optional question, e.g. /repo-mine ../stronghold vs packages/maistro-core
disable-model-invocation: false
---

The user wants a durable large-repo sweep. Arguments: $ARGUMENTS (source [vs target] [question]).

## What this skill does

Runs the two-tier durable mining harness proven on the stronghold→engine sweep of 2026-07-04
(35.5k LOC source scanned by 17 haiku slices with zero lost work across a session-limit crash):

- **`mining-orchestrator`** (Agent tool, subagent_type `mining-orchestrator`) partitions,
  launches, supervises, commits, consolidates.
- **`repo-scout`** (haiku) scans one slice under the crash-safe contract: resume-first,
  flush-per-file, heartbeat-per-file, one report file per scout.
- Shared checkpoint folder **`docs/mining/`** (README, INVENTORY.md, reports/, progress/),
  committed and pushed after every slice — survives container reclaim.

## Steps for the main agent

1. Parse $ARGUMENTS into: source scope, diff target (optional — absence means "inventory/audit"
   rather than gap-diff), and question. Ask via AskUserQuestion only if genuinely ambiguous.
2. Identify scope/deconfliction rules BEFORE launching: grep the target repo's ADRs for
   ownership splits (in this repo: ADR-019 canonical-source-split, ADR-035 catalog-ownership).
   Findings that contradict accepted decisions must be tagged "by-design, skip", not gaps.
3. Launch ONE `mining-orchestrator` agent with: source, target, question, checkpoint dir
   (`docs/mining/` on the current branch), scope rules, and batch size ≤ 8.
4. While it runs: if you see its heartbeats stop advancing and no completion arrives, resume it
   (SendMessage) or relaunch it — the checkpoint folder makes any restart lossless.
5. When it completes: read `docs/mining/INVENTORY.md` (NOT the raw reports) and relay the
   ranked findings. Confirm the folder is committed and pushed; commit it yourself if not.

## Invariants (do not violate)

- Nothing is held only in agent memory: every finding hits disk before the next file is read.
- Every checkpoint state change is committed to the remote branch promptly.
- Scouts/orchestrator never modify anything outside the checkpoint folder.
- Remediation (porting code, writing ADRs) is a separate follow-up phase fed by INVENTORY.md —
  never done by the scouts themselves.
