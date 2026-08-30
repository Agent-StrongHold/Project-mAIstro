---
inventory-delta:
  tests/: +29
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

Four more node IDs, same file, for #713's own Codex finding and the follow-up
that fixed it: each e2e job pre-pulled all three compose Dockerfiles, but
`hive-conductor-e2e`'s `up ... api-tests` never builds `e2e-tests`, and
`hive-conductor-e2e-ui`'s `up ... e2e-tests` never builds `api-tests` — each
job was paying to pre-pull, and carrying the registry-failure exposure of, an
image `docker compose` was never going to touch. `JOB_DOCKERFILES` narrows
each job to the two Dockerfiles it actually builds, and
`test_each_e2e_job_pre_pulls_exactly_what_it_builds` (2 node IDs, parametrised
over both jobs) checks both directions against `ci.yml`'s text: a missing
Dockerfile the job builds, and a pre-pulled one it doesn't.

A second Codex finding, on that fix itself (#715): `JOB_DOCKERFILES` and
`ci.yml`'s text are both hand-written, so a mistake copied into one could
match a mistake copied into the other and nothing above would notice. The
remaining 2 node IDs derive the map's own claim from
`docker-compose.test.yml`'s real dependency graph instead of trusting it:
`test_the_job_targets_the_service_job_target_service_names` (parametrised
over both jobs) ties `JOB_TARGET_SERVICE` to the literal `--exit-code-from`
argument `ci.yml` runs, and
`test_job_dockerfiles_match_the_compose_dependency_closure` (parametrised
over both jobs) walks that service's `depends_on` closure and its `build:
context`/`dockerfile` fields to compute the Dockerfiles it actually builds,
then asserts `JOB_DOCKERFILES[job]` equals that computed set. A service later
gaining a new dependency changes what the closure computes and fails this
test until `JOB_DOCKERFILES` catches up, rather than the job quietly missing
a pre-pull for an image it has started building.

Eleven more node IDs, `tests/test_ac_state_authorized_floor.py`, for
SPEC-083026-fcc9 — a different ratchet entirely, found while driving #720
through the Quality gate. `quality/ratchet-authorizations.json`'s
`design_coverage@27.8791` grant (#631/#662) had, by design
(SPEC-082926-6f49's own "Consequences"), become permanent: once independent,
unrelated work grew the fold past it and stayed there, `_stale_grants` could
never fire again (it only fires when the fold falls back to the grant) and
`_removed_binding_grants` refused every removal for the same reason, on every
future base, regardless of what the removing change touched. #713, #715 and
#720 each hit "unbanked improvement" against this exact grant in one
afternoon, none of their diffs touching anything it corrects.

`_superseded_grants` closes it: a grant is superseded once at least three
*independent* already-merged notes each individually — not via the fold's
`max` — clear its floor, a claim a single contributor's own PR cannot
manufacture (one PR contributes at most one note). Five node IDs
(`TestSupersededGrantsDirectly`) pin the pure function against synthetic
`Note`s: two below threshold don't supersede, three do, a note sitting
exactly at the grant's own value doesn't count (`>`, not `>=` — that value is
the fall the grant permits, not evidence against it), a note missing the
counter entirely doesn't crash the count, and no grants means nothing to
check. The remaining six (`TestASupersededGrantCanBePruned`), extending the
existing `repo`/`gate`/`_run` harness with a new `extra_base_notes` fixture
argument to seed multiple independently-named base notes (the existing
fixture only ever wrote one base note, `_baseline`, which a per-note count
cannot exercise), run the real thing end to end: fewer than three still
refuses removal, three-or-more fails the run *before* pruning with a named
list of the superseding notes (replacing the generic "bank it" message that
sent three PRs looking in the wrong place), the same case then passes once
pruned, pruning needs no fresh note of its own (mirroring SPEC-082926-6f49's
own AC-12 for the ordinary case), the candidate's own worktree note cannot
manufacture supersession on its own (computed from the base's notes only),
and a grant with no independent notes above it is unaffected — the existing
AC-8 behavior, unchanged.
