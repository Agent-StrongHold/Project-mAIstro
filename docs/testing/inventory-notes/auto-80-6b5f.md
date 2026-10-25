---
inventory-delta:
  packages/maistro-rsi/tests: +8
---

# auto-80-6b5f — `packages/maistro-rsi/tests` +8 (#80 round 22, unstated-isolation fail-closed)

Branch `auto-80`, head `881fdad69d43d52fe5632c7925657a12f8afee93`, 2026-09-27.

The D-04 verifier finding this delta belongs to: the autonomous RSI surfaces
defaulted `--isolation` to `local`, so `python -m maistro_rsi run` executed
model-generated work through `LocalWorktreeSandbox` on the host by omission —
the bare-subprocess tier ADR-093 decision 5 forbids. An unstated isolation now
refuses at every entry (CLI dispatcher, `LocalRsiConfig` default `""`,
`make_builders_apply_patch`); a *stated* `local` proceeds as ADR-082926-a6ab's
operator choice, and the `container` tier refusal is unchanged.

Nine node IDs added, one replaced, all in
`test_autonomous_isolation_tier.py`:

- `TestCliRefusal::test_run_without_isolation_refuses_fail_closed` — replaces
  the removed `test_run_local_isolation_is_not_refused_by_the_tier_guard`'s
  unstated-argv shape: `run` with no `--isolation` exits 2 before the repo
  check, naming ADR-093 and `--isolation local`;
- `TestCliRefusal::test_evolve_without_isolation_refuses_fail_closed` — same
  gate on `evolve`;
- `TestCliRefusal::test_run_explicit_local_isolation_is_not_refused_by_the_tier_guard`
  — the old local test's intent, restated for the now-explicit choice: guard
  silent, run proceeds to its next gate;
- `TestLibraryRefusal::test_loop_unstated_isolation_refuses` — a programmatic
  `LocalRsiConfig` without isolation raises `ContainmentUnavailable` at
  `run()`;
- `TestLibraryRefusal::test_unstated_isolation_refuses_rather_than_degrading_to_the_host`
  — the guard's refusal text names the floor and the operator's ways out;
- `TestFactoryRefusal` (4) — the factory is the one place a sandbox tier is
  chosen: `isolation=""` refuses ("no isolation was chosen"), a name the loop
  cannot construct (`"locaal"`) refuses instead of falling into the host
  worktree branch, `container` refuses on the tier floor, explicit `local`
  builds.

No other suite moved. Existing tests that exercise the local path now state
`isolation="local"` explicitly (24 constructor sites, 4 override-dict
helpers, 4 factory calls, 4 CLI argv lists) — the tests' behavior under the
old default is unchanged; they simply make the choice the new contract
requires. Companion note: `l80-repair-round22.md`.
