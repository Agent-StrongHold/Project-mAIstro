---
inventory-delta:
  packages/maistro-core/tests: +0
---

# auto-76-kata-conformance-shapes

The extension sandbox conformance lane (issue #76's acceptance: conformance
against real supported isolation backends) now runs against the Kata VM tier
on hosts that evidence it, and five of its assertions encoded bwrap's
mechanisms rather than the profile's contracts. Measured live on the Kata
backend and rewritten per-backend without weakening the bwrap evidence
(bwrap-only host simulated by registering only bubblewrap; all original
bwrap assertions re-verified):

- rlimits readback: Kata enforces PIDs/file-size as rlimits and CPU as the
  profile's CPU-seconds budget exactly, but memory is the VM budget
  (RLIMIT_AS reads RLIM_INFINITY — the hog test proves enforcement live),
  so RLIMIT_AS==256MB is now asserted only for the bwrap mechanism.
- memory hog: under Kata the kernel SIGKILLs (137, empty streams) instead of
  Python raising MemoryError; both are the ceiling stopping the workload.
- host paths: probe a freshly written host-only file instead of
  /etc/hostname — a VM brings its own rootfs where fixed host filenames can
  exist for unrelated reasons.
- workspace writes and the RLIMIT_FSIZE dd target address the sandbox's own
  ephemeral workdir per backend layout (bwrap /work, Kata /workspace);
  writing to a nonexistent path proved nothing about the ceiling.

Same 10 tests, 0 count delta. All 10 pass against live Kata and the bwrap
branches pass against a bwrap-only selector on the same host.
