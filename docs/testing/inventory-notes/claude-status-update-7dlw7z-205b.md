---
inventory-delta:
  tests/: +14
---
# claude-status-update-7dlw7z-205b

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_buildx_build_retry.py` — 7 node IDs for `scripts/buildx-build-retry.sh`
(Codex's #683 review finding: `docker/setup-buildx-action`'s default driver
runs BuildKit in its own container with its own image store, isolated from
the host daemon `prepull-base-images.sh` retries pulls into for #204 — so a
buildx-driven build's base-image fetch carried none of that retry protection,
reopening the exact failure #204 closed). Seven distinct test functions, none
parametrised except the workflow-contract check, which runs once per file
(ci.yml, security.yml) via `@pytest.mark.parametrize`, so the node count runs
one ahead of the function count.

A stub `docker` on PATH stands in for the real thing (no daemon in this
sandbox, and the point is the retry/backoff/exit-code contract, not Docker
itself): clean success on the first attempt, a transient failure that
retries and then succeeds, a persistent failure that exhausts the default
two attempts and reports `::error::` clearly, and `BUILDX_RETRY_ATTEMPTS=1`
disabling retry entirely. The last test reads both workflow files directly
and asserts every real `scripts/buildx-build-retry.sh` invocation carries the
`--` sentinel separating the script's own arguments from the passed-through
`docker buildx build` ones — a call missing it would silently swallow its
first real flag as the (rejected) sentinel position instead of building
anything.

Four more node IDs, same file, for a second Codex finding on #684: a `for`
loop bounded by `ATTEMPTS` runs zero times when `ATTEMPTS` is zero or
negative, and the script would then fall off the end with no explicit exit —
success, without docker ever having been invoked. Three parametrised cases
(`0`, `-1`, `not-a-number`) pin the new validation's `::error::` exit-2
refusal; a fourth pins the adjacent, easy-to-get-wrong case in the other
direction — `BUILDX_RETRY_ATTEMPTS=` (explicitly empty) is not malformed
input, `${VAR:-default}` already substitutes on empty the same as unset, and
that fourth test is what stops a future tightening of the validation from
rejecting a value bash itself treats as absent.

Three more node IDs, `tests/test_prepull_base_images.py`, for the gap a live
develop protected push actually hit: `hive-conductor-e2e` and
`hive-conductor-e2e-ui` run `docker compose --build` straight against
`packages/hive-conductor/docker-compose.test.yml`'s three Dockerfiles, never
through `prepull-base-images.sh`, so neither job carried any retry when one
of them failed outright on the exact #204 signature —
`cgr.dev/chainguard/python:latest: ... connection reset by peer`. The fix adds
a pre-pull step to both jobs; these tests are what stops it from rotting the
way `test_every_shipped_from_line_is_accounted_for` already guards
`docker-build`'s list — one confirms every `FROM` line across the three
compose Dockerfiles is covered by the pre-pull invocation, the other
(parametrised over both jobs) confirms `ci.yml` actually wires the step into
each job body, not just one of them.
