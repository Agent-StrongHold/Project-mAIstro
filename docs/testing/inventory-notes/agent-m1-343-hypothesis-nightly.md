---
inventory-delta:
  formal/: +1
  tests/: +1
---

# M1 #343 Hypothesis nightly wiring evidence

This change adds one formal-suite test that asserts the active Hypothesis profile matches pytest nightly mode, plus one root regression that invokes the formal test under `--nightly` with a non-default example count so CI proves the flag changes live Hypothesis settings.
