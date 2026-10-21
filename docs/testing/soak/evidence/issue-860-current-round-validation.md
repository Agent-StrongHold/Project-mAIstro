# Issue #860 current-round validation

- Reviewed issue acceptance against `docs/testing/soak/m3a-load-profile.md`,
  the soak driver, promotion gates, and accepted ADRs
  `ADR-081626-f383` (Attempt execution lease/fencing) and
  `ADR-082126-f69c` (recurrence produces canonical Runs).
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **84 passed**.
- `uv run python scripts/soak/run_soak.py --help`: passed; confirms this
  driver explicitly cannot sign promotion evidence (`exact_rc_artifact` always
  fails for the host-process preflight).
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`:
  passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`:
  passed.
- The assigned job directory contained no `check-*.log` files to inspect.

## Acceptance disposition

**Not promotion-ready.** Existing machine evidence
`m3a-round109-shakedown.json` is from a different commit, reports a 420.05 s
sustain against the 14,400 s minimum, and identifies a host-uvicorn preflight,
not the exact RC artifact. The documented profile still excludes concurrent
user/Workspace population, graph/node fan-out and successful tool/model/Canvas
work; its schedule race cancels the admitted probe Run without physical
execution. Existing gate tests verify these shortcomings fail closed; they do
not demonstrate the required four-hour production Compose soak or physical
Attempt fencing/recovery during active work. No new tests were added and no
inventory delta is required.

No product or evidence repair can honestly satisfy the missing production
execution requirements in this validation-only environment. Do not treat this
note or prior host-process evidence as release approval; run a new soak against
an immutable, identified RC image/configuration and resolve each failed
acceptance before promotion.
