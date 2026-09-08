---
name: repo-mine
description: Durable, crash-safe sweep of a large repo (or cross-repo comparison) using general-purpose Task subagents with a checkpoint contract. Partitions the target into small slices, checkpoints every finding to docs/mining/ and commits after each slice so nothing is lost to crashes, stalls, or session limits; resumable at any point. Produces a ranked INVENTORY.md. Use for repo-scale audits, gap-mining a sibling codebase, or any search too big for one context. Args - source path/repo, optional diff target, optional question, e.g. /repo-mine ../stronghold vs packages/maistro-core
disable-model-invocation: false
---

The user wants a durable large-repo sweep. Arguments: $ARGUMENTS (source [vs target] [question]).

## What this skill does

A durable two-tier mining harness — one supervising agent that partitions and consolidates,
plus one general-purpose subagent per slice, checkpointing to disk after every file:

- **This repo defines no custom subagent types** (there is no `.claude/agents/` directory and no
  agent-type registry anywhere in the tree — verified). The real delegation surface is the one
  documented in `AGENTS.md` ("Subagent context") and `.cursor/context/README.md`: launch
  **general-purpose subagents via the Task tool** and **paste the full contract into the Task
  prompt** — subagents start with a clean context and see nothing from this session.
- The supervisor (you) partitions, launches, supervises, commits, consolidates.
- Each slice agent scans one slice under the crash-safe contract below: resume-first,
  flush-per-file, heartbeat-per-file, one report file per slice.
- Shared checkpoint folder **`docs/mining/`** (create it if absent: README, INVENTORY.md,
  reports/, progress/), committed and pushed after every slice — survives container reclaim.

## Prerequisites — fail loudly, never silently substitute

Before any work starts, verify the delegation surface. If you cannot launch subagents with a
fresh context in this harness, **stop and report** "repo-mine needs the Task subagent surface;
unavailable here" — do not silently re-role a chat agent or claim the sweep ran. There are no
specialized miner agents to fall back on: the mining discipline lives entirely in the prompt
contract below, so any agent you launch must be given it verbatim.

## Steps for the main agent

1. Parse $ARGUMENTS into: source scope, diff target (optional — absence means "inventory/audit"
   rather than gap-diff), and question. Ask the user directly, in chat, only if genuinely ambiguous.
2. Identify scope/deconfliction rules BEFORE launching: grep the target repo's ADRs for
   ownership splits (in this repo: `docs/adr/ADR-019-canonical-source-split.md`,
   `docs/adr/ADR-035-catalog-ownership-split.md`). Findings that contradict accepted decisions must
   be tagged "by-design, skip", not gaps.
3. Partition the source into slices small enough for one subagent context (≤ 8 files per batch
   is a good ceiling). Write the partition to `docs/mining/progress/` before launching anything.
4. Launch ONE general-purpose subagent per slice via the Task tool. Paste into each Task prompt:
   - the slice's file list (paths, not prose),
   - the question and diff target,
   - the checkpoint contract (next bullet) and its slice's report path
     (`docs/mining/reports/<slice>.md`) and heartbeat path (`docs/mining/progress/<slice>.md`),
   - the scope rules from step 2,
   - the invariant that it writes ONLY inside `docs/mining/`.
5. While slices run: watch the heartbeats in `docs/mining/progress/`. If a heartbeat stalls and
   no completion arrives, relaunch that slice — the checkpoint files make any restart lossless;
   the relaunched prompt resumes from the last flushed file.
6. When slices complete: read `docs/mining/INVENTORY.md` (NOT the raw reports) and relay the
   ranked findings. Confirm the folder is committed and pushed; commit it yourself if not.

## The checkpoint contract (paste verbatim into every slice Task prompt)

- Nothing is held only in agent memory: every finding is written to the slice report and flushed
  to disk before the next file is read.
- Append one heartbeat line (timestamp + file just completed) to the slice's progress file after
  every file scanned.
- On (re)start, read your progress file first and resume at the first unrecorded file — never
  redo completed files, never skip ahead of a gap.

## Invariants (do not violate)

- Nothing is held only in agent memory: every finding hits disk before the next file is read.
- Every checkpoint state change is committed to the remote branch promptly.
- Slice agents never modify anything outside `docs/mining/`.
- Remediation (porting code, writing ADRs) is a separate follow-up phase fed by INVENTORY.md —
  never done by the slice agents themselves.
