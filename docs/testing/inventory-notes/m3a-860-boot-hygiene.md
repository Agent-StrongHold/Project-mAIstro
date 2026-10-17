---
inventory-delta:
  tests/: +4
---

# #860 — soak boot-hygiene regression coverage

The 2026-10-06 repair round lost a soak attempt to an incident chain inside
`scripts/soak/run_soak.py`: a relative `--out-dir` was passed to
`docker run -v` as a bind source (rejected), the LB-boot failure path raised
without killing the two replicas it had started, and the retry silently
adopted those orphans (`boot completed in 0.0s`) under a `--fresh-db` schema
reset — contaminating every count in that run's evidence
(12×500 exactly-once probe, 1943×502, admission ratio 0.0).

`tests/test_soak_promotion_gates.py` adds four root-suite nodes pinning the
repairs:

- `resolve_out_dir` normalizes `--out-dir` to an absolute path before any
  process boots (docker bind sources must be absolute);
- `ensure_replica_ports_free` refuses to boot while a previous run's replica
  still serves on 18201/18202;
- `kill_replicas_and_collect_orphans` kills every booted replica group and
  reports ports still serving;
- `boot_stack`'s LB-failure path kills both replicas before raising
  (discriminated: the pre-fix module leaks both, raising with zero kills).
