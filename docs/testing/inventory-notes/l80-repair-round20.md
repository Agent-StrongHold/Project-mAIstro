---
note: l80-repair-round20
issue: "#80"
head: 8f714f20d643e39c2b8d0eb78344a9112203e810
date: 2026-09-27
---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 round 20 — repair the rootless lane's runner-side bootstrap (XDG_RUNTIME_DIR + fail-loud readiness)

Prior finding at this head (`8f714f20d`): "no code defect found; repair action
is operational: obtain green remote CI." That was written when no remote run
existed at the head. One now does, and it falsifies the "no code defect" half:

## Remote evidence at `8f714f20d` (read-only `gh`, PR #1450, run 36336385671)

- `workflow-lint` ✓ — the round-19 SC2155/SC2046 repair holds remotely.
- `Build the real Builder sandbox image` ✓ and
  `Rootful daemon is refused (ADR-093 Decision 2 fail-closed proof)` ✓ —
  the fail-closed branch is proven on the runner's own rootful daemon.
- `Start a rootless Docker daemon for the conformance lane` ✗ after ~2m:
  the pinned bundle downloaded, `uidmap`/`slirp4netns` were already the
  newest version, `kernel.apparmor_restrict_unprivileged_userns=0` applied
  (all visible in the job log), `dockerd-rootless.sh` was launched — and then
  `docker info` failed 60 times over 120s and the step died on
  `grep -q rootless` with exit 1. **The step never printed `dockerd.log`**, so
  the remote failure mode was invisible: the two earlier "local-green vs
  remote-green" divergences in this lane were exactly this blindness repeated.
- `Run the real Builder sandbox conformance lane` and everything after it:
  never ran. `gates-ran`/integration-scope: downstream casualties.

## Repair (ci.yml, same step)

1. **`XDG_RUNTIME_DIR` is now created and owned by the runner user before
   `dockerd-rootless.sh` starts.** Hosted runners do not open a logind
   session for the runner user, so `/run/user/<uid>` is not guaranteed to
   exist; rootlesskit needs it to build its runtime directory. This is the
   leading suspect for the silent daemon death and is a documented
   rootless-Docker-on-CI requirement.
2. **The AppArmor knob is re-asserted inside this step**, hard (no `|| true`):
   the earlier bwrap provisioning sets it for its own kernel probes, but a
   step whose guarantee depends on another step's `|| true` surviving is not
   a guarantee.
3. **Prerequisites fail fast with the cause in the step name**: after the
   best-effort apt install, `command -v newuidmap slirp4netns` must succeed.
4. **Readiness failure dumps `tail -n 200 dockerd.log` behind a `::error::`
   annotation and exits 1** instead of a bare grep mismatch — if the daemon
   still fails remotely, the next round gets its evidence in the step log
   itself.

Local proof for the edited block: `bash -n` clean, `shellcheck -s bash` clean
on the extracted block, and the exact CI gate invocation
(`/tmp/actionlint -no-color -oneline -shellcheck /tmp/shellcheck-bin`,
actionlint 1.7.7 + shellcheck 0.10.0 — the pinned versions) exits 0 at this
head.

## Conformance evidence re-proven live at this head (round 20)

- Rootful daemon (`unix:///var/run/docker.sock`, no rootless marker):
  `test_sandbox_refuses_a_rootful_unmapped_daemon` PASSED; full bootstrap
  suite `247 passed, 17 skipped` (the 12+ escape tests skip, the refusal
  still runs — both halves of Decision 2 stay exercised).
- Rootless daemon (`unix:///run/user/1000/docker.sock`, SecurityOptions
  contain `rootless`, probe uid_map `0 1000 1 / 1 100000 65536`):
  the full production-class escape suite
  `packages/maistro-bootstrap/tests/test_container_sandbox.py`
  **16 passed, 1 skipped** (the skip is the refusal test — correctly inverted
  on a qualifying daemon).
- Hardening unit suite (no Docker): 24 passed. `packages/maistro-rsi/tests`:
  793 passed. `ruff check` / `ruff format --check`: clean.
- Gates: `check-vulture-baseline.py` 1403==1403 (no ledger change needed),
  `check-suite-inventory.py` ok, `check-ac-state.py` ok,
  `check-image-inventory.py` ok, `check-workflow-write-safety.py` ok,
  `check-build-context.py` ok, `check-shell-execution.py` ok.
  `check-gates-ran.py` needs the CI `--check-runs` payload and is not locally
  runnable; it has no local assertion to make.

## Residual

The one acceptance item this round cannot close from inside the worktree is
the remote-green run itself: I have no push or workflow-dispatch authority by
prohibition. The lane is now (a) designated, (b) locally proven on both
daemon branches at this head, (c) workflow-lint clean at the pinned tool
versions, and (d) instrumented to produce its own diagnostic log on the next
remote failure. If the next remote run still fails at `dockerd-rootless.sh`,
the dockerd.log tail in the step log is the input for round 21 — not another
provisioning guess.

Untracked scratch from the failed prior worker run (round 19's `agent_exit`
without a result record) is preserved, not committed: `.env.test` (a fake
`SECRET_TOKEN=...` fixture used by the scratch `verify_sandbox.py`) and
`verify_sandbox.py` (a manual probe duplicating what
`test_container_sandbox.py` already proves live). Neither belongs in the
tree: the first trips every secret-scanner pattern in
`check-build-context.py` for a token that is not real, the second has no
inventory entry and no test id.
