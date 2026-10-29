# #2251 gate-repair validation round — head `4581729a9` (merge of PR head `edaa0cc7e` + develop `10f872fa7`)

Validation-only round (writer role). No source changes; evidence recorded here so the
next round does not re-derive it. All four gates named red in the prior attempt
history were re-proven locally on this head.

## Merge state

- `origin/develop` fetched at round time = `10f872fa7be3` — **already an ancestor of
  HEAD** (`git merge-base --is-ancestor` true). The `mergeable: dirty` seen on the
  PR at `edaa0cc7e` is resolved by the local merge commit; CHANGELOG.md conflict was
  resolved by adopting develop's file wholesale (the branch's only CHANGELOG delta
  was the cosmetic `#2359; follow-up to #2357` → `#2359` reword — nothing lost).
- Diff vs develop base is exactly the 4 PR files: `docker-compose.repro.yml` (new),
  `docs/fleet/gate-c-repro-isolation.md` (new), `scripts/check-compose-resources.py`
  (+1 file registration), `tests/test_check_compose_resources.py` (assertion 8→9
  profiles; test count unchanged → no suite-inventory delta).

## Gate evidence (all commands run on this box, this head)

| Gate | Command | Result |
|---|---|---|
| compose acceptance | `env DB_PASSWORD=x LITELLM_MASTER_KEY=y 'API_KEYS=["repro:throwaway"]' docker compose -f docker-compose.repro.yml config -q` | OK; without env it refuses with `required variable DB_PASSWORD is missing` (the `${VAR:?}` contract) |
| compose resources | `uv run python scripts/check-compose-resources.py` | `OK: 9 supported Compose profiles have bounded memory, PID, and CPU limits`, rc=0 |
| its tests | `uv run pytest tests/test_check_compose_resources.py -q` | 13 passed |
| compose secrets | `uv run python scripts/check-compose-secrets.py` | `ok: 10 tracked Compose file(s) hand out no credential`, rc=0 |
| connection creds | `uv run python scripts/check-connection-credentials.py` | OK (1648 files), rc=0 |
| suite inventory | `uv run python scripts/check-suite-inventory.py` | `ok: 21 suite(s) match the recorded inventory`, rc=0 |
| vulture ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0 — 1248 reviewed identities = 1248 findings; **no ledger amendment needed** |
| ruff | `uv run ruff check .` / `ruff format --check .` | all green |
| docker-build (engine) | `docker build -t maistro-engine:head-check .` from HEAD | rc=0 (image `d7a75e262957`). hive-conductor / engine-research / rsi-runner Dockerfiles COPY none of the 4 changed files, so their inputs are identical to develop's |
| compose-durability | `CONDUCTOR_PORT=8101 packages/hive-conductor/scripts/verify-compose-durability.sh` | **rc=0** — inventory, down/up recreate, read-after-recreate, image-rebuild recreate, backup 0600 tarball, restore-from-destroyed-volume all ✔ |
| postgres pg18 | `pytest tests/migrations/test_migration_chain.py` (18 passed) → `alembic upgrade head` → `pytest packages/maistro-core/tests/persistence` (835 passed, 84 skipped) → `test_container_postgres.py + tests/workspaces` with `MAISTRO_REQUIRE_PG_LEGS=1` (434 passed, 2 skipped) vs live `pgvector/pgvector:pg18` on 127.0.0.1:5598 | green |
| postgres pg17 | same core steps vs `pgvector/pgvector:pg17` on 127.0.0.1:5599 | 18 + 835 passed, green |
| live repro stack | project `repro-cr2251` (left up by a prior attempt of this lane): engine `healthy`, litellm digest `af8050ea…b898` (identical to prod `docker-compose.yml`), pgvector pg18 `healthy`; `GET /health/live` → `{"status":"ok"}`; `GET /health/ready` with `Authorization: Bearer repro:throwaway` → `{"status":"ok"}` | end-to-end acceptance of the isolated stack; `/health/ready` unauthenticated 200 is canonical (status-only public contract, admin payload gated — `maistro_server/api/health.py:223`) |

## Environmental repairs done on this box (not repo changes)

The four gate failures seen on CI at `edaa0cc7e` were not reproducible as code faults;
locally three host faults had to be repaired first:

1. **/tmp tmpfs at 100% inodes** (1,048,576/1,048,576) — broke buildkit step I/O
   (`uv export` exit 2) and image export. Repaired by deleting regenerable scratch
   only: `/tmp/node-compile-cache` (V8 cache), stale `/tmp/leak-run`, pytest tmpdirs
   older than 24h. 111k inodes freed.
2. **Stale containerd lease** `t2x2fqamg731rc3tgpb53jzai` (created by the first
   ENOSPC-killed export) blocked every retry with `failed to open writer: ref …
   locked`. Removed surgically via `sudo ctr -n moby leases rm <id>` — nothing else.
3. **Intermittent container-net DNS/connect timeouts** to `files.pythonhosted.org`
   (Tailscale MagicDNS `100.100.100.100` flakiness in buildkit step netns). Bursts;
   retries in calm windows succeed (final durability run built + passed cleanly).

Lane-owned docker resources created by this round: `cr2251-pg17b` (pg17 on 5599 —
still up, harmless), images `cr2251-dnstest`, `cr2251-dns2`, `maistro-engine:head-check`
(build evidence, left in place). Pre-existing `repro-cr2251-*` stack and `cr2251-pg18`
were running on arrival and were deliberately left untouched.

## Residual risks

- CI will re-run all gates on the next push; GH runners have none of the local host
  faults. Nothing in the 4-file diff can affect wheel-imports/coverage/security —
  no `packages/`, `alembic/`, or dependency-manifest changes vs develop.
- If the durability or docker-build jobs still flake in CI, compare against a
  develop-branch run of the same SHA window before touching code: their inputs
  (Dockerfiles, `uv.lock`, `packages/**`, compose files under `packages/`) are
  identical to develop's on this head.
