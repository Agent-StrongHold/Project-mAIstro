# Salvage archive: unlanded #777 Design Studio draft (job 6c8c2bc4)

**This code is NOT shipped.** Nothing here is imported by any package; it lives
outside `packages/*/src` so it is invisible to vulture, pytest, mypy, and every
build. It is preserved for provenance only.

## Provenance

Lane L777 (issue #777, worktree `auto-777`). Repair job
`6c8c2bc477a345e0a5fc104c2b515c3b` (model `openrouter/cohere/north-mini-code:free`)
died mid-write on a provider error
(`Provider finish_reason: error`) while streaming these files into
`packages/maistro-design/src/maistro_design/studio/`, leaving them untracked.
The next round (job `b4a729eb45a44d81b8a2f838469cf26e`) preserved them here
rather than discarding them. A byte-identical verbatim copy of the files as
found (plus `__pycache__`) exists outside the repo at
`~/Git/wt/incoming-777-salvage/studio-src-verbatim/` with a unified diff at
`~/Git/wt/incoming-777-salvage.patch`.

The only changes made to the in-tree copy are mechanical gate repairs, applied
to the relocated copy only:

- `ruff check --fix` (import sorting, `List`/`Optional` modernization, removal
  of unused imports) and `ruff format`
- `design_engine.py`: added the missing `from datetime import datetime` (the
  file referenced `datetime.now()` at line 127 with no import — the truncated
  stream cut the import off; F821)
- `design_engine.py`: `skill_slug`/`system_slug` loop variables renamed to
  `_skill_slug`/`_system_slug` (B007, value unused in loop body)

## Why the draft was not adopted into production src

The draft is a placeholder skeleton that cannot truthfully implement #777 at
this head, and committing it under `packages/*/src` would have failed the lane
gates and violated the issue's stop condition. Evidence:

1. **It did not even import.** `core.py` did
   `from maistro_design.types import DesignSystem, Persona`; `Persona` does not
   exist in `maistro_design/types.py` (the canonical `Persona` is
   `packages/maistro-core/src/maistro/personas/model.py:26`), so importing
   `maistro_design.studio` raised `ImportError`. `design_engine.py:127`
   referenced an unimported `datetime` (`NameError` at runtime). 36 ruff
   errors total.
2. **It fabricates canonical state the issue forbids it from owning.** The stop
   condition says: do not create a Design-Studio-private Agent runtime, Goal
   owner, reconciliation loop, memory system, or Persona variant.
   - `core.py:_read_goal_state` returned a `state: "placeholder"` dict and
     subclassed the campaigns' read-only `GoalReader` protocol
     (`maistro_core/workspaces/campaigns/policy.py:54`) with a fake reader —
     a Design-Studio-private Goal authority with invented state.
   - `brief.py:commit_to_goal` fabricated a new canonical Goal revision
     (`str(int(goal_revision) + 1)`) with no Goal store behind it — a private
     Goal revision writer.
   - `execution.py:reclaim_delegated_subgoal` fabricated ownership history
     (`"original_owner": "workspace_agent"`), exactly the "fabricating new
     unrelated history" the acceptance criteria exclude.
   - `execution.py:ControlManager.cancel_branch` flipped the whole project's
     mode to `"cancelled"` instead of cancelling one branch while unrelated
     branches continue, and `resume_project` reset mode to `"direct"`,
     discarding the delegated mode it resumed from.
3. **All state was in-memory dicts** — no durability, so the
   refresh/reconnect acceptance criterion (restore actual ownership, locks,
   guidance, execution) was unimplementable as written.
4. **It duplicates canonical types.** `studio/types.py` redefined
   `DesignSystem` (canonical: `maistro_design/types.py`) and a private
   `Persona` dataclass (canonical: `maistro_core/personas/model.py`).

## Why #777 itself remains unimplementable at this head

Fresh audit at head `6109e49729fa3dcaeab1f9ad991879736e8dbd92`
(`origin/develop` == `9fe61e216`, no new upstream commits): every canonical
owner #777 must consume is still unlanded — see
`docs/testing/inventory-notes/777-design-studio-mixed-control-verify.md` for
the per-criterion audit. This archive is kept so the next implementer round
can reuse the draft's shape (CreativeBrief projection, ControlManager,
StudioToolSelector) once #804/#805/#806, #458 behavior, #774, #775 and #776
land, without re-deriving it — and without inheriting its fabrication bugs.
