---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 verifier round 17 (independent review) — Decision-2 enforcement head `4e20c0151`

First independent verification at the head that carries the ADR-093 Decision 2
enforcement (`4e20c0151f91847850ae58ab78109b172490580f`, "#80: enforce ADR-093
Decision 2 rootless/userns boundary in the Builder sandbox"). Round 16
(`04c679246`) verified the develop-sync merge *before* that commit existed.
The driver supplied **no `check-*.log` files** for this job, so every check
below was executed by this reviewer at exactly `4e20c0151` on a clean tree;
the only delta this record adds is itself (docs-only).

## Both Decision-2 branches re-executed live at this head (not assumed)

The round-16/15 records could only exercise the refusal branch: the shared
daemon (`/var/run/docker.sock`, Docker 29.7.2, `SecurityOptions` without
`rootless`, `rootdir=/var/lib/docker` — the exact D-04 regression posture) is
rootful, so the escape suite skips there. This round also reproduced the
qualifying branch, exactly as the CI lane does:

- Rootful branch:
  `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  …/test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon
  -v` → **1 passed** — the production class refused to start on the real
  rootful un-remapped daemon (`RuntimeError` matching "ADR-093 Decision 2")
  and left no container behind.
- Rootless branch: a user-local rootless daemon was already active at
  `unix:///run/user/1000/docker.sock` (the same shape the CI lane builds with
  `dockerd-rootless-setuptool.sh install --force`); the sandbox image was
  seeded into it via `docker save | docker load` (image id `205c40a9f0b3…`,
  byte-identical to the rootful daemon's), then
  `DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py -v` →
  **12 passed, 1 skipped** (only the refusal test skips — correct: this daemon
  qualifies). This is the first live run of the full escape suite — network
  deny, seed hygiene, env credential default-deny, read-only scope, namespace/
  device/socket, capability/privilege, timeout kill of detached descendants,
  cleanup, memory containment, and the new
  `test_container_user_namespace_maps_container_uids_off_the_host` — on a
  daemon that actually admits the sandbox.

## Re-executed at this head

- `uv run pytest packages/maistro-bootstrap/tests -q` → **247 passed,
  13 skipped** (12 daemon-gated escape tests skip on the default rootful
  daemon + 1 qualifying-daemon-gated refusal test; 247+13 = the 260 the
  enforcing commit recorded). Hardening/argv subset
  (`test_container_sandbox_hardening.py` +
  `test_container_sandbox_argv_status.py`) → **28 passed**.
- `uv run pytest packages/maistro-rsi/tests -q` → **793 passed**.
- `uv run ruff check packages/maistro-bootstrap packages/maistro-rsi` → all
  checks passed; `ruff format --check` on the three #80 Python surfaces →
  already formatted.
- Vulture ledger, CI argv form (`uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, as invoked
  at `quality.yml:837-841` and `vulture-ratchet.yml:81-85`) → **exit 0**
  (1403 == 1403, `unclassified: 0`, base `88408c9e0418`, candidate
  `4e20c0151f91`).
- `scripts/check-build-context.py` → exit 0 (both ignore files deny all 27
  secret patterns; the CI image build uses the tests-only context).
- `scripts/check-doc-links.py` → exit 0.
- `scripts/check-workflow-write-safety.py` → exit 0 (23 workflows).
- `scripts/check-suite-inventory.py` → exit 0 (14 suites match).

## Remote CI (read-only `gh` queries; no mutations)

At develop-sync merge head `d8c0d950` (the ancestor this commit sits on):
workflows `quality`, `Vulture Ratchet`, `Formal Conformance`, `security`,
`Gate C`, `Cage Guard`, `DevSkim`, `Registry CI` → **completed/success**
(round 14's "Formal Conformance IN_PROGRESS" finding is resolved); ci.yml run
`36323545035` → every job success, including `test` (the job carrying the
sandbox conformance lane) and `workflow-lint`. The enforcing commit
`4e20c0151` itself is local-only (push is prohibited for this lane), so
GitHub-side execution of *that exact SHA* remains UNVERIFIED by policy; every
command its lane runs was proven green locally at that exact SHA (above),
including both daemon branches.

## Acceptance re-derivation (spot-read at this head)

- Privilege/namespace kernel boundary: `_verify_userns_boundary` reads
  `/proc/self/uid_map` through the unprivileged agent exec *before* the
  harness lookup, the one-shot chown and the seed (ordering pinned by
  `test_entry_probes_the_container_user_namespace_before_any_root_work`);
  identity/unreadable maps fail closed with cleanup; real uid_map shapes
  pinned by `test_uid_map_identity_detection`. Live-proven both branches.
- Non-root: `--user 65532:65532` on create and on every exec;
  `test_agent_execs_run_as_unprivileged_user` (uid pinned, `/etc` write and
  `chown -R 0:0 /workspace` refused) passed live; the only root exec is the
  pre-seed empty-workspace `chown` (`test_the_only_root_exec_is_the_pre_seed_chown`).
- Network default-deny: `--network=none` asserted on the live container config
  plus per-host egress probes (v4/v6/link-local/RFC1918 + DNS) with
  "was not probed" guards — passed live on the rootless daemon.
- Credential default-deny & seed hygiene: `.env`/`.env.*`/`.envrc` indexed
  under a split index, untracked `unrelated-host-secret.txt`, `server.pem`,
  `secrets/`, nested `.git`, submodule gitlink contents — all absent inside;
  `env` shows only HOME + blank proxies. Passed live.
- Writable scope: `ReadonlyRootfs=true`, `/proc/mounts` enumeration refusing
  any rw mount outside {/tmp, /workspace} incl. pinned `/dev/shm`,
  `/dev/mqueue` — passed live.
- Timeout/kill/cleanup/exhaustion: detached-session kill, context cleanup
  (container removed), 3 GiB allocation contained, seed-failure cleanup at
  every transfer stage — all green.
- Production parity: the conformance module imports `ContainerBuilderSandbox`
  + `DEFAULT_IMAGE` from the production module; production callers
  (`local_loop.py:804-806`, `contained_validation.py:73-80`) use the same
  class; CI builds the same image from a tests-only context.
- SECURITY.md (`:326-342`) and `docs/security/SANDBOX-SUPPORT-MATRIX.md`
  (`:166-185`) cite the enforced boundary and both CI branches.
