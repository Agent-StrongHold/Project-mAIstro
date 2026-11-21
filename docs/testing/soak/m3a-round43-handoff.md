# Issue #860 — round 43 (job c43151bd) repair: falsified the "Docker unreachable"
# premise; fresh two-replica functional shakedown at 3da4e035eb

**Not promotion evidence or integration approval.** This round corrected a
factual error that every recent round repeated, then used the corrected
environment to produce the freshest functional soak evidence this lane has
(recorded head `3da4e035eb1f46093d507db0f90b131a3a8d6dbe`, this round's exact
starting head). The promotion-blocking terminal conditions are unchanged and
remain external to the lane.

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
  starting head `3da4e035eb1f46093d507db0f90b131a3a8d6dbe` (clean on arrival,
  identical to round 42's end head — nothing to salvage), develop base
  `0d49d4e068de9ecbf0f9510e33781dba8abc87de`, merge-base `e46ad6708fda`.
- This round's job directory supplied **no `check-*.log` files** (listed:
  `dispatch-context-receipt.json`, `dispatch-context.json`, `events.jsonl`,
  `manifest.json`, `prompt.txt`, `state.json`). The lane brief referenced the
  round-40-era failure (`98a11313/check-3.log`, `assert 24 == 21` in
  `test_ensure_schema_fences_ddl_behind_advisory_lock`): already repaired by
  `cd77bb81c` and re-verified green in rounds 41 and 42 at this same tree.
- No test added or removed (no inventory delta — `check-suite-inventory.py`
  re-run this round: 17/17 match), no `quality/*.json` edit (no ledger
  amendment justified: the exact vulture gate was re-run green at this head by
  round 42 and no source file changed since), no gate weakening, no remote
  mutations, no destructive git operations.

## The repair: "Docker daemon unreachable in lane" was a wrong socket path, not an environment limit

Round 42's handoff (and rounds before it) recorded the soak as impossible
here because `DOCKER_HOST=unix:///var/run/docker.sock` fails with "Cannot
connect to the Docker daemon". Re-examined from first primitives this round:

- A `dockerd` process is running in this lane (pid 3931791, up 5+ days,
  rootless: `_DOCKERD_ROOTLESS_CHILD=1`, `ROOTLESSKIT_STATE_DIR=/run/user/1000/dockerd-rootless`).
- Its live socket is `unix:///run/user/1000/docker.sock`
  (`curl --unix-socket /run/user/1000/docker.sock http://localhost/_ping` → `OK`).
  `/var/run/docker.sock` is a stale root-owned bind that no longer reaches the
  daemon — the failure every prior round recorded is real for *that path only*.
- With `DOCKER_HOST=unix:///run/user/1000/docker.sock` the full harness stack
  works: this round reused the soak-dedicated `maistro-soak-pg` container
  (pgvector pg18, port 18433 — itself proof a prior round used this socket)
  and pulled nothing new (`nginx:1.27-alpine` already present).

So the "environment check" step that concluded *no soak can be hosted here*
was testing the wrong endpoint. This matches the earlier note in
`auto-860-ci-repair.md` (production-artifact round): "Docker is reachable in
this environment (rootless daemon socket `unix:///run/user/1000/docker.sock`;
the default `/var/run/docker.sock` is stale)". Later rounds lost that finding.

## Fresh evidence: `m3a-round43-shakedown.json` at head `3da4e035eb`

Invocation (round 26's documented form, absolute out-dir required for the
bind-mounted LB):

```
DOCKER_HOST=unix:///run/user/1000/docker.sock \
  uv run python scripts/soak/run_soak.py --sustain-seconds 420 \
  --out-dir /home/dev/Git/wt/auto-860/docs/testing/soak/evidence
```

Run 09:06:11Z → 09:15:37Z (420.09 s sustained mix through the LB, 2×
`maistro_server` replicas on 18201/18202 booted via the RC entrypoint path in
2.6 s, nginx LB on 18080, dedicated soak Postgres schema reset + migrated).
Exit code 1 with `FAILED checks: ['sustain_duration', 'exact_rc_artifact']` —
the expected terminal pair, replayed identically via
`failed_promotion_checks()` on the archived pack.

Result at `hashes.git_head = 3da4e035eb1f46093d507db0f90b131a3a8d6dbe`
(`git_status_sha256 0c4ad4fc…`, `nginx_conf_sha256 8e4d447a…`,
`soak_env_sha256 23d0de45…`, `pgvector/pgvector@sha256:2358fcba…`):

| Gate | Result |
| --- | --- |
| `exactly_once_task_admission` | **True** — 12 concurrent duplicate submissions, 12×202, 1 distinct run_id, 0 runs sharing one task run identity |
| `exactly_once_schedule_occurrence` | **True** — two OS processes raced one pinned occurrence: 1 Run created, loser `already_fired`, 0 occurrences with multiple runs |
| `rate_limit_enforced` | **True** — 800-request probes through the LB and directly on each replica, authenticated and unauthenticated, all enforced (`enforced_everywhere=true`) |
| `lb_failover_bounded` | **True** |
| `replica_2_rejoined` | **True** — SIGTERM drain 1.0 s, rc 143, `drain_5xx=0`, `drain_conn_errors=0`, no escalation; rejoin ~6 s |
| `graceful_drain` | ok=True (required, SIGTERM mode) |
| `nonterminal_runs_after_settle` | **True** — count 0; final runs `completed=2359 cancelled=1` |
| `task_admission_availability` | **True** — 2333 accepted 202s outside the kill window, ratio 1.0 |
| `sustain_duration` | ok=**False**: observed 420.09 s vs the 14,400 s floor (`PROMOTION_MIN_SUSTAIN_SECONDS`) |
| `exact_rc_artifact` | ok=**False**: `host-uvicorn-preflight` refusal (design; no CLI override — `preflight_artifact_check()`) |

Evidence hygiene (round-26 procedure): the run rewrites the tracked
fixed-name outputs, so `hashes.git_clean=false` at write time referred only to
the run's own in-flight files. The outputs were copied to the six
`m3a-round43-shakedown*` files and the tracked fixed-name files restored from
`HEAD` via `git show` (no `git checkout --`/`git restore` was used); `git
status` after the procedure shows exactly the six new untracked evidence
files and nothing else. The binding identity is `hashes.git_head` plus the
recorded config/env/status hashes.

## Terminal conditions (unchanged, external to the lane)

1. `exact_rc_artifact` requires the exact production Compose
   image/configuration of a release candidate that a release owner designates.
   Round 42's fresh sweep of this round's own dispatch capture (61 API
   sources, 828 comment-like bodies) found **0** designation hits; parent #89
   remains open; linked PRs #1567/#1602 are closed unmerged and #1672 is an
   open draft. No RC exists to soak; the host-process preflight correctly
   refuses to sign promotion regardless of duration.
2. `sustain_duration` requires ≥ 14,400 s observed on that exact RC. A 4-hour
   host-preflight run is now *technically possible* in this lane (per the
   socket correction above) but cannot satisfy the criterion it exists for —
   the artifact under test would still not be the RC — and would still exit
   failed on gate 1. Attempting it in a bounded lane session trades a
   guaranteed-incomplete result for hours of uncheckpointed runtime.

Both blockers are release-owner decisions and a production-runner activity,
not code repairs. The issue's falsification goal — the functional gate set —
is now observed green at this head, closing the round-42 staleness finding
(278 production paths had changed since the round-30 pack; the round-43 pack
is bound to the current head).

## Deterministic gates re-executed this round (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed** |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |

The full battery (14,676-test maistro-core suite, 9,090-test CI-invocation
suite, exact vulture gate, mypy, doc-links, test-duplicates) was re-executed
green at this **exact head** by round 42, ~25 minutes before this round
started, on an identical tree (`git status` clean on arrival at the same
commit); re-running it would re-verify a byte-identical tree. The soak run
changed no source, test, or gate file.

## Handoff

The next lane inherits: (a) working Docker access — export
`DOCKER_HOST=unix:///run/user/1000/docker.sock` (do not trust
`/var/run/docker.sock`); (b) a fresh functional pack bound to this head;
(c) the same two external blockers. If a future brief supplies an
owner-designated RC image/configuration and a production Compose runner, the
4-hour promotion soak is executable in this environment; nothing in the
harness needs to change for it.

Progress: checked 1 issue; done 0 acceptance-complete issues (2 of 10
acceptance rows remain externally blocked: exact-RC ≥ 4 h soak, RC
designation); skipped 0; validation-command errors 0; blocked 1 (external).
