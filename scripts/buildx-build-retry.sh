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
# #899 adds the second bound: an invocation that never returns must not prevent
# the retry loop from advancing. Recent full docker-build evidence completed
# four cached builds plus the boot canary in 7m41s (#869); an 8-minute deadline
# therefore gives one individual build approximately the whole observed job
# budget before it is classified as wedged.
#
# Usage:
#   scripts/buildx-build-retry.sh -- <docker buildx build arguments...>
#
# Env:
#   BUILDX_RETRY_ATTEMPTS  attempts (default 2)
#   BUILDX_ATTEMPT_TIMEOUT hard deadline per attempt (default 15m; GNU timeout syntax)

set -euo pipefail

ATTEMPTS="${BUILDX_RETRY_ATTEMPTS:-2}"
ATTEMPT_TIMEOUT="${BUILDX_ATTEMPT_TIMEOUT:-15m}"

# A zero or negative ATTEMPTS makes the loop below run zero times: the script
# would reach EOF after `shift` with no explicit exit, which is success --
# reporting a build step green without ever invoking docker (Codex, #684).
if ! [[ ${ATTEMPTS} =~ ^[0-9]+$ ]] || [[ ${ATTEMPTS} -lt 1 ]]; then
	echo "::error::BUILDX_RETRY_ATTEMPTS must be a positive integer, got '${ATTEMPTS}'" >&2
	exit 2
fi

# GNU timeout treats duration 0 as "no timeout", which would silently recreate
# #899. Accept its ordinary duration syntax, including fractions used by the
# fast regression test, but reject zero and malformed values before any build.
if ! [[ ${ATTEMPT_TIMEOUT} =~ ^[0-9]+([.][0-9]+)?[smhd]?$ ]] || \
	[[ ${ATTEMPT_TIMEOUT} =~ ^0+([.]0+)?[smhd]?$ ]]; then
	echo "::error::BUILDX_ATTEMPT_TIMEOUT must be a positive duration, got '${ATTEMPT_TIMEOUT}'" >&2
	exit 2
fi

if ! command -v timeout >/dev/null 2>&1; then
	echo "::error::GNU timeout is required to enforce the buildx attempt deadline" >&2
	exit 2
fi

if [[ ${1:-} != "--" ]]; then
	echo "usage: $0 -- <docker buildx build arguments...>" >&2
	exit 2
fi
shift

for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
	set +e
	timeout --signal=TERM --kill-after=15s "${ATTEMPT_TIMEOUT}" docker buildx build "$@"
	status=$?
	set -e

	if [[ ${status} -eq 0 ]]; then
		exit 0
	fi

	if [[ ${status} -eq 124 || ${status} -eq 137 ]]; then
		outcome="timed out after ${ATTEMPT_TIMEOUT}"
	else
		outcome="failed with exit ${status}"
	fi

	if [[ ${attempt} -eq ${ATTEMPTS} ]]; then
		echo "::error::docker buildx build ${outcome} on attempt ${attempt}/${ATTEMPTS}; attempts exhausted" >&2
		exit 1
	fi

	echo "::warning::docker buildx build ${outcome} (attempt ${attempt}/${ATTEMPTS}); retrying" >&2
	sleep $((attempt * 5))
done
