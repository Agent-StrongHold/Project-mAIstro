---
inventory-delta:
  tests/: +5
---

# #862 pressure soak driver

Added five root contract tests for `scripts/soak-compose-pressure.py`, the
executable memory/PID pressure case the release soak (#860) runs against the
resource containment policy (#862):

- the driver reads the shipped engine profile ceiling (memory, swap, PIDs,
  CPU) from `docker-compose.yml`;
- loading a ceiling fails closed when limits are missing, effectively
  unbounded, out of the gate's safety policy, or the service is absent;
- the generated `docker run` invocation replays the ceiling verbatim and
  places every flag (including `--restart`, `-d`, `--rm`) before the image so
  the daemon actually applies it, and fractional CPU quotas keep nano-CPU
  precision;
- the fork-count parser accepts real counts and rejects noise;
- the verdict logic distinguishes a proven containment run from failures
  (no OOM kill, no restart, fan-out reaching the attempt bound, host process
  leakage, ceiling not applied verbatim, daemon unresponsive, or a spawn
  count so low the ceiling was not the binding constraint).

The tests are daemon-free: they cover the driver's policy, argument
construction, parsing, and verdict logic. The live pressure run itself is
executed by the release soak against a real Docker/Podman daemon and records
its own JSON evidence via `--output`.
