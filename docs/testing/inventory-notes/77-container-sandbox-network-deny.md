---
inventory-delta:
  packages/maistro-bootstrap/tests: +8
---

# 77-container-sandbox-network-deny

Eight tests, all in the container-sandbox subset of `maistro-bootstrap`.
Nothing removed or renamed; the two pre-existing Docker-gated isolation tests
and the four #305 argv-status tests pass unchanged.

`test_container_sandbox.py` (+3, now 5 total). The three new ones are
Docker-gated against the *actual* `ContainerBuilderSandbox` backend (the issue
explicitly rejects evidence from a fake or selector backend), so they skip
wherever `docker` or the `maistro-builders` image is absent and run for real
where it exists:

- `test_agent_commands_cannot_reach_any_network_by_default` — the #77
  regression itself: an agent-issued command (a probe script written through
  the sandbox's own `write_file`/`run_command`) attempts public IPv4, public
  IPv6, DNS resolution, the link-local cloud-metadata address and RFC1918
  private ranges, and every one must be denied; the live container's
  `NetworkMode` is also asserted to be `none` directly off `docker inspect`.
- `test_agent_execs_run_unprivileged_user` — `id -u` is the sandbox's non-root
  uid, and the agent fails to write `/etc` or `chown` the workspace (it is not
  root and holds no capabilities).
- `test_seed_leaves_ambient_credentials_on_the_host` — `.env`, root `.pem`,
  `.git/config` (credential helpers, remote tokens) and `.git/hooks` never
  reach the container, while the working tree and nested ordinary files do,
  and `git diff` still works off the seeded refs/objects.

`test_container_sandbox_hardening.py` (+5, new). Docker-free argv-shape tests
so the create-time configuration is locked on hosts/CI without Docker:
`--network=none` on the `docker run` and never touched afterwards; `--user`
pinned to the unprivileged uid with the capability floor intact; exactly one
root exec in the sandbox's lifetime (the pre-seed workspace `chown`) and every
agent-reachable exec carrying the explicit `-u`/HOME prefix; the seed built
host-side through the full `_SEED_EXCLUDES` denylist and extracted as the
agent uid with `--no-same-owner`; and the denylist's load-bearing entries
locked as policy.

Pre-existing failures in this environment (identical on a clean tree, not
touched by this change): `test_cli.py`/`test_cli_answers.py` collection
(missing optional deps), 5 in `test_sandbox_preflight.py`, 1 in
`test_credentials.py`, 1 in `maistro-rsi`'s
`test_no_host_shell_execution.py`.
