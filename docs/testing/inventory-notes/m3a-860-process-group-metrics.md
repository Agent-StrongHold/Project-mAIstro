---
inventory-delta:
  tests/: +6
---

# #860 — measure the application process group, not only uv

Six regressions in `tests/test_soak_promotion_gates.py` cover a live `uv run`
wrapper/application-child topology (32 MiB child allocation and 16 descriptors
must appear in `sample_once`), four process-group cases (complete, unreadable
member, missing RSS, empty group), and continued sampling after wrapper exit.
The group cases exclude unrelated processes. Missing measurements remain null,
not a misleading zero or partial healthy aggregate (ADR-083026-a91e).

These are sampler regressions, not an application soak or production leak proof.
The exact-RC and duration gates remain unchanged. Historical raw evidence must
not be rewritten to imply its old wrapper-only samples measured the application.
