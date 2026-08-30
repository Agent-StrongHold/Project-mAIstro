#!/usr/bin/env bash
# Retry a `docker buildx build`, because buildx's default driver cannot reuse
# prepull-base-images.sh's retried pulls (Codex, #683).
#
# Why this exists
# ----------------
# `docker/setup-buildx-action`'s default `docker-container` driver runs
# BuildKit inside its OWN container with its OWN image store, isolated from
# the host daemon. `prepull-base-images.sh` retries `docker pull` against the
# HOST daemon (#204) -- a retry that never reaches a buildx-driven build,
# which resolves every `FROM`/`--from=` reference through a fresh, unretried
# registry fetch. That reopens exactly the failure #204 closed, for any job
# converted to buildx: a required check red on a registry reset, on a build
# that is otherwise fine.
#
# Why the whole build is retried, not just the pull
# ---------------------------------------------------
# prepull-base-images.sh retries only the fetch, deliberately: a genuine
# build failure must still fail on its first attempt, or a real regression
# would silently cost three attempts before anyone notices it is red.
# A buildx invocation has no equivalent seam -- pull and build are one
# `docker buildx build` call -- so that precision is not available here.
# Retrying the whole call trades a bounded, known cost (a genuinely broken
# build fails on its Nth attempt instead of its first) for closing a real,
# previously-proven failure mode. ATTEMPTS is kept lower than
# prepull-base-images.sh's default for exactly that reason.
#
# Usage:
#   scripts/buildx-build-retry.sh -- <docker buildx build arguments...>
#
# Env:
#   BUILDX_RETRY_ATTEMPTS  attempts (default 2)

set -euo pipefail

ATTEMPTS="${BUILDX_RETRY_ATTEMPTS:-2}"

if [[ ${1:-} != "--" ]]; then
	echo "usage: $0 -- <docker buildx build arguments...>" >&2
	exit 2
fi
shift

for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
	if docker buildx build "$@"; then
		exit 0
	fi
	if [[ ${attempt} -eq ${ATTEMPTS} ]]; then
		echo "::error::docker buildx build failed after ${ATTEMPTS} attempts" >&2
		exit 1
	fi
	echo "::warning::docker buildx build failed (attempt ${attempt}/${ATTEMPTS}); retrying" >&2
	sleep $((attempt * 5))
done
