---
inventory-delta:
  tests/: +16
---

# Develop-side absorption of the #562 quality-class suite (recorded 2026-09-02)

PR #800's merge (778a2121) landed the sixteen
`tests/test_autonomous_merge_quality_classes.py` node IDs without a
branch-owned `tests/` note, leaving develop@3d783e74 with an unrecorded
+16 drift (expected 3020, collected 3036). Push-event CI never surfaced it
because its combined-suite step fails earlier on the pre-existing
base==HEAD ratchet-behavior refusals; every PR that update-branched onto
3d783e74 inherited the red instead (first observed on PR #898's lane,
19:28Z). This note records the delta on develop so inherited checks
self-correct. Identified and disclosed by the #838 delivery lane.
