---
inventory-delta:
  packages/hive-conductor/backend/tests: +26
  packages/maistro-rsi/tests: +1
---
# issue-509-rsi-container-dispatch

## packages/hive-conductor/backend/tests: +26

`test_rsi_container_dispatch.py` (+25, new) is the suite for the container
dispatch backend that #509 adds (`services/rsi_container_dispatch.py`) and the
service lifecycle that consumes it. Docker is never contacted: every test
drives the same `_run_docker` seam the production paths use, so a green run is
proven against recorded argv, not against whatever daemon the CI host has.
(Beyond this suite, the dispatch path itself was smoke-verified against the
real daemon: a freshly built runner image executed the whole loop — clone,
test argv, agent cycle — inside an ephemeral `--rm` container, wrote its
checkpoints through the mounted report dir, and the host executed nothing but
the docker CLI.)

- The attestation (8): a missing CLI, an unreachable daemon and an absent
  runner image are each named as what is missing; all three present attests;
  the policy gate `require_isolation()` reads the backend probe when
  `IN_PROCESS_ISOLATION_AVAILABLE` is `None` (the shipped default — a gate, not
  a constant); the operator kill-switch (`False`) refuses even with a live
  backend; a hung docker probe lands in the same operator-facing refusal
  instead of an unhandled exception (the route's intended 400, not a 500); and
  the refusal still names `run_rsi_isolated.sh`.
- The launch argv (9): the loop runs inside the image's own venv python, no
  shell token anywhere in the argv (a metacharacter payload in the objective
  stays an argv token), the source repo is mounted read-only, the report dir is
  mounted outside the edited tree, the policy vector crosses as `--test-argv`
  JSON, a bare leading `python` in the policy vector is resolved to the image's
  virtualenv interpreter before forwarding (the base env's pinned PATH would
  otherwise pick the base-image python, which cannot import pytest — while an
  argument that merely *says* `python` is candidate data and passes through
  untouched), the runtime is hardened like the wrapper (`--cap-drop=ALL`,
  `no-new-privileges`, `--pids-limit`, `--memory`, `--rm`, plus `--user`
  pinning the loop to this process's uid:gid — with every capability stripped,
  container-root could not write the host-owned report mount), the container is
  labeled/named with its run id — and the container-side command parses with
  the real `maistro_rsi` argparse parser, pinning every flag the dispatch
  forwards (added after the first run of this change omitted the required
  `--test-cmd`, which would have failed every dispatch at exit 2 inside the
  container, before a single cycle).
- The dispatched lifecycle (9): a run starts and is contained (status
  `completed`, container id recorded, the in-process `LocalRsiLoop`
  demonstrably never constructed, every host subprocess a docker verb and none
  an `exec`, and `launch()` staged the container's global git config into the
  report mount — exactly the read-only mount target and its gitdir, never a
  wildcard, because the clone-time ownership check ignores command-line-scoped
  config); a run is refused over HTTP when the backend cannot attest (400
  naming the missing piece, no launch attempted); cancellation stops the
  container and settles the record `stopped` (one bounded stop — `stop_run`'s —
  with the cancellation path's stop reserved for cancellations that didn't go
  through `stop_run`); a stop that races the launch — arriving while `docker
  run` is still unrolling in its worker thread, so no container id exists yet
  — waits out the bounded launch and stops the container it actually started,
  and the cancelled run never reaches the wait (a container that must never
  be waited on once its run was stopped); a container exiting non-zero is
  `errored`; a container
  the backend loses (daemon restart) is `errored` rather than running forever;
  checkpoints the container wrote become run cycles/promotions/summary for the
  UI; and the spec derives output directories from the run id under the
  server's working root (the request cannot aim them, two runs cannot collide).

`test_rsi_execution_containment.py` (46 → 46, net 0) is reworked in place, not
grown: the #305 pins that answered "this process cannot contain the loop"
(fail-closed constants, the builders-factory sandbox assertions) now assert the
#509 form — the flag defaults to `None` and the refusal fires only when the
dispatch probe fails, and the "policy-resolved config reaches the loop" tests
assert the config reaches the *dispatch spec* instead (the host-side
`LocalRsiLoop` monkeypatched to raise if constructed). Same node count, so no
delta; the assertions moved with the execution model. The two refusal tests
now pin the backend's probe off the host's real docker — they assert policy
plumbing, not daemon state.

## packages/maistro-rsi/tests: +1

`test_non_production_reachability.py` (5 → 5, net 0): the activation pin
`test_the_http_run_gate_stays_disabled_until_containment_exists` is renamed to
`test_the_http_run_gate_attests_a_real_backend_not_a_constant` and now asserts
the shipped flag is *not* a bare bool — a literal `True` attests containment
nobody verified, a literal `False` is #305's refuse-everything constant that
#509 replaced with a working path — while still pinning the route's
`require_isolation()` call. The scanner-sensitivity cases gain the `False` and
`None` spellings. `__main__`'s `--test-argv` flag itself is exercised from the
conductor suite above (the parse test), so no new RSI-side nodes there.

`test_local_loop.py` (net +1) restores the proof of
SPEC-082926-a6ab/AC-7 — the #509 rework of the conductor containment suite
had deleted the old marker-bearing test along with the host-side construction
it pinned. The criterion's substance survives #509 unchanged: the loop builds
the builders apply function from its own config, so a run resolved to
`container` isolation reaches `make_builders_apply_patch` as
`isolation="container"` plus its image, never a silently-defaulted host
sandbox. The proof now lives against `maistro_rsi.local_loop` directly — in
the dispatched model that construction runs inside the runner container, and
the guarantee is the loop's, wherever it executes. This +1 is what restores
the design-coverage floor the Quality gate folded at the base.
