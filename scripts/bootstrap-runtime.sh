# shellcheck shell=bash
# The user-owned Python/uv bootstrap contract (#1821).
#
# Sourced by both supported POSIX entrypoints — install.sh (via $SCRIPT_DIR)
# and get.sh (via $INSTALL_DIR, after the source tree is in place) — so the
# two can never drift. It is also sourced whole by the installer test
# harnesses, which is why it has no top-level side effects beyond state
# initialization and function definitions.
#
# The contract, in one place:
#
#   1. uv is resolved first. A compatible existing installation is reused
#      (on PATH, or in a known user-owned directory that this shell simply
#      predates). Otherwise uv is installed with its official standalone
#      installer — a shell script, so a host with neither Python nor pip can
#      still bootstrap — into a user-owned directory, and that directory is
#      put on this process's PATH so the installer can use it immediately.
#      pip is never involved, so PEP 668 "externally managed" environments
#      cannot block or break this path, and nothing is ever elevated.
#   2. Python is resolved for the INSTALLER'S OWN helper execution
#      (scripts/secret_env.py and inline validation snippets) against
#      MAISTRO_HELPER_PYTHON_FLOOR. A host interpreter that satisfies the
#      helper floor is accepted as-is; if none exists, the interpreter uv
#      provisions is used. The helper floor is deliberately lower than the
#      package floor: the wizard and everything it runs go through uv, which
#      resolves packages/maistro-bootstrap's requires-python and provisions a
#      matching interpreter when the host does not have one. Accepting a
#      helper interpreter therefore never reports package execution as
#      satisfied — that claim is made only by ensure_package_python, which
#      validates the >= MAISTRO_PACKAGE_PYTHON_FLOOR requirement separately.
#
# Sourcing contract:
#   - the sourcing entrypoint provides info/ok/warn/fail (the library
#     installs quiet fallbacks only when they are absent, so a harness's
#     definitions always win);
#   - source it exactly once per process: sourcing (re)initializes the
#     resolution state below.
#
# Environment knobs (all optional, all user-owned scope):
#   MAISTRO_UV_INSTALLER_URL   explicit installer URL; wins over everything
#   MAISTRO_UV_VERSION         pin, e.g. 0.9.5 -> astral.sh/uv/0.9.5/install.sh
#   MAISTRO_UV_NO_MODIFY_PATH  =1 passes INSTALLER_NO_MODIFY_PATH=1 through to
#                              the official installer (no shell rc changes)
#   UV_INSTALL_DIR             passed through; also probed as a uv location

# --- Interpreter floors ------------------------------------------------------
#
# The smallest interpreter the installer's own helpers run on. Kept at 3.11
# on purpose: helpers are stdlib-only scripts, and the strict 3.12+ floor the
# workspace requires is enforced where it belongs — on package execution —
# not here. The split is the tested contract of #1821.
MAISTRO_HELPER_PYTHON_FLOOR="3.11"
# What packages/maistro-bootstrap/pyproject.toml (requires-python) demands
# for the wizard and CLI. test_bootstrap_runtime.py asserts this constant
# matches that file, so the two cannot drift.
MAISTRO_PACKAGE_PYTHON_FLOOR="3.12"

# --- State -------------------------------------------------------------------
#
# Resolution results live here. Entry points also initialize the arrays for
# their own readers; this is the one authoritative reset.
PYTHON_CMD=()
UV_CMD=()
UV_PACKAGE_PYTHON=""

# --- Caller-provided logging, with quiet fallbacks ---------------------------
if ! declare -F info >/dev/null 2>&1; then
    info() { printf 'INFO: %s\n' "$*"; }
fi
if ! declare -F ok >/dev/null 2>&1; then
    ok() { printf 'OK: %s\n' "$*"; }
fi
if ! declare -F warn >/dev/null 2>&1; then
    warn() { printf 'WARN: %s\n' "$*"; }
fi
if ! declare -F fail >/dev/null 2>&1; then
    fail() { printf '[error] %s\n' "$*" >&2; exit 1; }
fi

# --- PATH and location helpers ----------------------------------------------

# Prepend $1 to PATH when absent. In-process only: no file on disk changes,
# so nothing unrelated to this install is ever rewritten (#1821: the installer
# must be able to use what it just resolved without a fresh shell).
path_prepend_once() {
    local dir="$1"
    [[ -d "$dir" ]] || return 0
    case ":$PATH:" in
        *":$dir:"*) return 0 ;;
    esac
    PATH="$dir:$PATH"
    export PATH
}

# Directories a compatible existing uv may sit in without being on this
# process's PATH: a previous install added it to the shell rc files, but this
# shell was started before that (or a non-login shell never read them).
# $UV_INSTALL_DIR first because the official installer honors it.
uv_path_candidates() {
    [[ -n "${UV_INSTALL_DIR:-}" ]] && printf '%s\n' "$UV_INSTALL_DIR"
    printf '%s\n' "${HOME:?}/.local/bin"
    printf '%s\n' "${HOME:?}/.cargo/bin"
    printf '%s\n' /opt/homebrew/bin
}

# --- uv acquisition ----------------------------------------------------------

# Which installer to run. Default: the official standalone installer for the
# latest uv release. MAISTRO_UV_VERSION pins a release (provenance policy:
# the astral.sh official channel, pinnable for reproducible installs);
# MAISTRO_UV_INSTALLER_URL replaces the whole thing for mirrors/air-gaps.
uv_installer_url() {
    if [[ -n "${MAISTRO_UV_INSTALLER_URL:-}" ]]; then
        printf '%s\n' "$MAISTRO_UV_INSTALLER_URL"
    elif [[ -n "${MAISTRO_UV_VERSION:-}" ]]; then
        printf 'https://astral.sh/uv/%s/install.sh\n' "$MAISTRO_UV_VERSION"
    else
        printf '%s\n' "https://astral.sh/uv/install.sh"
    fi
}

install_uv_standalone() {
    command -v curl >/dev/null 2>&1 ||
        fail "curl is required to install uv. Install curl (or uv itself: https://docs.astral.sh/uv/getting-started/installation/) and re-run."

    local url scratch installer
    url="$(uv_installer_url)"
    scratch="$(mktemp -d "${TMPDIR:-/tmp}/maistro-uv.XXXXXX")"
    installer="$scratch/install.sh"

    info "Installing uv (user-owned; no system Python, pip, or elevation involved) from $url ..."
    if ! curl -fsSL "$url" -o "$installer"; then
        rm -rf "$scratch"
        fail "Could not download the uv installer from $url. Check network/proxy access and re-run; nothing was installed or modified."
    fi

    # The official installer installs into a user-owned directory ($HOME/.local/bin
    # by default, UV_INSTALL_DIR to override) and — its documented, announced,
    # idempotent default — appends a clearly marked PATH block to shell start-up
    # files so NEW shells find uv. It never elevates. MAISTRO_UV_NO_MODIFY_PATH=1
    # forwards INSTALLER_NO_MODIFY_PATH=1 for hosts where nothing may touch rc
    # files; this installer never edits rc files itself either way.
    trap 'rm -rf "$scratch"' INT TERM
    if ! INSTALLER_NO_MODIFY_PATH="${MAISTRO_UV_NO_MODIFY_PATH:-0}" sh "$installer"; then
        rm -rf "$scratch"
        trap - INT TERM
        fail "The uv installer failed (its output is above — unwritable destination? interrupted download?). Nothing else was modified; fix the problem and re-run."
    fi
    rm -rf "$scratch"
    trap - INT TERM

    local dir
    while IFS= read -r dir; do
        path_prepend_once "$dir"
    done < <(uv_path_candidates)

    if command -v uv >/dev/null 2>&1; then
        UV_CMD=(uv)
    else
        fail "uv was installed but cannot be found on PATH (looked in \$UV_INSTALL_DIR, ~/.local/bin, ~/.cargo/bin, /opt/homebrew/bin). Add its directory to PATH and re-run."
    fi
    ok "uv installed: $(uv --version)"
    local uv_path
    uv_path="$(command -v uv)"
    info "uv lives in ${uv_path%/*} (owned by the initiating account). This run already has it on PATH; new shells get it from the installer's marked PATH block."
    if [[ "${MAISTRO_UV_NO_MODIFY_PATH:-0}" == "1" ]]; then
        warn "MAISTRO_UV_NO_MODIFY_PATH=1 was honored: no shell start-up file was touched. Add ${uv_path%/*} to PATH yourself for new shells."
    fi
}

# Resolve uv: reuse what exists (PATH, then known user-owned locations), or
# install the standalone tool. Never pip (#1821).
ensure_uv() {
    [[ ${#UV_CMD[@]} -gt 0 ]] && return 0

    if command -v uv >/dev/null 2>&1; then
        UV_CMD=(uv)
        ok "uv found: $(uv --version)"
        return 0
    fi

    # Installed but not on this shell's PATH: adopt it instead of downloading
    # a second copy — retrying after a failed run must reuse, not duplicate.
    local dir
    while IFS= read -r dir; do
        [[ -x "$dir/uv" ]] || continue
        path_prepend_once "$dir"
        UV_CMD=(uv)
        ok "uv found at $dir/uv — not on this shell's PATH; added for this run"
        return 0
    done < <(uv_path_candidates)

    install_uv_standalone
}

# --- Python acquisition ------------------------------------------------------

# True when the interpreter invocation "$@" (e.g. python3, or py -3) satisfies
# the dotted floor in $1. The probe is data on stdin, so nothing from the host
# environment can leak into or out of it.
python_meets_floor() {
    local floor="$1"
    shift
    "$@" - "$floor" <<'PY' >/dev/null 2>&1
import sys

floor = tuple(int(part) for part in sys.argv[1].split("."))
raise SystemExit(0 if sys.version_info >= floor else 1)
PY
}

# The interpreter uv resolves (and provisions when missing) for the
# PACKAGE floor. Sets UV_PACKAGE_PYTHON to its absolute path on success.
# This is the only place allowed to claim package execution is satisfied —
# it is validated against >= MAISTRO_PACKAGE_PYTHON_FLOOR independently of
# whatever helper interpreter ensure_python accepted (#1821).
ensure_package_python() {
    [[ -n "$UV_PACKAGE_PYTHON" ]] && return 0
    ensure_uv

    local floor="$MAISTRO_PACKAGE_PYTHON_FLOOR"
    if ! "${UV_CMD[@]}" python find ">=$floor" >/dev/null 2>&1; then
        info "Resolving a Python >= $floor interpreter for the maistro-install package (requires-python >= $floor)..."
        if ! "${UV_CMD[@]}" python install ">=$floor"; then
            fail "uv could not provision Python >= $floor (network, disk space, or python downloads disabled — see uv's output above). Install Python $floor+ yourself and re-run; nothing was modified."
        fi
    fi

    local interpreter
    interpreter="$("${UV_CMD[@]}" python find ">=$floor")" ||
        fail "uv reports Python >= $floor as available but cannot locate the interpreter. Re-run; if it persists, 'uv python list' shows what uv sees."

    # Belt and braces: whatever uv resolved is executed and checked against
    # the floor before it may be announced, so an unexpected resolution can
    # never be reported as satisfying package execution.
    python_meets_floor "$floor" "$interpreter" ||
        fail "uv resolved $interpreter, which does not satisfy the package's Python >= $floor requirement. Refusing to run the wizard on it; install Python $floor+ and re-run."

    UV_PACKAGE_PYTHON="$interpreter"
    ok "Package interpreter (Python >= $floor, resolved by uv): $interpreter"
}

# Resolve the interpreter for the installer's own helper execution against
# MAISTRO_HELPER_PYTHON_FLOOR. Falls back to uv — which needs no Python to
# install — when no host interpreter qualifies, so a machine with neither
# Python nor pip still bootstraps (#1821).
ensure_python() {
    [[ ${#PYTHON_CMD[@]} -gt 0 ]] && return 0

    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_meets_floor "$MAISTRO_HELPER_PYTHON_FLOOR" "$candidate"; then
            PYTHON_CMD=("$candidate")
            ok "Python found: $("$candidate" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
            return 0
        fi
    done

    if command -v py >/dev/null 2>&1 && python_meets_floor "$MAISTRO_HELPER_PYTHON_FLOOR" py -3; then
        PYTHON_CMD=(py -3)
        ok "Python found: $(py -3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
        return 0
    fi

    # No host interpreter satisfies the helper floor. Provision through uv:
    # the package floor is what is worth downloading, and a >= package-floor
    # interpreter also serves every helper.
    ensure_uv
    ensure_package_python
    PYTHON_CMD=("$UV_PACKAGE_PYTHON")
    ok "Helper interpreter: $("$UV_PACKAGE_PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))') at $UV_PACKAGE_PYTHON (provisioned by uv; no usable system Python)"
}
