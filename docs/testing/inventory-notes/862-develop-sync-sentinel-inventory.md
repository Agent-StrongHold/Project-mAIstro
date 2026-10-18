---
inventory-delta:
  tests/: +1
---

# 862-develop-sync-sentinel-inventory

One inherited test, recorded after the develop sync (origin/develop at
`2f56be40a`) that this repair round performed. This branch added no test in
this step.

## What moved

`tests/security/test_sentinel_permission_table_armed.py` gained
`test_hive_preset_tracks_the_executable_registry`, which pins
`PERMISSION_PRESETS["hive_conductor_tools"]` to exactly the tools the
Conductor's `dispatch_tool` registry can execute. It arrived with develop's
`edb669149` / `bf8aa27f1` ("arm Sentinel permission tables on shipped Compose
profiles", EPIC M2-A #2156), which landed on develop without a covering
inventory note — the only `tests/` delta develop's notes claim in that range
is the #1881 pair's +19, which matches its two new files exactly. The merge
therefore imported a +1 collected delta that no existing note accounts for,
and this branch's own notes (`862-compose-resource-containment` +5,
`862-pressure-soak-driver` +5) were already exact, so the drift shows up here.

## Why a separate note

The movement is not #862 work; attributing it to an #862 note would misstate
what this issue changed. Recording the inherited delta under its own slug
keeps each change's number pointing at its own cause, and the note is
idempotent against later base moves: if develop records the same +1 under its
own slug, the next `--update` re-derives this note's delta from the actual
drift rather than accumulating.
