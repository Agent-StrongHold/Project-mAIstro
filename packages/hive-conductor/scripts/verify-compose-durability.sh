#!/usr/bin/env bash
# Prove the standalone Compose deployment's durable state survives recreate,
# and that backup/restore round-trips it atomically (#331).
#
# Scenario, in order — every step must hold for the script to pass:
#
#   guard     the startup guard REFUSES to serve when CONDUCTOR_DATA_DIR is
#             unwritable or (in-container) sits on the container's own root
#             filesystem (silently ephemeral across recreate)
#   create    fresh `up --build`, one-shot setup wizard provisions the first
#             admin and daily user
#   write     authenticated writes land in every durable store: settings
#             (state.db), an integration secret (user_credentials.enc under
#             credential_master.key), a session cookie
#   recreate  `down` (volume kept) + `up`, then `up` after an image rebuild —
#             neither may log anyone out or drop a record
#   read      pre-recreate session cookie still authenticates; the admin can
#             still log in; the setting and the stored secret are still there
#   backup    `maistro security backup` captures the whole data directory
#             into one archive
#   restore   `down -v` (volume destroyed), fresh volume, stop, `maistro
#             security restore --yes`, start — the pre-destroy session cookie
#             authenticates again and every record is readable
#
# Layout note: CONDUCTOR_DATA_DIR is /data/conductor, a directory INSIDE the
# `conductor-data` volume mounted at /data. The data directory must not be
# the volume's mount root: restore swaps the directory itself by rename, and
# a mount point cannot be renamed (EBUSY). Helper containers therefore mount
# the volume at /data (read-only) or /srv (read-write) and address
# /data/conductor or /srv/conductor.
#
# Usage:
#   packages/hive-conductor/scripts/verify-compose-durability.sh
# Env:
#   CONDUCTOR_PORT   host port for the deployment (default 8101)
#   KEEP_UP=1        leave the stack running after a failure, for debugging
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.yml"
PORT="${CONDUCTOR_PORT:-8101}"
BASE_URL="http://localhost:${PORT}"
DATA_DIR_IN_VOLUME="conductor"   # CONDUCTOR_DATA_DIR, relative to the volume root
JAR="$(mktemp -d)/cookies.txt"
BACKUP_DIR="$(mktemp -d)"
ARCHIVE="${BACKUP_DIR}/conductor-data.tar.gz"
ADMIN_USER="duradmin"
ADMIN_PASS="durability-admin-pass-331"
PROBE_SECRET="durability-probe-secret-331"

PASS=0
FAIL=0

note() { printf '\n===== %s =====\n' "$1"; }
ok()   { PASS=$((PASS + 1)); printf '✔ %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '✘ %s\n' "$1"; }
check() { # check <name> <command...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi
}
require() { # require <name> <command...> — hard-fail variant for preconditions
  local name="$1"; shift
  if "$@" >&2; then ok "$name"; else bad "$name"; echo "precondition failed: ${name}" >&2; exit 1; fi
}
curl_auth() { curl -fsS -b "$JAR" -H 'Content-Type: application/json' "$@"; }
login_body() {
  printf '{"username": "%s", "password": "%s"}' "$ADMIN_USER" "$ADMIN_PASS"
}

wait_ready() { # wait_ready <minutes>
  local deadline=$((SECONDS + $1 * 60))
  while (( SECONDS < deadline )); do
    if curl -fsS "${BASE_URL}/health/ready" >/dev/null 2>&1; then return 0; fi
    sleep 3
  done
  echo "service did not become ready within $1 minutes" >&2
  $COMPOSE logs --no-color --tail=80 >&2 || true
  return 1
}

cleanup() {
  if (( FAIL == 0 )) || [[ -z "${KEEP_UP:-}" ]]; then
    $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$BACKUP_DIR" "$(dirname "$JAR")"
  else
    echo "KEEP_UP=1 and failures present — stack left running at ${BASE_URL}" >&2
  fi
}
trap cleanup EXIT

note "preconditions"
docker info >/dev/null 2>&1 || { echo "docker unavailable" >&2; exit 1; }
if env -i bash -c "exec 3<>/dev/tcp/localhost/${PORT}" 2>/dev/null; then
  echo "something already listens on ${PORT}; set CONDUCTOR_PORT" >&2
  exit 1
fi
ok "docker available, port ${PORT} free"

note "start: fresh deployment (this builds the image)"
$COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
require "compose up --build" $COMPOSE up -d --build
require "service healthy on first boot" wait_ready 20

note "guard: startup must refuse an unwritable data directory"
IMAGE="$($COMPOSE config --images | head -1)"
GUARD_UNWRITABLE_LOG="${BACKUP_DIR}/guard-unwritable.log"
GUARD_RC=0
timeout 240 docker run --rm --tmpfs /data:ro "$IMAGE" >"$GUARD_UNWRITABLE_LOG" 2>&1 || GUARD_RC=$?
# The refusal must stop the process, not serve: `docker run` in the
# foreground only returns once the main process has exited; exit code 124 is
# `timeout`'s, meaning uvicorn was still running (and would have served).
check "unwritable data dir: process stops instead of serving" test "$GUARD_RC" -ne 124
check "unwritable data dir: refusal logs DATA_DIR_UNWRITABLE" \
  grep -q "DATA_DIR_UNWRITABLE" "$GUARD_UNWRITABLE_LOG"

note "guard: startup must refuse an ephemeral (container-root) data directory"
GUARD_EPHEMERAL_LOG="${BACKUP_DIR}/guard-ephemeral.log"
GUARD_RC=0
timeout 240 docker run --rm "$IMAGE" >"$GUARD_EPHEMERAL_LOG" 2>&1 || GUARD_RC=$?
check "ephemeral data dir: process stops instead of serving" test "$GUARD_RC" -ne 124
check "ephemeral data dir: refusal logs DATA_DIR_EPHEMERAL" \
  grep -q "DATA_DIR_EPHEMERAL" "$GUARD_EPHEMERAL_LOG"

note "create: one-shot setup wizard"
curl -fsS -X POST "${BASE_URL}/v1/setup/complete" -H 'Content-Type: application/json' -d "{
  \"hardware_preset\": \"laptop\",
  \"admin_username\": \"${ADMIN_USER}\",
  \"admin_password\": \"${ADMIN_PASS}\",
  \"user_username\": \"duruser\",
  \"user_password\": \"durability-user-pass-331\",
  \"optional_modules\": []
}" >/dev/null
ok "setup/complete provisioned the first admin and user"

note "write: session, settings, integration credential"
require "login as admin (session cookie issued)" \
  curl -fsS -c "$JAR" -X POST "${BASE_URL}/v1/auth/login" \
    -H 'Content-Type: application/json' -d "$(login_body)"
curl_auth -X PATCH "${BASE_URL}/v1/settings" -d '{"theme": "dark"}' >/dev/null
ok "settings write acknowledged (theme=dark into state.db)"
curl_auth -X PUT "${BASE_URL}/v1/credentials/github" \
  -d "{\"secret\": \"${PROBE_SECRET}\"}" >/dev/null
ok "credential write acknowledged (user_credentials.enc under credential_master.key)"

note "inventory: the coupled durable files exist in the volume, least-privilege owned"
VOLUME_NAME="$($COMPOSE config --format json | python3 -c \
  "import json,sys; print(next(iter(json.load(sys.stdin)['volumes'].values()))['name'])")"
INVENTORY="$(docker run --rm -v "${VOLUME_NAME}:/data:ro" --entrypoint ls "$IMAGE" -1 "/data/${DATA_DIR_IN_VOLUME}" || true)"
echo "$INVENTORY"
check "state.db in data dir"              bash -c "echo '${INVENTORY}' | grep -qx 'state.db'"
check "credential_master.key in data dir" bash -c "echo '${INVENTORY}' | grep -qx 'credential_master.key'"
check "user_credentials.enc in data dir"  bash -c "echo '${INVENTORY}' | grep -qx 'user_credentials.enc'"
OWNERS="$(docker run --rm -v "${VOLUME_NAME}:/data:ro" --entrypoint stat "$IMAGE" \
  -c '%u' "/data" "/data/${DATA_DIR_IN_VOLUME}" || true)"
check "volume root and data dir owned by nonroot uid 65532" \
  bash -c "test '${OWNERS}' = '65532
65532'"

note "recreate: compose down/up keeps the volume"
$COMPOSE down >/dev/null
$COMPOSE up -d >/dev/null
require "service healthy after down/up" wait_ready 10

note "read: after recreate, accounts, sessions, settings, secrets survive"
check "pre-recreate session cookie still authenticates" curl_auth "${BASE_URL}/v1/auth/whoami"
if curl_auth "${BASE_URL}/v1/auth/whoami" | grep -q "\"${ADMIN_USER}\""; then
  ok "whoami reports the same admin"
else
  bad "whoami reports the same admin"
fi
check "admin password still logs in" \
  curl -fsS -X POST "${BASE_URL}/v1/auth/login" -H 'Content-Type: application/json' -d "$(login_body)"
if curl_auth "${BASE_URL}/v1/settings" | grep -q '"theme":"dark"'; then
  ok "settings still hold theme=dark"
else
  bad "settings still hold theme=dark"
fi
if curl_auth "${BASE_URL}/v1/credentials" | grep -q '"configured":true'; then
  ok "github credential still configured (store decrypts)"
else
  bad "github credential still configured (store decrypts)"
fi

note "recreate: image replacement (rebuild, same volume) also preserves state"
$COMPOSE up -d --build >/dev/null
require "service healthy after image rebuild" wait_ready 20
check "pre-rebuild session cookie STILL authenticates" curl_auth "${BASE_URL}/v1/auth/whoami"
check "admin password STILL logs in" \
  curl -fsS -X POST "${BASE_URL}/v1/auth/login" -H 'Content-Type: application/json' -d "$(login_body)"
if curl_auth "${BASE_URL}/v1/credentials" | grep -q '"configured":true'; then
  ok "github credential STILL configured"
else
  bad "github credential STILL configured"
fi

note "backup: one atomic archive of the whole data directory"
$COMPOSE stop >/dev/null
# The archive is written by the container's uid 65532; make the host-side
# staging dir writable for it (it is a fresh mktemp dir under the runner's
# private tmp, and the archive itself lands world-readable for the host).
chmod 777 "$BACKUP_DIR"
docker run --rm -v "${VOLUME_NAME}:/data:ro" -v "${BACKUP_DIR}:/backup" \
  --entrypoint maistro "$IMAGE" \
  security backup --data-dir "/data/${DATA_DIR_IN_VOLUME}" --out /backup/conductor-data.tar.gz
require "archive exists and is non-empty" test -s "$ARCHIVE"
tar -tzf "$ARCHIVE" | head -20
ok "archive is a readable gzip tarball"

note "restore: destroy the volume, boot fresh, restore, verify everything"
$COMPOSE down -v >/dev/null
$COMPOSE up -d >/dev/null
require "fresh volume boots (setup wizard would be back)" wait_ready 10
$COMPOSE stop >/dev/null
# Mount the volume at /srv so the data directory /srv/conductor is NOT the
# mount root: restore swaps it by rename, and a mount point cannot be
# renamed (EBUSY). /srv itself must be writable by uid 65532 — the volume
# inherited that ownership from the image.
docker run --rm -v "${VOLUME_NAME}:/srv" -v "${BACKUP_DIR}:/backup:ro" \
  --entrypoint maistro "$IMAGE" \
  security restore --data-dir "/srv/${DATA_DIR_IN_VOLUME}" --from /backup/conductor-data.tar.gz --yes
$COMPOSE start >/dev/null
require "service healthy after restore" wait_ready 10

check "post-restore: pre-destroy session cookie authenticates" curl_auth "${BASE_URL}/v1/auth/whoami"
check "post-restore: admin password logs in" \
  curl -fsS -X POST "${BASE_URL}/v1/auth/login" -H 'Content-Type: application/json' -d "$(login_body)"
if curl_auth "${BASE_URL}/v1/settings" | grep -q '"theme":"dark"'; then
  ok "post-restore: settings hold theme=dark"
else
  bad "post-restore: settings hold theme=dark"
fi
if curl_auth "${BASE_URL}/v1/credentials" | grep -q '"configured":true'; then
  ok "post-restore: github credential still configured"
else
  bad "post-restore: github credential still configured"
fi

note "result"
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
if (( FAIL > 0 )); then
  echo "durability scenario FAILED" >&2
  exit 1
fi
echo "durability scenario PASSED: create, write, recreate (down/up + image replacement), read, backup, restore all hold"
