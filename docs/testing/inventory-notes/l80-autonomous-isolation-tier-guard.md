---
inventory-delta:
  packages/maistro-rsi/tests: +7
---

# Autonomous isolation tier guard (#80 repair rounds 4-5)

The 2026-08-31 D-04 reopening evidence for #80 included a verifier finding
that `python -m maistro_rsi run/evolve --isolation container` exposed the
Tier-3 `ContainerBuilderSandbox` to *autonomous* multi-cycle RSI with no
execution-mode or tier guard anywhere on the path, while ADR-093 decision 6
floors unattended execution at a Tier-2 user-space kernel and decision 5 says
full-auto is blocked on a Tier-3-only host.

`test_autonomous_isolation_tier.py` (7 tests) pins the refusal at both entries
the finding named:

- the CLI dispatcher (`maistro_rsi/__main__.py::_refuse_unattendable_isolation`,
  called first in `_run` and `_evolve` — before the repo check, so nothing
  starts): `run`/`evolve` with `--isolation container` exit 2 naming ADR-093
  and the enforced floor; `--isolation local` is untouched by this guard;
- the library boundary (`maistro_rsi/local_loop.py::LocalRsiLoop._require_autonomous_isolation_tier`,
  first call in `run()`): a programmatic `LocalRsiConfig(isolation="container")`
  raises `ContainmentUnavailable`, because the config is a public constructor
  that can bypass the CLI. The local loop keeps running.

## Round 5: the guard stopped importing `maistro.sandbox.policy`

Round 4 drove the comparison from `maistro.sandbox.policy`
(`MODE_FLOORS[ExecutionMode.AUTONOMOUS]` via `tier_satisfies`). That import
regressed the promotion-surface ratchet: any `maistro.sandbox.*` import first
executes `maistro/sandbox/__init__.py`, which imports the execution fence and
credential boundary and, through them, ~220 maistro-core modules that are
neither protected by `maistro_rsi/sensitive_paths.py` nor baselined in
`quality/promotion-surface-baseline.json` — so
`scripts/check-promotion-surface-provenance.py` failed with "134 unprotected
module(s) in closure" against the trusted base (the GitHub
exact-debt-ledger job's red run).

Round 5 moves the two ADR-093 facts the guard needs into
`maistro_rsi/isolation_floor.py` (the tier ladder order and the autonomous
floor), inside the containment surface the `maistro_rsi/` pattern already
protects. Parity is enforced rather than hoped for: the seventh test,
`TestMirrorParity::test_mirror_is_the_canonical_policy`, imports both the
mirror and the canonical `maistro.sandbox.policy` and refuses any
disagreement — over the floor value, the ladder membership, and every
`tier_satisfies` comparison. Tests sit outside the promotion closure, so
they may import the canonical module; the loop cannot. A canonical ladder
change therefore fails this suite until the mirror follows it deliberately.

Ran live: `uv run pytest packages/maistro-rsi/tests` = 786 passed;
`scripts/check-promotion-surface.py` = "promotion surface: ok" (24 tolerated,
worktree mode); `RATCHET_BASE_REV=ca4caec7d… check-promotion-surface-provenance.py`
= "OK: 171 promotion-path module(s), no candidate-approved tolerance
expansion" (24 -> 24); `RATCHET_BASE_REV=ca4caec7d… check-ratchet-provenance.py`
= OK (37 consumers, delegated gates green).
