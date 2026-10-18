---
inventory-delta:
  packages/maistro-bootstrap/tests: +12
  packages/maistro-core/tests: +6
  tests/: +25
---
# 1820-container-runtime-selection

Issue #1820 (honor the selected container runtime and define non-elevated
host installation) adds 25 node IDs across two suites.

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
