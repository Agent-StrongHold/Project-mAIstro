#!/usr/bin/env bash
set -euo pipefail

# Public bootstrapper.
#
# Usage:
#   curl -fsSL https://get.hiveconductor.dev | bash
#   curl -fsSL https://raw.githubusercontent.com/BlakeMatthews-dev/maistro-engine/main/get.sh | bash
#
# This script needs bash and is the entrypoint for macOS, Linux, and WSL2.
# On native Windows (no bash), use get.ps1 instead — from PowerShell:
#   irm https://raw.githubusercontent.com/BlakeMatthews-dev/maistro-engine/main/get.ps1 | iex
# get.ps1 sets up WSL2 + Ubuntu, then runs this same script inside it.
#
# This script installs/updates the maistro-engine source tree, then delegates to
# ./install.sh so the same interactive feature/deployment flow is used everywhere.
#
# Version selection (E5/#298, ADR-073126-c4e1):
#
#   ./get.sh                          # latest RELEASE tag (default)
#   ./get.sh --version v1.0.0         # exactly that release tag
#   MAISTRO_VERSION=v1.0.0-rc1 ./get.sh
#   ./get.sh --channel dev            # develop branch, for contributors
#   ./get.sh --branch my/topic        # any branch, for development
#
# The default used to be "clone branch main", which made "install v1.0.0"
# inexpressible and meant two people running the same command a week apart got
# different code. The default is now a tag, which is immutable.

REPO="${MAISTRO_REPO:-BlakeMatthews-dev/maistro-engine}"
# No default: an empty MAISTRO_BRANCH means "resolve a release tag". Defaulting
# it to `main` here would make an explicit branch request indistinguishable
# from no request at all.
BRANCH="${MAISTRO_BRANCH:-}"
VERSION="${MAISTRO_VERSION:-}"
CHANNEL="${MAISTRO_CHANNEL:-stable}"
# 1 = refuse to install anything when no release tag can be resolved, instead
# of falling back to a branch. For CI and for anyone who needs the install to
# be reproducible or not at all.
REQUIRE_RELEASE="${MAISTRO_REQUIRE_RELEASE:-0}"
# Branch installed when the stable channel has no release to resolve. `main` and
# not `develop` on purpose: ADR-073126-c4e1 §2 makes `main` the only branch a
# final release tag may point at, so it is the closest thing to "the released
# line" while no release exists.
NO_RELEASE_FALLBACK_BRANCH="main"
LEGACY_DIR="$HOME/.maistro"
DEFAULT_INSTALL_DIR="$HOME/.maistro/maistro-engine"
INSTALL_DIR="${MAISTRO_DIR:-$DEFAULT_INSTALL_DIR}"
REPO_URL="https://github.com/${REPO}.git"
ARCHIVE_MARKER=".maistro-archive-install"

# Set by resolve_ref(): REF_KIND is `tag` or `branch`, REF is the tag/branch
# name, ARCHIVE_URL is the matching codeload tarball, and IMAGE_TAG is the
# container tag install.sh should pin the compose stack to.
REF_KIND=""
REF=""
ARCHIVE_URL=""
IMAGE_TAG=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[maistro]${NC} $*"; }
ok() { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: get.sh [options] [-- install.sh options]

Version selection:
  --version VERSION   Install exactly this release tag (e.g. v1.0.0, v1.0.0-rc1).
                      A bare 1.0.0 is accepted and normalized to v1.0.0.
  --channel stable    Latest published release tag. This is the default.
  --channel dev       The 'develop' branch — for contributors, not for users.
  --branch NAME       Any branch, for development. Overrides --channel.
  --require-release   Fail instead of falling back to a branch when no release
                      tag can be resolved.
  -h, --help          Show this help.

Everything after `--`, and any unrecognized option, is passed straight through
to install.sh (e.g. --answers-file, --skip-wizard, --no-start).

Environment:
  MAISTRO_VERSION, MAISTRO_CHANNEL, MAISTRO_BRANCH, MAISTRO_REQUIRE_RELEASE,
  MAISTRO_REPO, MAISTRO_DIR, MAISTRO_SHA256SUMS_URL,
  MAISTRO_GITHUB_TOKEN (only used to raise the GitHub API rate limit).
EOF
}

# Normalize a user-supplied version to the tag form the repo actually uses.
# `1.0.0` and `v1.0.0` name the same release to a human; only one of them is a
# real ref, so accept both and emit the real one.
normalize_version() {
    local v="$1"
    [[ "$v" == v* ]] && printf '%s\n' "$v" || printf 'v%s\n' "$v"
}

# Latest published release tag via the GitHub API, or empty when there is none.
#
# /releases/latest deliberately excludes prereleases and drafts, which is the
# behavior we want for a default install: an rc must be asked for by name, never
# handed to someone who just ran the one-liner.
latest_release_tag() {
    command -v curl >/dev/null 2>&1 || return 0
    local api="https://api.github.com/repos/${REPO}/releases/latest"
    local -a auth=()
    local token="${MAISTRO_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"
    [[ -n "$token" ]] && auth=(-H "Authorization: Bearer ${token}")
    local body
    # No -f: a 404 (no releases yet) is an expected answer here, not an error,
    # and the caller distinguishes "no releases" from "could not ask".
    body="$(curl -sSL --max-time 20 -H 'Accept: application/vnd.github+json' \
        "${auth[@]}" "$api" 2>/dev/null)" || return 0
    printf '%s' "$body" \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -1
}

# Decide what to install, once, before anything is downloaded. Explicit beats
# implicit throughout: --version wins over --branch wins over --channel.
resolve_ref() {
    if [[ -n "$VERSION" ]]; then
        REF_KIND="tag"
        REF="$(normalize_version "$VERSION")"
        info "Installing release ${REF} (requested explicitly)."
    elif [[ -n "$BRANCH" ]]; then
        REF_KIND="branch"
        REF="$BRANCH"
        warn "Installing branch '${REF}' — a branch moves. Use --version vX.Y.Z for a reproducible install."
    elif [[ "$CHANNEL" == "dev" ]]; then
        REF_KIND="branch"
        REF="develop"
        warn "Channel 'dev': installing the 'develop' branch. Unreleased code — expect breakage."
    elif [[ "$CHANNEL" == "stable" ]]; then
        REF="$(latest_release_tag)"
        if [[ -n "$REF" ]]; then
            REF_KIND="tag"
            info "Installing latest release ${REF}."
        else
            # No releases published yet (today: the repo has zero tags), or the
            # API was unreachable. Neither is a reason to install silently —
            # say exactly what is about to happen and how to avoid it.
            if [[ "$REQUIRE_RELEASE" == "1" || "$REQUIRE_RELEASE" == "true" ]]; then
                fail "No published release found for ${REPO} and MAISTRO_REQUIRE_RELEASE=1 was set. Nothing installed."
            fi
            REF_KIND="branch"
            REF="$NO_RELEASE_FALLBACK_BRANCH"
            warn "No published release found for ${REPO} (the GitHub API returned none, or was unreachable)."
            warn "Falling back to the '${REF}' branch, which is where release tags are cut from."
            warn "This is NOT a pinned install: '${REF}' moves. To pin, re-run with --version vX.Y.Z"
            warn "once a release exists, or with --require-release to fail instead of falling back."
        fi
    else
        fail "Unknown channel '${CHANNEL}'. Use --channel stable or --channel dev."
    fi

    if [[ "$REF_KIND" == "tag" ]]; then
        ARCHIVE_URL="https://github.com/${REPO}/archive/refs/tags/${REF}.tar.gz"
        # A tagged install pins the container images to the matching tag, so
        # the compose stack and the source tree are the same release.
        IMAGE_TAG="$REF"
    else
        ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"
        # No published image corresponds to an arbitrary branch commit, so a
        # branch install uses the moving tag — and install.sh builds from
        # source anyway unless image_pull is explicitly readied.
        IMAGE_TAG="latest"
    fi
}

download_with_git() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Updating existing maistro-engine checkout at $INSTALL_DIR..."
        if [[ "$REF_KIND" == "tag" ]]; then
            # --force so re-running with the same tag after an upstream retag
            # (which should never happen — tags are immutable per ADR §2 — but
            # would otherwise wedge the checkout) still converges.
            git -C "$INSTALL_DIR" fetch --depth 1 --force origin "refs/tags/${REF}:refs/tags/${REF}"
            git -C "$INSTALL_DIR" checkout --force --detach "refs/tags/${REF}"
        else
            git -C "$INSTALL_DIR" fetch --depth 1 origin "$REF"
            git -C "$INSTALL_DIR" checkout -B "$REF" "origin/$REF"
        fi
        ok "Updated source checkout to ${REF}."
        return
    fi

    if [[ -e "$INSTALL_DIR" ]]; then
        fail "$INSTALL_DIR exists but is not a git checkout. Move it aside or set MAISTRO_DIR."
    fi

    info "Cloning maistro-engine ${REF} into $INSTALL_DIR..."
    # `--branch` takes a tag name too, and with --depth 1 leaves HEAD detached
    # at the tag — which is what a pinned install should look like.
    git clone --depth 1 --branch "$REF" "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned source checkout at ${REF}."
}

download_with_archive() {
    if [[ -e "$INSTALL_DIR" && ! -e "$INSTALL_DIR/$ARCHIVE_MARKER" ]]; then
        fail "$INSTALL_DIR exists but was not created by this installer. Move it aside or set MAISTRO_DIR."
    fi
    command -v curl >/dev/null 2>&1 || fail "curl is required when git is unavailable."
    command -v tar >/dev/null 2>&1 || fail "tar is required when git is unavailable."

    if [[ -e "$INSTALL_DIR/$ARCHIVE_MARKER" ]]; then
        info "Updating existing maistro-engine archive checkout at $INSTALL_DIR..."
    else
        info "Downloading maistro-engine ${REF} archive..."
    fi

    local tmp
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/maistro.XXXXXX")"
    curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$tmp" --strip-components=1
    if [[ -e "$INSTALL_DIR/$ARCHIVE_MARKER" ]]; then
        # Updating in place: drop the old tree (keep .env) before laying down the
        # fresh archive, so files removed/renamed upstream don't linger as stale.
        find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name '.env' -exec rm -rf {} +
    fi
    mkdir -p "$INSTALL_DIR"
    cp -R "$tmp"/. "$INSTALL_DIR"/
    rm -rf "$tmp"
    touch "$INSTALL_DIR/$ARCHIVE_MARKER"
    ok "Source archive is up to date."
}

migrate_legacy_install() {
    # The previous public installer wrote .env directly into ~/.maistro.
    # The new default is the nested ~/.maistro/maistro-engine checkout. If
    # we're on the default path and the old .env exists without a new one,
    # copy it over so existing users keep their tokens and provider keys.
    [[ "$INSTALL_DIR" == "$DEFAULT_INSTALL_DIR" ]] || return 0
    [[ -f "$LEGACY_DIR/.env" ]] || return 0
    [[ -f "$INSTALL_DIR/.env" ]] && return 0

    warn "Found legacy install at $LEGACY_DIR — migrating .env to $INSTALL_DIR."
    mkdir -p "$INSTALL_DIR"
    # `cp` creates under the caller's umask and the old `chmod 600` ran after
    # the credentials were already on disk (#357). Pipe through the installer's
    # helper instead, which creates the destination at 0600 with O_CREAT|O_EXCL
    # before the first byte. `|| true` is gone with it: a migration that
    # silently failed left the user believing their keys had moved.
    if ! python3 "$INSTALL_DIR/scripts/secret_env.py" create "$INSTALL_DIR/.env" \
            < "$LEGACY_DIR/.env"; then
        fail "Could not migrate $LEGACY_DIR/.env to $INSTALL_DIR/.env (see above). Your existing file is untouched."
    fi
    ok "Migrated .env. Old copy left at $LEGACY_DIR/.env — remove it once verified."
}

bootstrap_source() {
    # Download FIRST — migrate_legacy_install would otherwise create $INSTALL_DIR
    # (with a copied .env), which trips the "exists but not a checkout" guard in
    # download_with_git and the missing-marker guard in download_with_archive,
    # blocking legacy users from installing/updating. Copy the .env afterward,
    # once the checkout exists.
    if command -v git >/dev/null 2>&1; then
        download_with_git
    else
        warn "git not found; falling back to source archive download."
        download_with_archive
    fi
    migrate_legacy_install
}

resolve_args_paths() {
    # Rewrite relative --answers-file paths to absolute while cwd is still
    # the caller's, before run_installer cd's into INSTALL_DIR.
    local args=() arg prev=""
    for arg in "$@"; do
        if [[ "$prev" == "--answers-file" && "$arg" != /* ]]; then
            arg="$(cd "$(dirname "$arg")" && pwd)/$(basename "$arg")"
        elif [[ "$arg" == --answers-file=* && "${arg#--answers-file=}" != /* ]]; then
            local rel="${arg#--answers-file=}"
            arg="--answers-file=$(cd "$(dirname "$rel")" && pwd)/$(basename "$rel")"
        fi
        args+=("$arg")
        prev="$arg"
    done
    printf '%s\0' "${args[@]}"
}

# Verify the downloaded install.sh against a published SHA256SUMS manifest
# before executing it (SPEC-072726-3439 Phase 5). Opt-in via
# MAISTRO_SHA256SUMS_URL until the production release URL is wired in as a
# default constant.
verify_installer_checksum() {
    [[ -n "${MAISTRO_SHA256SUMS_URL:-}" ]] || return 0
    command -v curl >/dev/null 2>&1 || fail "curl is required for checksum verification."

    local sha_cmd
    if command -v sha256sum >/dev/null 2>&1; then
        sha_cmd="sha256sum"
    elif command -v shasum >/dev/null 2>&1; then
        sha_cmd="shasum -a 256"
    else
        fail "sha256sum or shasum is required for checksum verification."
    fi

    info "Verifying install.sh against $MAISTRO_SHA256SUMS_URL ..."
    local sums expected actual
    sums="$(curl -fsSL "$MAISTRO_SHA256SUMS_URL")" || fail "Could not fetch checksum manifest."
    expected="$(printf '%s\n' "$sums" | awk '$NF == "install.sh" {print $1}' | head -1)"
    [[ -n "$expected" ]] || fail "Checksum manifest has no entry for install.sh."
    actual="$($sha_cmd "$INSTALL_DIR/install.sh" | awk '{print $1}')"
    if [[ "$actual" != "$expected" ]]; then
        fail "install.sh checksum mismatch (expected $expected, got $actual). Refusing to run it."
    fi
    ok "install.sh checksum verified."
}

run_installer() {
    local resolved=()
    if [[ $# -gt 0 ]]; then
        while IFS= read -r -d '' item; do
            resolved+=("$item")
        done < <(resolve_args_paths "$@")
        set -- "${resolved[@]}"
    fi

    cd "$INSTALL_DIR"
    chmod +x ./install.sh 2>/dev/null || true

    # Pin the compose stack's images to the same release as the source tree.
    # install.sh derives this itself from `git describe` when it is unset, but
    # the archive path has no git metadata to derive it from, so pass it
    # explicitly and let one decision cover both download paths.
    export MAISTRO_IMAGE_TAG="${MAISTRO_IMAGE_TAG:-$IMAGE_TAG}"

    if [[ -t 0 ]]; then
        exec bash ./install.sh "$@"
    fi

    if [[ -r /dev/tty ]]; then
        exec bash ./install.sh "$@" < /dev/tty
    fi

    exec bash ./install.sh "$@"
}

# Consume only get.sh's own options; everything else is install.sh's business
# and is forwarded verbatim. Unrecognized options are forwarded rather than
# rejected so install.sh stays free to grow flags without get.sh needing to
# learn about each one.
parse_args() {
    PASSTHROUGH=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --version)
                [[ $# -ge 2 ]] || fail "--version requires a value (e.g. --version v1.0.0)"
                VERSION="$2"
                shift 2
                ;;
            --version=*)
                VERSION="${1#--version=}"
                shift
                ;;
            --channel)
                [[ $# -ge 2 ]] || fail "--channel requires a value (stable or dev)"
                CHANNEL="$2"
                shift 2
                ;;
            --channel=*)
                CHANNEL="${1#--channel=}"
                shift
                ;;
            --branch)
                [[ $# -ge 2 ]] || fail "--branch requires a value"
                BRANCH="$2"
                shift 2
                ;;
            --branch=*)
                BRANCH="${1#--branch=}"
                shift
                ;;
            --require-release)
                REQUIRE_RELEASE=1
                shift
                ;;
            -h | --help)
                usage
                exit 0
                ;;
            --)
                shift
                PASSTHROUGH+=("$@")
                break
                ;;
            *)
                PASSTHROUGH+=("$1")
                shift
                ;;
        esac
    done
}

main() {
    parse_args "$@"
    resolve_ref

    echo ""
    echo "maistro-engine public installer"
    printf 'repo:   %s\n' "${REPO}"
    printf '%-8s%s\n' "${REF_KIND}:" "${REF}"
    printf 'images: %s\n' "${IMAGE_TAG}"
    printf 'dir:    %s\n' "${INSTALL_DIR}"
    echo ""

    bootstrap_source
    verify_installer_checksum
    if [[ ${#PASSTHROUGH[@]} -gt 0 ]]; then
        run_installer "${PASSTHROUGH[@]}"
    else
        run_installer
    fi
}

main "$@"
