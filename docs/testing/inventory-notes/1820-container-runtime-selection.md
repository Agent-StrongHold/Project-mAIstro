---
inventory-delta:
  packages/maistro-bootstrap/tests: +12
  packages/maistro-core/tests: +6
  tests/: +29
---
# 1820-container-runtime-selection

Issue #1820 (honor the selected container runtime and define non-elevated
host installation) adds 29 node IDs across two suites.

`tests/` (+16) is a new file, `tests/test_install_runtime_selection.py`, which
lifts the runtime-selection functions out of `install.sh` verbatim — the same
technique as `test_install_compose_floor.py`, because
`release-installer.yml` runs the installer only on tags and no PR check would
otherwise execute a line of it. It pins the issue's regression matrix: both
CLIs present (selected podman must win — the headline case, verified to fail
against the old docker-first probe), selected podman never probing an
inaccessible docker (proven by canary: the unselected binary is not even
invoked), docker-only, podman-only, auto with both (docker by documented
policy), an unavailable selection failing actionably without bootstrapping or
selecting the other runtime, a selected-but-dead daemon failing instead of the
old unconditional `[ok] Compose runtime`, selection precedence (persisted
plan beats the transient env override; env fills the wizardless gap; unknown
tokens warn and degrade to auto), legacy plans without the runtime key still
resolving via auto, the docker-only preflight gate skipping under podman, and
the manifest recording the honored runtime. A follow-up repair added four
more: the generated recovery/success text must name the selection even when
no compose front-end was resolved — a `--no-start` run leaves COMPOSE_CMD
empty, and the old `:-docker compose` fallback wrote Docker commands into a
Podman install's RECOVERY.md and print_success output (proven to fail against
the pre-fix install.sh: the two headline tests fail, the resolved-front-end
and docker/auto-order ones pass on both, as they should). A fifth test
pins the stack healthchecks to the CMD-SHELL form after the rootless-
Podman transcript showed podman's compose provider word-splitting
exec-form args (`["CMD", "python", "-c", "import ..."]` reached the
engine as `python -c import ...` — SyntaxError every probe, engine stuck
unhealthy, conductor dependency never starting). The harness also became
hermetic (shim dir + coreutils toolbin, no system PATH) so a host with
real docker/podman binaries cannot flip the unavailable-selection tests.
The CI-repair round added four more (`tests/` total +25): the install
manifest must record the RESOLVED compose front-end, not the raw
selection — `write_install_manifest` consumed
`selected_container_runtime` via command substitution, so an `auto`
install recorded the literal `auto` and `maistro upgrade` re-ran its
docker-first lookup, handing a Podman-owned stack to a merely-present
Docker CLI on the first upgrade. `manifest_container_runtime` prefers
the front-end `start_engine` resolved, probes the documented
docker-then-podman order read-only under `auto`, and keeps `auto` only
when nothing answers (tests: auto landing on podman with a compose-less
docker present, auto landing on docker, auto staying `auto` when no
front-end answers, and an explicit podman selection surviving a working
docker). The same round moved the unknown-runtime-token diagnostic to
stderr — stdout must stay the bare token because every caller consumes
it via command substitution — and the harness's `warn` stub now
mirrors the real install.sh's stdout `warn` so that contract is pinned
rather than masked.

A later repair round added three more (`tests/` total +28) after review
flagged that the explicit-selection fail in `ensure_compose_runtime` keyed
on the RESOLVED plan field: an unanswered ``auto`` materializes as
``container_runtime: docker`` in delivery.json (the wizard's resolved
default), so a fresh host — which by definition has no Compose front-end
yet — failed naming a docker selection the operator never made, before the
documented macOS/apt Docker bootstrap could be offered. The fix adds
`container_runtime_selection_is_explicit`, which reads the RAW wizard
answer (`container_runtime_selection`, written by plan.py beside the
resolved field) and falls back to the `MAISTRO_CONTAINER_RUNTIME` pin: an
explicit docker answer (or pin) still fails actionably without
bootstrapping, an auto that RESOLVED to docker reaches the bootstrap, and
an auto that resolved to podman keeps the named-runtime failure (no Podman
bootstrap exists; installing Docker would be the silent switch). A fourth
test pins the wizardless analogue: an explicit `MAISTRO_CONTAINER_RUNTIME`
pin with no plan on a fresh host is a selection — it fails naming the pin
instead of bootstrapping whatever installs. The
headline test is proven to fail against the pre-fix install.sh (bootstrap
absent, selection named) and pass after.

Two adjacent suites were updated rather than added to: `test_install_compose_floor.py`'s
harness now also lifts `selected_container_runtime`/`runtime_compose_cmd`
(and points `PLAN_DIR` at an absent plan) so its unselected-path tests keep
exercising the real probe order, and `test_install_engine_floor.py`'s order
pin moved one level down to `docker_only_preflight_checks`, which now wraps
the engine floor and its two daemon-adjacent companions so a podman selection
never validates the unselected docker engine. The property pinned is
unchanged: the floor check precedes every daemon-touching step.

`packages/maistro-bootstrap/tests` (+9) covers the planning side:
`effective_runtime` explicit-selection survival and the deterministic auto
policy (podman only for `local_podman`; docker for every other tier,
including the schema default), the plan's delivery artifact recording both
the resolved runtime and the raw selection, the materialized `delivery.json`
carrying them, Makefile/entrypoint artifacts naming only the selected runtime
for both delivery modes, the renderer rejecting an unsupported runtime
instead of defaulting to docker, the keyword-default keeping direct callers
working, and the legacy-plan fallback to docker. The CI-repair round added
three degenerate-shape tests (+12 total): `_plan_runtime`'s isinstance guards
are total over arbitrary plan dicts — missing/non-dict `generated_artifacts`,
missing/non-dict `delivery`, an unrecognized runtime token, the podman happy
path — and a corrupted delivery artifact still materializes on the docker
default (the diff-coverage gate flagged the two untaken guard arcs at 50%;
these take them).

`packages/maistro-core/tests` (+6) pins the upgrade path onto the same
contract: `maistro upgrade` used to re-derive its compose front-end with a
docker-first probe (`_resolve_compose_runtime`), silently handing a selected
Podman install to Docker on the first upgrade. It now honors the runtime
recorded in the install manifest — the parameterized cases cover both
runtimes recorded, a recorded runtime whose binary is absent from PATH (still
honored: the upgrade must not silently switch; the preflight support probe
fails actionably instead), and the unrecorded/`auto` legacy behavior.

The change also edits `install.sh`, `docs/install/default-installer.md`
(runtime-selection policy + OS/runtime/privilege matrix), and the pydantic
install manifest schema (`container_runtime` field) — none of which move a
count.

## CI repair: supply-chain lock refresh (this note carries the round)

The `security` job failed at `0f7134057` on three advisories that postdate
the lock and are unrelated to this branch's diff (no dependency declaration
is touched by the feature): `aiohttp==3.14.3 CVE-2026-111064`,
`GHSA-2g87-pp6c-29x5` and `CVE-2026-111063`, all fixed in `3.14.4`.
Repaired per the gate's own prescription by refreshing the lock
(`uv lock --upgrade-package aiohttp==3.14.4`; `aiohttp` 3.14.3 → 3.14.4 and
its transitive `yarl` 1.24.2 → 1.25.1, no other package version or
requirement edge changed) and re-proved with CI's exact sequence
(`uv sync --locked --extra dev`, `uv pip install pip-audit`, freeze,
`pip-audit --strict --format=json`, `scripts/pip_audit_gate.py`): green, with
only the triaged `ecdsa PYSEC-2026-1325` remaining, plus
`scripts/check-dependency-namespaces.py` green. The `Supply chain
(pip-audit)` job shape (`uv sync --locked --all-extras`) is green the same
way. No test-count change from the repair; the +16 above is the suite truth.
Full round record, including the base-owned reachability failures this round
attributed to `origin/develop` with a pristine-base reproduction:
[`REPAIR-NOTES-1820-ci-gate-repair.md`](../../../REPAIR-NOTES-1820-ci-gate-repair.md).
