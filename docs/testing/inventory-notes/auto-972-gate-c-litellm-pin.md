# Repair #972 @ e6619eb80b9 (branch auto-972) — 2026-10-21 Gate C CI-repair round

Assigned head `e6619eb80b99fbdaaa30af5aae33688ed6dd4e30`, assigned develop
base `9cc5d1aca141695d747b23bd06a12cce9d8f850d` (merge base == base; the
branch sits exactly on develop). Job
`349bea8a1ae8482d9aa20eacfd079196`. Worktree was clean at start; every claim
below was re-derived, none inherited. The prior round (82a238e3) died on
provider rate limits after all five of its checks passed (rc=0 each), so no
repair evidence was lost — but nothing had been diagnosed yet either.

## Root cause of the Gate C failure (re-derived from CI logs, not assumed)

`gh run view 39613465196 --log-failed` (run for this exact head) shows the
failing step is **"Install and start through the documented path"** and the
first error inside it:

    litellm Error manifest unknown
    langfuse  Interrupted
    Error response from daemon: manifest unknown

The failure happens at **image pull time**, ~1 second after `docker compose
up` begins — before any container starts, before any readiness assertion.
`docker-compose.yml` pinned `litellm` to the mutable tag
`ghcr.io/berriai/litellm:main-latest` (line 164). Evidence the tag itself is
gone (not a runner blip):

- `docker manifest inspect ghcr.io/berriai/litellm:main-latest` →
  `manifest unknown`, from this environment, hours after the CI failure.
- Anonymous ghcr registry API: `HEAD
  /v2/berriai/litellm/manifests/main-latest` → 404, while
  `main` and `main-v1.x.y` tags still list.

Timeline: develop's own Gate C **passed** at 13:09:46Z (run 39605564512,
pulling litellm successfully at 13:10:49Z, job 119240744414); this branch's
run failed at 14:03:58Z with the same compose file (no compose diff exists
between the branch and develop — `git diff origin/develop...HEAD --stat --
docker-compose.yml` is empty). The tag was deleted upstream in that window.
Any Gate C run of any branch after it would fail identically; the branch's
Python changes are unrelated to the failure.

## The repair

`docker-compose.yml` now pins litellm by **digest**:

    image: ghcr.io/berriai/litellm@sha256:af8050ea45707c42a0572c5cceaa5cebaa89cee4c5cd0585cf879a529804b898

- The digest is a multi-arch index (linux/amd64 + linux/arm64 + attestation
  entries), verified to still exist upstream by digest after the tag
  deletion (`docker manifest inspect` by digest → 4 platforms).
- It is the image this repo's stack has been running on the shared daemon
  for the past 11 days (`LITELLM_RELEASE_TAG=v1.106.0-dev.3`, image created
  2026-09-16), i.e. the tested line, not a new version choice.
- This fulfills the intent already recorded in
  `docs/specs/SPEC-072726-3439-installer-e2e-flow.md` (Open questions:
  "`main-latest` is unpinned today; Phase 5 should pin the LiteLLM image
  digest too"). The spec text was left untouched (governance-owned); this
  note records that the pin now exists.
- The other third-party refs were checked for the same fragility and left
  alone: `pgvector/pgvector:pg18` (major tag, resolves) and
  `langfuse/langfuse:2` (major tag, resolves). Only litellm was on a
  mutable `-latest` tag and only litellm was broken.

## Local Gate C proof (isolated parallel stack)

The shared daemon runs other lanes' live stacks (`maistro-postgres` belongs
to worktree auto-52's project; deleting it was not an option), so the proof
ran install.sh's **sanctioned root override** path (`docker-compose.override.yml`,
safety-gated by install.sh's `require_safe_override_file`): unique
container names + shifted host ports (engine 18000, conductor 18101,
litellm 14000, langfuse 13100, postgres 15433). The override file was
temporary and is not committed; `docker-compose.yml` itself is the only
functional change and CI's own run cannot even see an override file.

With the pinned digest, on this branch, following gate-c.yml's exact steps:

1. Clean starting state (rm .env, rm -rf .maistro-install, project down).
2. `./install.sh --skip-wizard --no-cli --no-open` with gate-c.yml's exact
   env (plus isolated ports) → **exit 0**; compose pulled the digest-pinned
   litellm (the exact operation CI failed on), built maistro-engine and
   hive-conductor, started all five services.
3. gate-c.yml readiness assertions, verbatim logic: `/health/live` and
   `/health/ready` on the engine → ok; `/health/ready` on the conductor →
   ok; `SELECT version_num FROM alembic_version` → `065` (matches the
   `^[0-9a-z_]+$` fail-closed grep); final re-assertions → ok.
4. `docker inspect gatec-proof-litellm` → image `sha256:af8050ea…`,
   status running; litellm answers `/health/liveliness` 200 and returns the
   canonical 401 auth error on unauthenticated `/v1/models`.
5. Teardown `docker compose down -v --remove-orphans` → project removed;
   auto-52's `maistro-postgres` still `Up (healthy)` afterwards.

## Gates re-run on this tree

- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 3409 files already formatted
- `uv run pytest packages/maistro-core/tests/extensions/ -q` →
  **1287 passed, 5 skipped** (quarantine suite: 38 passed)
- `scripts/check-compose-resources.py` → OK (8 profiles bounded)
- `scripts/check-compose-secrets.py` → ok (9 Compose files, no credential)
- `scripts/check-deployment-claims.py` → OK
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → rc=0
  (1321 reviewed identities == 1321 findings; no ledger edit needed)

## Scope note

No Python production code changed in this round; the issue #972 quarantine
work at this head (effective-governing-state audit for version actions in
`packages/maistro-core/src/maistro/extensions/quarantine.py`) is unchanged
and its tests still pass. No test was added or removed → no
suite-inventory delta for this round. The driver-side "recovery budget
exhausted / provider 400 missing tags" block was an LLM-provider
infrastructure failure in earlier rounds, not a repository defect; nothing
in-tree addresses or needs to address it.

## Residual risks

- The pinned litellm (v1.106.0-dev.3, 2026-09-16 build) will age; upgrades
  are now a deliberate digest bump (see compose comment). If BerriAI ever
  garbage-collects the digest, Gate C breaks again — visible immediately as
  a pull failure, not silently.
- `langfuse/langfuse:2` and `pgvector/pgvector:pg18` remain mutable
  major tags; the same deletion mode would break Gate C through them. Not
  repaired here (no evidence of breakage; minimal-change discipline).
