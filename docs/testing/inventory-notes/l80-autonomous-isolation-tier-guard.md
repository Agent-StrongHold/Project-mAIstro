---
inventory-delta:
  packages/maistro-rsi/tests: +6
---

# Autonomous isolation tier guard (#80 repair round 4)

The 2026-08-31 D-04 reopening evidence for #80 included a verifier finding
that `python -m maistro_rsi run/evolve --isolation container` exposed the
Tier-3 `ContainerBuilderSandbox` to *autonomous* multi-cycle RSI with no
execution-mode or tier guard anywhere on the path, while ADR-093 decision 6
floors unattended execution at a Tier-2 user-space kernel and decision 5 says
full-auto is blocked on a Tier-3-only host.

`test_autonomous_isolation_tier.py` (6 tests) pins the refusal added in this
round at both entries the finding named:

- the CLI dispatcher (`maistro_rsi/__main__.py::_refuse_unattendable_isolation`,
  called first in `_run` and `_evolve` — before the repo check, so nothing
  starts): `run`/`evolve` with `--isolation container` exit 2 naming ADR-093
  and the enforced floor; `--isolation local` is untouched by this guard;
- the library boundary (`maistro_rsi/local_loop.py::LocalRsiLoop._require_autonomous_isolation_tier`,
  first call in `run()`): a programmatic `LocalRsiConfig(isolation="container")`
  raises `ContainmentUnavailable`, because the config is a public constructor
  that can bypass the CLI. The local loop keeps running.

The rule is data-driven from `maistro.sandbox.policy`
(`autonomous_isolation_refusal` compares the backend's tier with
`MODE_FLOORS[ExecutionMode.AUTONOMOUS]` via `tier_satisfies`), and the
`TestPolicyLinkage` test pins that linkage both ways: the refusal exists
because the canonical policy says Tier 3 does not satisfy the autonomous
floor, and unstated/local vocabulary is not the guard's question.

Ran live: `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py`
= 6 passed; adjacent pins unaffected (`test_no_host_shell_execution.py`,
`test_contained_validation.py`, `test_run_model_arguments.py` = 48 passed;
`test_local_loop.py`, `test_cli.py` = 41 passed).
