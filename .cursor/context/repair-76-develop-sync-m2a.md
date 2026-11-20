# Issue #76 round: develop-sync conflict resolution (M2-A) + named CI-gate repair (head f26c8a974)

Round scope: resolve the preserved develop-sync merge conflict (MERGE_HEAD=5056cf069, "M2-A —
Harden governed tool execution"), then prove the two merge-queue gate failures locally.

## Merge resolution (commit f26c8a974, parent1=61cae1eb9 branch, parent2=5056cf069 develop)

Develop M2-A removed the model-authored shell-string seam (`BuilderSandbox.run_command(cmd)`
→ argv-only `run_argv`) from the protocol, `LocalWorktreeSandbox`, and the (old docker-era)
`ContainerBuilderSandbox`, and rewired `agent_loop.py` to validated argv dispatch. The branch
(#76) had independently rewritten `ContainerBuilderSandbox` onto the canonical selector
(`maistro.sandbox`), keeping the string seam. Resolution kept BOTH intents:

- `container_sandbox.py`: develop's removal wins — the merged `agent_loop.py` dispatches the
  `run_command` tool via `_run_command_argv` + `sandbox.run_argv`, so the adapter's `sh -c`
  seam had no caller left. Branch's only delta there was a comment reword (moot once removed).
- `test_container_sandbox.py`: branch structure kept (Kata gating, stub-backed adapter
  contract, lifecycle/failure-path parity classes); develop's seam rename applied to the
  surviving tests (`run_argv(["python", "probe.py"])`, exec-order assertion updated).
- `test_container_sandbox_hardening.py`: branch's adapter-contract rewrite kept; develop's
  two `run_command("ls")`→`run_argv(["ls"])` edits applied to the surviving exec call.
- `test_agent_loop_run_tests_args.py`: fake sandbox's vestigial `run_command` guard dropped
  (protocol no longer declares it).

Ledger integrity (AGENTS.md row-loss rule): `git diff --numstat HEAD^1/HEAD^2 HEAD -- quality/`
shows only rows for identities the merged code no longer contains (branch-era banked vulture
rows for the removed seams). CI-exact vulture gate passes on the merged head: base 5056cf069,
1249 reviewed → 1247 findings, 0 unbanked.

## Gate evidence (all executed this round on f26c8a974)

- The two named merge-queue failures:
  - **hive-conductor-compose-durability**: `scripts/verify-compose-durability.sh` →
    **PASSED, 34 checks 0 failed** (create→write→recreate down/up+rebuild→read→backup→restore).
    `packages/hive-conductor` is byte-identical to base 5056cf069 (`git diff --stat` empty),
    so the prior red cannot be produced by current branch content.
  - **Coverage gate**: diff half reproduced with CI's producer invocations (core/canvas/
    evolve/rsi/bootstrap `coverage run --branch`, combine, xml) →
    `check-diff-coverage.py coverage.xml --base 5056cf069` → **exit 0** (every measured changed
    file ≥90% lines / ≥80% branches; changed production modules aggregate 95% over 4176 stmts).
    The 87% publish-set floor consumes archive/postgres producers (DB services) not run here —
    residual below.
- Suites: bootstrap 276p/1s; core 16937p/1213s/7xf; canvas 581p/75s; evolve 1000p/6s;
  rsi 1795p/1f/1s; hive-conductor backend 4126p/29s.
- Gates: ruff check ✓, ruff format --check (3551 files) ✓, mypy (AGENTS-exact, 949 files) ✓,
  vulture CI-exact ✓, radon ✓, reachability+dispositions+provenance ✓, direct-effects ✓,
  model-egress ✓, ratchet-provenance ✓, suite-inventory (21 suites match; no delta) ✓,
  convergence-matrix ✓, backlog-consistency ✓.

## Residuals

- `test_contained_fitness.py::test_real_evaluation_scores_every_signal_inside_one_container`
  fails identically on base 5056cf069 (verified in a throwaway base worktree: same missing
  `pytest -q -p no:cacheprovider` rerun in the probe statuses). Docker-gated; no CI job builds
  `maistro-builders:latest`, so CI never executes it. Pre-existing develop debt, not a #76
  regression; left untouched to keep the repair focused.
- The 87% publish-set floor was not re-measured end-to-end (needs archive+postgres producers).
  Analytic: only core+bootstrap production changed vs base; those measure 95% on the changed
  modules with ~1.2pt documented floor headroom.
- Kata-VM-gated tests skip on this host (no Kata profile); stub-backed contract classes carry
  the adapter contract everywhere (branch design).
