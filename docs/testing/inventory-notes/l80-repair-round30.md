---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 round 30 — repair: the conformance suite's own collection-time Docker probe was the remaining `test: failure` source

Branch `auto-80`, base head `54ce10e087e4460f36232fa01b38a8e3bdc256d9`, issue
#80, 2026-09-28. One file changed:
`packages/maistro-bootstrap/tests/test_container_sandbox.py` (test-only; no
production code, no node IDs added/removed — delta 0, inventory re-verified at
275).

## Evidence, not guesswork

Two independent, reproduced failure modes pointed at the module-level daemon
posture probe:

1. Job `1f507fa8e71d407e85bfd6b29873fe89` `check-3.log`: unhandled
   `subprocess.TimeoutExpired` from
   `docker run --rm --network=none maistro-builders:latest cat /proc/self/uid_map`
   (timeout 180) raised at **module import** (`_DAEMON_QUALIFIES = ...` line),
   erroring the entire pytest collection — exit 1, `test: failure`.
2. This worktree, same day: `docker version` and `docker image inspect` answer
   in milliseconds while `docker info --format '{{.SecurityOptions}}'` on the
   same shared daemon hangs past 20s. The daemon stalls per-code-path, so any
   unbounded docker call at import is a latent hang; the image-inspect probe
   previously had **no timeout at all**, and a hung import can kill the whole
   gate at job timeout.

A third, latent wrong-branch hazard: the boolean `_DAEMON_QUALIFIES` treated
"probe failed/timed out" the same as "identity map observed", so a stalled
probe on a boundary-providing daemon would skip the escape suite **and run the
refusal test against a sandbox that starts fine** — a flake converted into a
red DID-NOT-RAISE failure.

## Repair (fail-closed to skip, never fail-closed to error)

- `_docker_ready()`: `timeout=60` on the image inspect (previously unbounded)
  and `except (OSError, subprocess.SubprocessError) -> False`.
- `_daemon_provides_userns_boundary()` → `_daemon_uid_boundary() -> bool | None`:
  True = userns boundary proven via the production classifier
  (`_uid_map_maps_container_root_to_host_root`, unchanged); False = identity
  map positively observed; None = docker errored or probe timed out. Probe
  failure is no longer conflated with a proven identity map.
- Escape suite runs only on `True`; `test_sandbox_refuses_a_rootful_unmapped_daemon`
  runs only on `False` (positive identity-map evidence). `None` skips both.
- Healthy-daemon behavior is unchanged: same probes, same classifier, same
  branch split, same 19 node IDs in this module.

## Validation executed at `54ce10e0` + this change

- `uv run ruff check .` / `uv run ruff format --check .`: pass.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests`
  → `ok ... 275`; `--suite packages/maistro-rsi/tests` → ok. No delta needed.
- Named `test` gate (the exact driver check-3 argv, job `6debbe12…`):
  **199 passed, 19 skipped** in 31.85s.
- Live daemon-posture proof on this host's rootful un-remapped daemon:
  `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -q`
  → **1 passed** (`test_sandbox_refuses_a_rootful_unmapped_daemon`, the real
  production sandbox refusing with `ADR-093 Decision 2`), 18 skipped by
  posture, module completes in ~5s including the live probe.
- Vulture per-identity ledger:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → rc 0, 1402/1402 banked (no ledger amendment; no src changes).

## Acceptance criteria mapping (issue #80)

- Filesystem/process/namespace-kernel/network/device/host-socket/credential/
  privilege escape coverage: `test_path_escape_blocked`,
  `test_process_namespace_devices_and_host_socket_are_not_reachable`,
  `test_nested_user_namespace_does_not_reopen_the_host`,
  `test_agent_commands_cannot_reach_any_network_by_default`,
  `test_no_block_devices_reachable`, `test_no_host_unix_sockets_visible`,
  `test_no_host_listening_ports_visible`,
  `test_container_environment_is_credential_default_deny`,
  `test_agent_execs_run_as_unprivileged_user` — all in
  `test_container_sandbox.py` against the production `ContainerBuilderSandbox`;
  kernel-tier coverage in `packages/maistro-core/tests/sandbox/test_escape_conformance.py`
  (Bubblewrap) and `packages/maistro-rsi/tests/test_autonomous_isolation_tier.py`.
- Network/credential default-deny: egress probe asserts `NetworkMode==none` on
  the live container plus 7-path connect + DNS denial; env test proves host
  credentials and Docker client proxy config do not cross.
- Seed hygiene: `test_seed_leaves_ambient_credentials_on_the_host` and
  `test_seed_refuses_replaced_index_paths` prove `.env`/`.git`/unrelated host
  secrets never enter the container (also covered daemon-independent in
  `test_container_sandbox_hardening.py`).
- Not container root: `test_agent_execs_run_as_unprivileged_user` + the
  ADR-093 Decision 2 uid_map launch gate (`_verify_userns_boundary`,
  hardening suite + `test_container_user_namespace_maps_container_uids_off_the_host`).
- Read-only default / minimized writable scope:
  `test_rootfs_and_writable_scope_are_explicit` (live `ReadonlyRootfs`, full
  mount-table enumeration).
- Timeout/kill/cleanup/exhaustion: `test_timeout_kills_the_command_and_detached_descendants`,
  `test_context_cleanup_removes_the_container`,
  `test_memory_exhaustion_is_contained_by_the_container_limit`.
- CI conformance lane: `.github/workflows/ci.yml` builds the real image from
  `Dockerfile.sandbox` (no repo context), proves the rootful refusal, then
  provisions a rootless dockerd and runs the full escape suite on it.
- SECURITY.md cites this evidence (limitation #8 narrative, suites named).
- Same production class: every conformance test instantiates
  `ContainerBuilderSandbox` from `maistro_bootstrap.builders.container_sandbox`
  and asserts against its live container (`_require_cid()` + `docker inspect`).

## Residual risks

- A stalled daemon now costs at most ~240s of import probing before skipping
  (bounded, green); coverage for that run is restored by the dedicated
  conformance lane, which provisions its own daemons and hard-fails with
  evidence if they never become ready.
- The hosted `test` job also runs `packages/maistro-evolve/tests/benchmarks`
  (swebench), which pulls `python:3.12-slim` from Docker Hub at runtime; that
  lane's DNS/pull flakiness (round-29 evidence, run 36440932829) is outside
  this lane's diff and untouched.
