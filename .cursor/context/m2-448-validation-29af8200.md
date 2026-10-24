# M2 initiative (#448) validation record — head 29af8200e

Lane L448, job d8224712839b4068aaa30ffad8fb693c. Validation-only pass: no
production code changed. Evidence below is from reachable code at this exact
head; driver ran no deterministic checks (`checks: []` in the job manifest),
so every item here was executed in-lane.

## Verdict basis: NEEDS-DEEP-REVIEW

### Confirmed unmet — reopened #76 / Gate B (one sandbox authority)

1. Canonical ADR-093 wiring registers only bubblewrap + opt-in fake:
   `packages/maistro-core/src/maistro/sandbox/wiring.py:55-71` — the only
   registrations in `build_selector`; `sandbox/backends/` contains only
   `bubblewrap.py` and `fake.py` (no VM/container/gVisor tiers), while the
   policy ladder declares tiers above `DEV_ONLY`.
2. Production code-execution paths bypass the selector/policy authority:
   `grep -r build_selector --include=*.py packages/ | grep -v tests` yields
   only `cli/_sandbox.py:33` and `cli/_eval_workspace.py:659` (CLI-only).
   `tools/sandbox/docker.py`, `tools/sandbox/microvm.py`,
   `tools/sandbox/server.py`, and
   `maistro_bootstrap/builders/container_sandbox.py` import nothing from
   `maistro.sandbox` — the Protocol/selector does not govern them.

Gate B ("one canonical SandboxProtocol/selector governs the production
code-execution path") is therefore unmet at this head. Closing it is an
architecture-level epic (route docker/microvm/container_sandbox through the
selector + add satisfiable VM/container tiers), not a lane-local repair.

### Confirmed unmet — #1197 (bounded host output)

`grep -in 'cap|limit|bound|truncat|max' over output|stdout|stderr|log|capture`
across `tools/sandbox/docker.py` (219 lines), `tools/sandbox/microvm.py`
(147 lines), `builders/container_sandbox.py`: zero hits. No bound on captured
stdout/stderr in those production paths.

### Verified green (tree health, not gate closure)

- `uv run ruff check .` — pass.
- `uv run ruff format --check .` — 2881 files already formatted.
- `uv run pytest packages/maistro-core/tests/sandbox -x -q` — 113 passed,
  35 skipped (skips are real-backend tiers absent on this host).
- `uv run pytest packages/maistro-core/tests/security
  packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-bootstrap/tests/test_sandbox_preflight.py -q` —
  1397 passed, 24 skipped.

### Not adjudicated here (out of lane scope, needs own lanes)

- #1201 schedule ownership / actor provenance; #1202 full Agent-boundary
  scan/redaction pipeline (warden/sentinel/redact modules exist; end-to-end
  wiring unproven); #1204 quota snapshot replay; #1198 mount/TOCTOU
  completeness (hardening tests exist and pass; coverage sufficiency not
  audited); all enterprise-closeout children (#289/#325/#362-#379).
  No issue was closed or commented from this lane.
