# L80 round 26 — independent verifier re-proof at head ff19533d

Branch `auto-80`, head `ff19533d2b89cda6e030a6a1f44de81fb7ad183a` (round-25
lane repair), issue #80, 2026-09-27. Read-only verify round plus this note;
no source or test changes, inventory delta +0.

## Remote conformance lane: still red, new root cause captured

PR #1450 at this head, CI run `36351155187`, job `108709967297` (`test`),
concluded `failure`; `gates-ran` context PENDING at refresh time. Step
outcomes: step 7 (image build) ok, step 8 (rootful refusal proof) ok,
**step 9 "Start a rootless Docker daemon" ok for the first time** — the
round-25 firewall-plane fix (`--iptables=false --ip6tables=false
--userland-proxy=false --bridge=none`) unblocked provisioning — but
**step 10 "Load the Builder sandbox image into the rootless daemon"
failed with exit 126** and step 11 ("Run the real Builder sandbox
conformance lane") was **skipped**. Ninth consecutive red CI run of this
lane; the escape suite still has not executed remotely at any head.

Failure log line (fetched via `gh run view --job 108709967297 --log-failed`
after run completion):

    docker: Error response from daemon: Could not check if docker-default
    AppArmor profile was loaded: open
    /sys/kernel/security/apparmor/profiles: permission denied
    ##[error]Process completed with exit code 126.

`docker load` into the lane daemon succeeded ("Loaded image:
maistro-builders:latest"); the `memory.max` enforcement-probe container
failed at create: on the Ubuntu 24.04 hosted runner the kernel exposes
AppArmor but the rootless userns cannot read securityfs profiles, so moby
errors instead of treating AppArmor as absent. Locally (WSL, securityfs
not mounted) the same probe passes — which is why rounds 19–25 stayed
green locally. Repair belongs in lane provisioning (make the daemon see a
usable-or-absent AppArmor, e.g. mask `/sys/kernel/security` in the
daemon's mount namespace before `dockerd-rootless.sh`), not in the
sandbox contract; the escape suite would hit the same create-time error
on the runner the moment step 10 passes, so this is the only remaining
lane blocker. SECURITY.md:343-354 and
docs/security/SANDBOX-SUPPORT-MATRIX.md describe the lane design
accurately, but note the present-tense "the CI conformance lane runs both
branches" remains evidence-pending remotely: at this head only the
refusal branch has executed on CI.

## Local re-proof by this verifier at this exact head

Daemon replica of the round-25 recipe started from scratch
(`/tmp/l80v-rootless/docker.sock`; rootless SecurityOptions, vfs,
iptables/ip6tables/userland-proxy/bridge off, moby 29.7.2; the pinned
29.8.1 extras / static 28.5.2 matrix was proven in rounds 24–25 and not
repeated):

- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -v`
  with `DOCKER_HOST` pointed at the lane daemon = **16 passed, 1 skipped**
  (skip = inverted rootful-refusal test). Escape surfaces executed live:
  fs escape, path escape, network default-deny, unprivileged exec uid,
  seed hygiene (.env/.git/host secrets), credential-env default-deny,
  read-only rootfs + `/proc/mounts` write-scope, pid/ns/device/host-socket,
  timeout kill incl. detached descendants, cleanup, memory-limit
  containment, uid_map off-host mapping, nested-userns, block devices,
  host unix sockets, host ports.
- Step 10 verbatim locally: `docker save | docker load` ok;
  `memory.max=67108864` under the 64m probe (Linger=yes on this host).
- `test_sandbox_refuses_a_rootful_unmapped_daemon` against the rootful
  `/var/run/docker.sock` daemon = **1 passed**.
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py`
  = **26 passed**.
- Driver gates this round: lock/ruff/format green; 193 passed/16 skipped
  (check-3), bootstrap inventory 266 (check-4), rsi inventory 801
  (check-5).

## Process checks

- PR #1450 body: "Refs #80" only — no fixes/closes/resolves keywords;
  grep over `0c8370a8..ff19533d` subjects+bodies finds none.
- Salvage block from the round-25 handoff: resolved — the round-25 writer
  committed `ff19533d` itself; worktree clean at the assigned head, no
  uncommitted work discarded.

## Open handoff (unchanged criterion)

Acceptance "CI or a clearly designated hardware-capable conformance lane
runs the suite" is still unmet remotely: the suite provably passes at
this head (this round, local) but the designated CI lane has never
completed it. One runner-environment blocker remains (AppArmor profiles
unreadable under rootless), now reproduced with its exact daemon error.
