#!/usr/bin/env bash
# Pre-pull the external images a Dockerfile needs, retrying the fetch (#204).
#
# Why this exists
# ---------------
# `docker-build` failed on PR #174 before touching a line of repository content:
#
#   #2 [internal] load metadata for cgr.dev/chainguard/python:latest-dev
#   #2 ERROR: failed to do request: Head "https://cgr.dev/v2/.../latest-dev":
#      read tcp ...: read: connection reset by peer
#
# The same job succeeded on PR #175 four minutes later, same Dockerfile and same
# runner pool. The build is fine; the network fetch is not.
#
# That matters more than one red check. The goal is CI trustworthy enough for
# automerge, and a required check that fails on a registry reset cannot be
# trusted — someone has to notice and re-run it. Worse, the GitHub App gets
# `403 Resource not accessible by integration` on `rerun-failed-jobs`, so an
# automated agent that hits this cannot clear it and the PR simply sits red.
#
# Why only the *fetch* is retried
# -------------------------------
# Retrying `docker build` wholesale would hide real breakage and triple the cost
# of an honestly-red build. Pulling first means a genuine build failure — a bad
# Dockerfile, a failing `RUN` — still fails on its first attempt, exactly as it
# does today. Only the network step gets another go.
#
# Why the image list is derived, not written down
# -----------------------------------------------
# A hand-maintained list in the workflow rots the first time a Dockerfile gains
# a stage or an external `COPY --from=...` source, and rots silently: the missing
# image is simply pulled by `docker build` instead, so the retry quietly stops
# covering it and nothing fails until the next registry blip. Parsing the
# Dockerfiles means the list cannot drift from what is actually built.
#
# Usage:
#   scripts/prepull-base-images.sh Dockerfile packages/hive-conductor/Dockerfile
#   scripts/prepull-base-images.sh --list Dockerfile     # print images, pull nothing
#
# Env:
#   PREPULL_ATTEMPTS  attempts per image (default 3)

set -euo pipefail

ATTEMPTS="${PREPULL_ATTEMPTS:-3}"

usage() {
	echo "usage: $0 [--list] DOCKERFILE [DOCKERFILE...]" >&2
	exit 2
}

# Every external image the given Dockerfiles reference, deduplicated.
#
# Docker can introduce an external image in two places:
#   * `FROM image [AS alias]`;
#   * `COPY --from=image ...`, where `image` is not a prior stage alias/index.
#
# Skips things that are not pullable images:
#   * `scratch`, which is the empty base and has no registry entry;
#   * a reference to an earlier build stage, tracked via `AS <alias>` and the
#     numeric stage indexes seen so far;
#   * an unresolved build argument, which cannot be resolved without build args.
#     It is reported on stderr rather than dropped silently, since it means this
#     script no longer covers that image.
base_images() {
	awk '
		function emit_external(image, origin, low) {
			low = tolower(image)
			if (image ~ /\$/) {
				print FILENAME ": cannot resolve " image " from " origin ", not pre-pulled" > "/dev/stderr"
			} else if (low != "scratch" && !(low in stage) && !(image ~ /^[0-9]+$/)) {
				print image
			}
		}

		toupper($1) == "FROM" {
			image = ""
			alias = ""
			for (i = 2; i <= NF; i++) {
				if ($i ~ /^--/) continue            # --platform=... and friends
				if (image == "") { image = $i; continue }
				if (toupper($i) == "AS" && i < NF) alias = tolower($(i + 1))
			}
			emit_external(image, "FROM")
			# Registered after the image is judged, so `FROM x AS builder`
			# followed by `FROM builder` resolves in that order.
			if (alias != "") stage[alias] = 1
			stage_index++
			next
		}

		toupper($1) == "COPY" {
			for (i = 2; i <= NF; i++) {
				if ($i ~ /^--from=/) {
					image = $i
					sub(/^--from=/, "", image)
					emit_external(image, "COPY --from")
				}
			}
		}
	' "$@" | sort -u
}

pull() {
	local image="$1" attempt
	for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
		if docker pull "$image"; then
			return 0
		fi
		if [[ ${attempt} -eq ${ATTEMPTS} ]]; then
			# Named explicitly: without this the job would fall through to a
			# `docker build` failure that reads like a broken Dockerfile.
			echo "::error::could not pull ${image} after ${ATTEMPTS} attempts" >&2
			return 1
		fi
		echo "::warning::pull of ${image} failed (attempt ${attempt}/${ATTEMPTS}); retrying" >&2
		sleep $((attempt * 5))
	done
}

main() {
	local list_only=0
	if [[ ${1:-} == "--list" ]]; then
		list_only=1
		shift
	fi
	[[ $# -ge 1 ]] || usage

	local dockerfile
	for dockerfile in "$@"; do
		[[ -f ${dockerfile} ]] || {
			echo "::error::no such Dockerfile: ${dockerfile}" >&2
			exit 1
		}
	done

	local images
	images="$(base_images "$@")"
	if [[ -z ${images} ]]; then
		echo "::error::no external images found in: $*" >&2
		exit 1
	fi

	if [[ ${list_only} -eq 1 ]]; then
		echo "${images}"
		return 0
	fi

	local image
	while IFS= read -r image; do
		pull "${image}"
	done <<<"${images}"
}

main "$@"
