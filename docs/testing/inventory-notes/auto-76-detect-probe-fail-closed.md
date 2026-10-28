---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-76-detect-probe-fail-closed

CI-repair round for #76: the Coverage gate (publish-set floor + diff coverage)
failed on the diff-coverage leg —

```
FAIL: 1 file(s) below the diff-coverage floor
  packages/maistro-core/src/maistro/sandbox/detect.py: 88.9% of 18 changed
  lines (need 90%); uncovered 198, 217
```

Both uncovered statements are fail-closed returns in the Kata-aware `_probe_vm`
(detect.py): line 198 — KVM usable, no `kata-runtime` on PATH, but a non-Kata
VMM (firecracker/cloud-hypervisor/qemu) *is* present, so the probe must refuse
the tier and name the missing supported deployment profile rather than claim
hardware virtualization it cannot launch; line 217 — `kata-runtime` and
`docker` both on PATH but `docker info` exits non-zero, so the daemon survey
failed and the tier reads absent-with-reason. The neighbors (probe timeout →
line 215, daemon without Kata runtimes → line 220) were already tested; these
two branches were the only changed lines nothing executed.

+2 node IDs in `packages/maistro-core/tests`
(`test_real_backend.py::test_the_vm_probe_refuses_a_non_kata_vmm_without_the_supported_profile`
and `...::test_the_vm_probe_refuses_a_docker_daemon_that_is_down`), both
following the file's existing `_probe_vm` pattern (monkeypatched `_kvm_usable`
/ `_which` / `subprocess.run`). No production code moved; every other gate
input is unchanged.

Local evidence at this revision: `coverage run --branch --source=
packages/maistro-core/src/maistro` over the sandbox suite leaves detect.py
missing only line 80; the audit arithmetic over the 18 changed lines vs
develop (`10f872fa7`) computes 100% line coverage (floor 90) and 8/8 branch
arcs (floor 80).

## Named-gate proof at `9ef2204c` (2026-10-26, this repair round)

The Coverage gate (publish-set floor + diff coverage) was re-executed locally
with CI's exact commands against the current develop base `407b181c`:

- Unit producer replayed verbatim (REQUIRE_AUTH=false, MAISTRO_DRY_RUN=1,
  `uv sync --locked --all-extras`, five per-package `coverage run --append
  --branch` invocations): core 17164 passed / 1215 skipped / 7 xfailed
  (752s); canvas 583 passed / 75 skipped; evolve 1000 passed / 6 skipped;
  bootstrap 276 passed / 1 skipped; rsi 1795 passed / 1 skipped / 1 failed
  (environment finding below).
- `uv run python scripts/check-diff-coverage.py coverage.xml --base
  407b181c46b4f532dbad4b64d0c2195e7a814f75` → "ok: every measured file this
  change touches is at or above 90% lines / 80% branch arcs" (29 changed
  source files measured, 26 test files exempt). detect.py — the file the
  failing CI job 121678193248 named — is inside that measured set.
- `uv run coverage report --fail-under=87` → exit 0, TOTAL 93% (93,191
  statements). This is a conservative lower bound: it runs on the unit
  producer's data only (no MinIO/PostgreSQL producers on this host), and
  those producers append hits inside the same `--source` trees without
  changing the denominator.
- Vulture ledger with CI's exact argv
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) → exit 0; 1248 reviewed identities, no
  unbanked rows; no ledger amendment needed this round.

Environment finding (not a branch regression): the operator-built
`maistro-builders:latest` image on this host (created 2026-10-26) lacks a
`git` binary, so the docker-gated
`packages/maistro-rsi/tests/test_contained_fitness.py::
test_real_evaluation_scores_every_signal_inside_one_container` — which CI
*skips* (no such image on runners; `coverage (no services)` is green at this
head) — runs here and fails when the fail-first probe's in-container `git
rev-parse` exits 127 (`maistro_rsi.fail_first._resolve_evidence_shas` then
correctly refuses to collect evidence). The probe path is untouched by this
branch; the image is operator infrastructure and was not rebuilt here.
Rebuild the image with git (the sandbox's own `diff()` already requires it)
before using that host for contained-fitness evidence.
