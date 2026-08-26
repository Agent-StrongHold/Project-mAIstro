#!/usr/bin/env bash
set -euo pipefail

# maistro-engine local installer.
#
# This script is intentionally conservative:
#   - it asks feature/deployment questions through maistro-install when a TTY exists;
#   - it preserves existing .env files and appends only missing runtime keys;
#   - it binds services to localhost by default;
#   - it starts the checked-out source tree with docker/podman compose.

# Where this script lives, so its helpers resolve whatever the caller's cwd is.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COMPOSE_FILE="${MAISTRO_COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${MAISTRO_ENV_FILE:-.env}"
BIND_HOST="${MAISTRO_BIND_HOST:-127.0.0.1}"
PORT="${MAISTRO_PORT:-8000}"
PLAN_DIR="${MAISTRO_INSTALL_PLAN_DIR:-.maistro-install}"
ANSWERS_FILE="${MAISTRO_INSTALL_ANSWERS:-}"
SKIP_WIZARD="${MAISTRO_SKIP_WIZARD:-0}"
START_STACK="${MAISTRO_START_STACK:-1}"
AUTO_INSTALL_DEPS="${MAISTRO_AUTO_INSTALL_DEPS:-0}"
MACOS_RUNTIME="${MAISTRO_MACOS_RUNTIME:-}"
INSTALL_CLI="${MAISTRO_INSTALL_CLI:-1}"
OPEN_BROWSER="${MAISTRO_OPEN_BROWSER:-1}"

# Container tag the generated image_pull compose pins to (E5/#298). get.sh
# exports this to match the release it just checked out; when install.sh is run
# directly out of a tree, derive it from the tag that tree is sitting on so a
# `git checkout v1.0.0 && ./install.sh` also pins correctly. `latest` is the
# fallback for a branch checkout, where no published image corresponds to the
# working tree anyway.
resolve_image_tag() {
    local tag=""
    if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
        tag="$(git describe --tags --exact-match 2>/dev/null || true)"
    fi
    printf '%s\n' "${tag:-latest}"
}
MAISTRO_IMAGE_TAG="${MAISTRO_IMAGE_TAG:-$(resolve_image_tag)}"
export MAISTRO_IMAGE_TAG

OS_NAME="$(uname -s)"
ARCH="$(uname -m)"
CHOSEN_RUNTIME=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PYTHON_CMD=()
UV_CMD=()
COMPOSE_CMD=()
COMPOSE_FILES=()

info() { echo -e "${BLUE}[maistro]${NC} $*"; }
ok() { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

is_macos() { [[ "$OS_NAME" == "Darwin" ]]; }

# True inside a WSL2 (or WSL1) distro. WSL sets WSL_DISTRO_NAME/WSL_INTEROP;
# /proc/version also names the Microsoft-patched kernel on every WSL release.
is_wsl() {
    [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]] && return 0
    grep -qi "microsoft" /proc/version 2>/dev/null
}

# Ask a yes/no question. Returns 0 for yes. Honours MAISTRO_AUTO_INSTALL_DEPS=1
# for non-interactive runs; refuses (returns 1) when there is no terminal.
confirm() {
    local prompt="$1"
    if [[ "$AUTO_INSTALL_DEPS" == "1" || "$AUTO_INSTALL_DEPS" == "true" ]]; then
        info "$prompt -> auto-confirmed (MAISTRO_AUTO_INSTALL_DEPS)"
        return 0
    fi

    local reply
    if [[ -t 0 ]]; then
        read -r -p "$prompt [y/N] " reply
    elif [[ -r /dev/tty ]]; then
        read -r -p "$prompt [y/N] " reply < /dev/tty
    else
        warn "No interactive terminal to confirm: $prompt"
        warn "Re-run with MAISTRO_AUTO_INSTALL_DEPS=1 to allow automatic installation."
        return 1
    fi
    [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

usage() {
    cat <<EOF
Usage: ./install.sh [options]

Options:
  --answers-file PATH  Use a maistro-install answers YAML file instead of prompts.
  --skip-wizard       Skip the feature/deployment questionnaire.
  --no-start          Generate/repair files but do not start compose.
  --no-cli            Do not install the host 'maistro' CLI (builders TUI).
  --no-open           Do not open the Conductor UI in a browser when ready.
  --plan-dir PATH     Directory for materialized install plan artifacts.
  -h, --help          Show this help.

Environment:
  MAISTRO_DIR, MAISTRO_PORT, MAISTRO_BIND_HOST, MAISTRO_INSTALL_ANSWERS,
  MAISTRO_SKIP_WIZARD, MAISTRO_START_STACK, MAISTRO_COMPOSE_FILE,
  MAISTRO_AUTO_INSTALL_DEPS (1 = install deps on macOS without prompting),
  MAISTRO_MACOS_RUNTIME (colima | docker-desktop = preselect, skip the prompt),
  MAISTRO_INSTALL_CLI (0 = do not install the host 'maistro' CLI),
  MAISTRO_OPEN_BROWSER (0 = do not open the Conductor UI when ready),
  MAISTRO_IMAGE_TAG (container tag the image_pull compose pins to; defaults to
    the release tag this checkout sits on, else 'latest').

macOS:
  When no container runtime is found, the installer asks whether to install
  Docker Desktop or Colima (via Homebrew) and starts it. Existing Docker
  Desktop / Colima installs are detected and started instead of reinstalling.

Windows:
  There is no native Windows path for this script — it needs bash. Run
  get.ps1 from PowerShell first; it sets up WSL2 + Ubuntu (handling the
  required reboot) and then runs this installer inside the distro.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --answers-file)
            [[ $# -ge 2 ]] || fail "--answers-file requires a path"
            ANSWERS_FILE="$2"
            shift 2
            ;;
        --skip-wizard)
            SKIP_WIZARD=1
            shift
            ;;
        --no-start)
            START_STACK=0
            shift
            ;;
        --no-cli)
            INSTALL_CLI=0
            shift
            ;;
        --no-open)
            OPEN_BROWSER=0
            shift
            ;;
        --plan-dir)
            [[ $# -ge 2 ]] || fail "--plan-dir requires a path"
            PLAN_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1"
            ;;
    esac
done

ensure_python() {
    if [[ ${#PYTHON_CMD[@]} -gt 0 ]]; then
        return
    fi

    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
        then
            PYTHON_CMD=("$candidate")
            ok "Python found: $("$candidate" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
            return
        fi
    done

    if command -v py >/dev/null 2>&1 && py -3 - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    then
        PYTHON_CMD=(py -3)
        ok "Python found: $(py -3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
        return
    fi

    fail "Python 3.11+ is required. Install Python, then re-run ./install.sh."
}

ensure_uv() {
    if [[ ${#UV_CMD[@]} -gt 0 ]]; then
        return
    fi

    if command -v uv >/dev/null 2>&1; then
        UV_CMD=(uv)
        ok "uv found: $(uv --version)"
        return
    fi

    ensure_python
    info "Installing uv into the current user's Python environment..."
    "${PYTHON_CMD[@]}" -m pip install --user --quiet uv

    if "${PYTHON_CMD[@]}" -m uv --version >/dev/null 2>&1; then
        UV_CMD=("${PYTHON_CMD[@]}" -m uv)
        ok "uv installed: $("${PYTHON_CMD[@]}" -m uv --version)"
        return
    fi

    if command -v uv >/dev/null 2>&1; then
        UV_CMD=(uv)
        ok "uv installed: $(uv --version)"
        return
    fi

    fail "uv installed, but the executable is not on PATH. Add the Python user scripts directory to PATH and retry."
}

random_secret() {
    local prefix="${1:-}"
    local bytes="${2:-32}"
    "${PYTHON_CMD[@]}" - "$prefix" "$bytes" <<'PY'
import secrets
import sys

prefix = sys.argv[1]
size = int(sys.argv[2])
print(prefix + secrets.token_urlsafe(size))
PY
}

env_has() {
    local key="$1"
    [[ -f "$ENV_FILE" ]] && grep -qE "^${key}=" "$ENV_FILE"
}

env_get() {
    local key="$1"
    if [[ -f "$ENV_FILE" ]]; then
        grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
    fi
}

# Every write to $ENV_FILE goes through scripts/secret_env.py (#357).
#
# `printf >>` and `cat >` create the file under the caller's umask -- 0644 on a
# typical system -- and the old code narrowed it with `chmod 600` only after
# every secret had already been written. Any process that could read the
# directory could read the credentials in that window, and a crash inside it
# left them world-readable for good.
#
# The helper creates a new file with O_CREAT|O_EXCL at 0600 and replaces an
# existing one through a same-directory temp file, so the mode is never wider
# than 0600 and an interrupted run leaves the previous file intact.
# Usage: secret_env_run <command> [args...]   -- $ENV_FILE is inserted as the
# path argument the CLI expects immediately after the command.
secret_env_run() {
    local command="$1"
    shift
    ensure_python
    "${PYTHON_CMD[@]}" "$SCRIPT_DIR/scripts/secret_env.py" "$command" "$ENV_FILE" "$@"
}

append_env_once() {
    local key="$1"
    local value="$2"
    if ! env_has "$key"; then
        secret_env_run append-once "$key" "$value"
    fi
}

# Like append_env_once but also replaces an existing blank value in place.
# Use for secrets that compose requires non-empty; a prior install may have
# written the key with an empty value as a placeholder.
fill_env_value() {
    secret_env_run set-key "$1" "$2" --only-if-blank
}

# Ensure API_KEYS (a JSON array) contains token. Preserves other existing keys.
ensure_api_keys_contains() {
    secret_env_run ensure-api-keys "$1"
}

# Insert or replace a key in $ENV_FILE. Unlike append_env_once this keeps the
# key's position and overwrites whatever value is there.
set_env_value() {
    secret_env_run set-key "$1" "$2"
}

append_provider_placeholders() {
    local key
    for key in \
        OPENAI_API_KEY \
        ANTHROPIC_API_KEY \
        GEMINI_API_KEY \
        CEREBRAS_API_KEY \
        COHERE_API_KEY \
        GROQ_API_KEY \
        MISTRAL_API_KEY \
        NVIDIA_API_KEY \
        OPENROUTER_API_KEY \
        SAMBANOVA_API_KEY \
        XAI_API_KEY \
        DEEPSEEK_API_KEY \
        TOGETHER_API_KEY \
        FIREWORKS_API_KEY \
        DEEPINFRA_API_KEY
    do
        append_env_once "$key" ""
    done
}

# The mode is established at creation now, not here (#357). This remains as a
# check: if the file somehow is not 0600 and owned by this user, say so loudly
# rather than assume. `check` never rewrites the file, so a refusal here is
# information, not a repair that might mask the cause.
verify_env_file() {
    secret_env_run check \
        || warn "$ENV_FILE did not pass the credential-file safety check above."
}

write_new_env() {
    local token db_pass litellm_key langfuse_secret langfuse_salt
    token="$(random_secret "" 32)"
    db_pass="$(random_secret "" 24)"
    litellm_key="$(random_secret "sk-" 32)"
    langfuse_secret="$(random_secret "" 32)"
    langfuse_salt="$(random_secret "" 24)"

    # Piped into `create`, which makes the file with O_CREAT|O_EXCL at 0600.
    # Exclusive on purpose: sync_env_file only calls this when the file is
    # absent, so a file appearing in between is something else writing to
    # the same path and must not be clobbered with credentials.
    secret_env_run create <<EOF
# Generated by install.sh. Do not commit this file.
# Regenerate with: rm .env && ./install.sh

# API access
MAISTRO_ACCESS_TOKEN=${token}
API_KEYS=["${token}"]
REQUIRE_AUTH=true
MAISTRO_BIND_HOST=${BIND_HOST}
MAISTRO_PORT=${PORT}

# Database
POSTGRES_PASSWORD=${db_pass}
DB_PASSWORD=${db_pass}
DATABASE_URL=postgresql://maistro:${db_pass}@postgres:5432/maistro

# LiteLLM gateway
LITELLM_MASTER_KEY=${litellm_key}
LITELLM_URL=http://litellm:4000
LITELLM_BASE_URL=http://litellm:4000
LITELLM_PROXY_URL=http://litellm:4000
LITELLM_API_BASE=http://litellm:4000/v1
LITELLM_API_KEY=${litellm_key}
LITELLM_PROXY_KEY=${litellm_key}

# Default model aliases. Change after adding at least one provider key below.
DEFAULT_MODEL=gemini/gemini-2.5-flash
CHAT_DEFAULT_MODEL=gemini/gemini-2.5-flash
MAISTRO_BUILDERS_MODEL=gemini/gemini-2.5-flash

# Langfuse
LANGFUSE_NEXTAUTH_SECRET=${langfuse_secret}
LANGFUSE_SALT=${langfuse_salt}
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=

# Provider API keys. Leave blank for providers you do not use.
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
CEREBRAS_API_KEY=
COHERE_API_KEY=
GROQ_API_KEY=
MISTRAL_API_KEY=
NVIDIA_API_KEY=
OPENROUTER_API_KEY=
SAMBANOVA_API_KEY=
XAI_API_KEY=
DEEPSEEK_API_KEY=
TOGETHER_API_KEY=
FIREWORKS_API_KEY=
DEEPINFRA_API_KEY=

# Evolve / benchmark defaults
BENCHMARK_FIDELITY=proxy
EOF

    verify_env_file
    ok "Generated $ENV_FILE with local credentials."
}

repair_existing_env() {
    local token db_pass litellm_key

    warn "$ENV_FILE exists; preserving values and appending missing installer keys."

    token="$(env_get MAISTRO_ACCESS_TOKEN)"
    if [[ -z "$token" ]]; then
        token="$(random_secret "" 32)"
        fill_env_value MAISTRO_ACCESS_TOKEN "$token"
    fi

    db_pass="$(env_get DB_PASSWORD)"
    if [[ -z "$db_pass" ]]; then
        db_pass="$(env_get POSTGRES_PASSWORD)"
    fi
    if [[ -z "$db_pass" ]]; then
        db_pass="$(random_secret "" 24)"
    fi

    litellm_key="$(env_get LITELLM_MASTER_KEY)"
    if [[ -z "$litellm_key" ]]; then
        litellm_key="$(random_secret "sk-" 32)"
    fi

    # API_KEYS is the server's actual auth list; ensure our token is in it
    # even if the key already existed (blank or with other entries).
    ensure_api_keys_contains "$token"
    append_env_once REQUIRE_AUTH "true"
    append_env_once MAISTRO_BIND_HOST "$BIND_HOST"
    append_env_once MAISTRO_PORT "$PORT"
    append_env_once POSTGRES_PASSWORD "$db_pass"
    fill_env_value DB_PASSWORD "$db_pass"
    append_env_once DATABASE_URL "postgresql://maistro:${db_pass}@postgres:5432/maistro"
    fill_env_value LITELLM_MASTER_KEY "$litellm_key"
    append_env_once LITELLM_URL "http://litellm:4000"
    append_env_once LITELLM_BASE_URL "http://litellm:4000"
    append_env_once LITELLM_PROXY_URL "http://litellm:4000"
    append_env_once LITELLM_API_BASE "http://litellm:4000/v1"
    fill_env_value LITELLM_API_KEY "$litellm_key"
    fill_env_value LITELLM_PROXY_KEY "$litellm_key"
    append_env_once DEFAULT_MODEL "gemini/gemini-2.5-flash"
    append_env_once CHAT_DEFAULT_MODEL "gemini/gemini-2.5-flash"
    append_env_once MAISTRO_BUILDERS_MODEL "gemini/gemini-2.5-flash"
    fill_env_value LANGFUSE_NEXTAUTH_SECRET "$(random_secret "" 32)"
    fill_env_value LANGFUSE_SALT "$(random_secret "" 24)"
    append_env_once LANGFUSE_PUBLIC_KEY ""
    append_env_once LANGFUSE_SECRET_KEY ""
    append_env_once BENCHMARK_FIDELITY "proxy"
    append_provider_placeholders
    verify_env_file
    ok "Repaired missing/blank installer keys in $ENV_FILE."
}

sync_env_file() {
    ensure_python
    if [[ -f "$ENV_FILE" ]]; then
        repair_existing_env
    else
        write_new_env
    fi
}

# Locate a compose front-end and set COMPOSE_CMD. Returns 1 if none is present.
# This only checks the CLI; daemon readiness is verified separately.
detect_compose_cmd() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        return 0
    fi

    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
        return 0
    fi

    if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(podman compose)
        return 0
    fi

    if command -v podman-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(podman-compose)
        return 0
    fi

    return 1
}

# True when the docker CLI exists and the daemon answers.
docker_daemon_ready() {
    command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

ensure_homebrew() {
    if command -v brew >/dev/null 2>&1; then
        ok "Homebrew found: $(brew --version | head -n 1)"
        return
    fi

    if ! confirm "Homebrew is not installed but is needed to install a container runtime. Install Homebrew now?"; then
        fail "Homebrew is required. Install it from https://brew.sh/ and re-run ./install.sh."
    fi

    info "Installing Homebrew (you may be prompted for your password)..."
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Put brew on PATH for this session (Apple Silicon and Intel locations).
    local brew_bin
    for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [[ -x "$brew_bin" ]]; then
            eval "$("$brew_bin" shellenv)"
            break
        fi
    done

    command -v brew >/dev/null 2>&1 \
        || fail "Homebrew installed but 'brew' is not on PATH. Open a new shell and re-run ./install.sh."
    ok "Homebrew installed: $(brew --version | head -n 1)"
}

wait_for_docker_daemon() {
    info "Waiting for the Docker daemon to become ready..."
    local attempts=0
    until docker info >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [[ $attempts -gt 60 ]]; then
            return 1
        fi
        sleep 2
    done
    ok "Docker daemon is ready."
}

start_colima() {
    info "Starting the Colima container VM (first run can take a minute)..."
    if ! colima start; then
        warn "colima start failed. Check 'colima status' and retry."
        return 1
    fi
    wait_for_docker_daemon
}

# Set CHOSEN_RUNTIME to "colima" or "docker-desktop". Honours
# MAISTRO_MACOS_RUNTIME, asks interactively, and defaults to Colima when
# non-interactive (headless and license-free).
choose_macos_runtime() {
    CHOSEN_RUNTIME=""
    case "$MACOS_RUNTIME" in
        colima | docker-desktop)
            CHOSEN_RUNTIME="$MACOS_RUNTIME"
            return 0
            ;;
        "") ;;
        *)
            warn "Ignoring unknown MAISTRO_MACOS_RUNTIME='$MACOS_RUNTIME' (use 'colima' or 'docker-desktop')."
            ;;
    esac

    if [[ "$AUTO_INSTALL_DEPS" == "1" || "$AUTO_INSTALL_DEPS" == "true" ]]; then
        info "Non-interactive run: defaulting to Colima (headless)."
        CHOSEN_RUNTIME="colima"
        return 0
    fi

    local reply
    if [[ -t 0 || -r /dev/tty ]]; then
        echo ""
        echo "Which container runtime should I install?"
        echo "  1) Colima         - free, headless, scriptable (recommended)"
        echo "  2) Docker Desktop - GUI app; may require a paid license for larger orgs"
        if [[ -t 0 ]]; then
            read -r -p "Choose [1/2] (default 1): " reply
        else
            read -r -p "Choose [1/2] (default 1): " reply < /dev/tty
        fi
    else
        info "No interactive terminal: defaulting to Colima."
        CHOSEN_RUNTIME="colima"
        return 0
    fi

    case "$reply" in
        2 | docker* | desktop | D | d) CHOSEN_RUNTIME="docker-desktop" ;;
        *) CHOSEN_RUNTIME="colima" ;;
    esac
}

install_colima_stack() {
    ensure_homebrew
    info "Installing Colima and the Docker CLI via Homebrew..."
    brew install colima docker docker-compose
    ok "Colima and Docker CLI installed."
    start_colima
}

install_docker_desktop() {
    ensure_homebrew
    info "Installing Docker Desktop via Homebrew (large download)..."
    brew install --cask docker
    ok "Docker Desktop installed."
    info "Launching Docker Desktop; accept any permission/license prompts it shows..."
    open -a Docker >/dev/null 2>&1 || warn "Could not launch Docker Desktop automatically."
    wait_for_docker_daemon \
        || warn "Docker Desktop did not finish starting. Complete its first-run setup, then re-run ./install.sh."
}

# Bring a Docker daemon up on macOS, installing one via Homebrew + Colima when
# nothing is present. Prefers an already-installed runtime before installing.
bootstrap_macos_runtime() {
    # Docker CLI is present but the daemon is down — try to start what's installed.
    if command -v docker >/dev/null 2>&1; then
        warn "The docker CLI is installed but the daemon is not responding."
        if command -v colima >/dev/null 2>&1; then
            start_colima
            return
        fi
        if [[ -d "/Applications/Docker.app" ]]; then
            info "Starting Docker Desktop..."
            open -a Docker >/dev/null 2>&1 || warn "Could not launch Docker Desktop."
            wait_for_docker_daemon \
                || warn "Docker Desktop did not finish starting. Open it manually, then re-run."
            return
        fi
        warn "Could not determine how to start the Docker daemon. Start Docker Desktop or run 'colima start', then re-run."
        return
    fi

    # Nothing installed — let the user pick a runtime, then install it.
    info "No container runtime detected on this Mac."
    if ! confirm "Install a container runtime now?"; then
        warn "Skipping container runtime install."
        warn "Install Docker Desktop (https://docker.com/products/docker-desktop) or Colima, then re-run ./install.sh."
        return
    fi

    choose_macos_runtime
    case "$CHOSEN_RUNTIME" in
        docker-desktop) install_docker_desktop ;;
        *) install_colima_stack ;;
    esac
}

# Start dockerd directly when there's no init system managing it — the common
# case inside a fresh WSL2 distro, which usually boots without systemd unless
# the user opted in via /etc/wsl.conf. Falls back through service/systemctl
# first since those are the supervised, restart-safe path when available.
start_dockerd_unsupervised() {
    if command -v service >/dev/null 2>&1 && service docker start >/dev/null 2>&1; then
        :
    elif command -v systemctl >/dev/null 2>&1 && systemctl start docker >/dev/null 2>&1; then
        :
    elif command -v dockerd >/dev/null 2>&1; then
        info "No init system managing dockerd (typical under WSL2); starting it directly."
        nohup dockerd >/var/log/dockerd.log 2>&1 &
        disown
    fi
    wait_for_docker_daemon
}

# Install Docker Engine via apt when nothing is present. This is the free,
# headless equivalent of the macOS Homebrew+Colima path — and is exactly what
# a fresh WSL2 Ubuntu distro needs, since it ships with no container runtime
# at all. Scoped to apt-based distros; other package managers fall through to
# the generic failure message in ensure_compose_runtime.
bootstrap_apt_docker_runtime() {
    if command -v docker >/dev/null 2>&1; then
        warn "The docker CLI is installed but the daemon is not responding."
        start_dockerd_unsupervised \
            || warn "Could not start the Docker daemon. Start it manually (e.g. 'sudo service docker start'), then re-run."
        return
    fi

    command -v apt-get >/dev/null 2>&1 || return 0

    info "No container runtime detected."
    if ! confirm "Install Docker Engine now via apt?"; then
        warn "Skipping container runtime install."
        warn "Install Docker Engine (https://docs.docker.com/engine/install/) or Podman, then re-run ./install.sh."
        return
    fi

    info "Installing Docker Engine via apt (you may be prompted for your password)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker.io docker-compose-plugin
    ok "Docker Engine installed."
    start_dockerd_unsupervised
}

ensure_compose_runtime() {
    if detect_compose_cmd; then
        # On macOS a docker CLI can exist with the daemon stopped; bring it up.
        if is_macos && [[ "${COMPOSE_CMD[0]}" == "docker" ]] && ! docker_daemon_ready; then
            bootstrap_macos_runtime
        elif [[ "${COMPOSE_CMD[0]}" == "docker" ]] && ! is_macos && ! docker_daemon_ready; then
            bootstrap_apt_docker_runtime
        fi
        ok "Compose runtime: ${COMPOSE_CMD[*]}"
        return
    fi

    if is_macos; then
        bootstrap_macos_runtime
    else
        bootstrap_apt_docker_runtime
    fi
    if detect_compose_cmd; then
        ok "Compose runtime: ${COMPOSE_CMD[*]}"
        return
    fi

    fail "No compose runtime found. Install Docker Desktop, Docker Engine with compose, or Podman, then retry."
}

run_feature_wizard() {
    if [[ "$SKIP_WIZARD" == "1" || "$SKIP_WIZARD" == "true" ]]; then
        warn "Skipping maistro-install questionnaire."
        return
    fi

    ensure_uv
    mkdir -p "$PLAN_DIR"

    local args=(run --project packages/maistro-bootstrap maistro-install --materialize-dir "$PLAN_DIR" --maistro-root "$PWD")
    if [[ -n "$ANSWERS_FILE" ]]; then
        args+=(--answers-file "$ANSWERS_FILE")
    fi

    info "Collecting feature, deployment, provider, observability, sandbox, and crypto choices..."
    if [[ -n "$ANSWERS_FILE" ]]; then
        "${UV_CMD[@]}" "${args[@]}"
    elif [[ -t 0 ]]; then
        "${UV_CMD[@]}" "${args[@]}"
    elif [[ -r /dev/tty ]]; then
        "${UV_CMD[@]}" "${args[@]}" < /dev/tty
    else
        fail "No interactive terminal available. Re-run with --answers-file or MAISTRO_SKIP_WIZARD=1."
    fi

    ok "Installer plan written to $PLAN_DIR."
}

http_ok() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -sf "$url" >/dev/null 2>&1 && return 0
    fi
    "${PYTHON_CMD[@]}" - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=4) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
}

# Read the wizard's delivery mode from the materialized plan (empty when the
# wizard was skipped). delivery.json is machine-written JSON, so a grep is safe.
delivery_mode() {
    local f="$PLAN_DIR/delivery.json"
    [[ -f "$f" ]] || return 0
    grep -o '"mode"[[:space:]]*:[[:space:]]*"[a-z_]*"' "$f" | head -1 | grep -o '[a-z_]*"$' | tr -d '"'
}

compose_files() {
    COMPOSE_FILES=(-f "$COMPOSE_FILE")
    COMPOSE_UP_ARGS=(up -d --build)
    local mode
    mode="$(delivery_mode)"
    if [[ "$mode" == "image_pull" ]]; then
        if [[ "${MAISTRO_IMAGE_PULL_READY:-0}" == "1" && -f "$PLAN_DIR/compose.install.yml" ]]; then
            # Standalone file: no build: keys anywhere, and no --build — pinned
            # images only. --project-directory keeps .env interpolation and
            # relative bind mounts anchored at the repo root.
            COMPOSE_FILES=(--project-directory "$PWD" -f "$PLAN_DIR/compose.install.yml")
            COMPOSE_UP_ARGS=(up -d)
            info "Delivery: image_pull — pinned images (tag ${MAISTRO_IMAGE_TAG}) from $PLAN_DIR/compose.install.yml (no local build)."
        else
            warn "delivery_mode=image_pull selected, but pinned images are not published yet."
            warn "Falling back to source build (identical runtime behavior, longer install)."
        fi
    fi
    local override="$PLAN_DIR/compose.override.yml"
    if [[ -f "$override" ]]; then
        COMPOSE_FILES+=(-f "$override")
    fi
}

# Record the host Docker socket path so the builder mount works regardless of
# runtime. Docker Desktop uses /var/run/docker.sock; Colima exposes it under
# ~/.colima/<profile>/docker.sock. Only meaningful for docker (not podman).
record_docker_sock() {
    command -v docker >/dev/null 2>&1 || return 0

    local host path
    host="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    [[ -n "$host" ]] || host="${DOCKER_HOST:-}"

    case "$host" in
        unix://*) path="${host#unix://}" ;;
        "") path="/var/run/docker.sock" ;;
        *)
            warn "Docker endpoint '$host' is not a unix socket; the builder docker.sock mount may not apply."
            warn "Set MAISTRO_DOCKER_SOCK in $ENV_FILE manually if the builder sandbox needs it."
            return 0
            ;;
    esac

    if [[ "$path" != "/var/run/docker.sock" ]]; then
        info "Detected non-default Docker socket at $path; recording MAISTRO_DOCKER_SOCK."
        upsert_env MAISTRO_DOCKER_SOCK "$path"
    fi
}

# On ARM64 (Apple Silicon), best-effort check that the pinned third-party images
# publish arm64 manifests. Locally-built images (engine, conductor) are native.
# Advisory only — missing manifests just mean QEMU emulation, never a hard stop.
report_arch() {
    case "$ARCH" in
        arm64 | aarch64) ;;
        *) return 0 ;;
    esac
    command -v docker >/dev/null 2>&1 || return 0

    info "ARM64 host detected; checking base images for native arm64 builds..."
    local img missing=0
    for img in \
        "pgvector/pgvector:pg17" \
        "ghcr.io/berriai/litellm:main-latest" \
        "langfuse/langfuse:2"
    do
        if docker manifest inspect "$img" 2>/dev/null | grep -q "arm64"; then
            ok "arm64 image available: $img"
        else
            warn "No confirmed arm64 manifest for $img — Docker may emulate it (slower)."
            missing=$((missing + 1))
        fi
    done
    [[ $missing -eq 0 ]] || warn "Emulated images run via QEMU; functional but slower on Apple Silicon."
}

start_engine() {
    if [[ "$START_STACK" == "0" || "$START_STACK" == "false" ]]; then
        warn "Skipping compose start because --no-start or MAISTRO_START_STACK=0 was set."
        return
    fi

    ensure_compose_runtime
    record_docker_sock
    report_arch
    compose_files
    info "Starting maistro-engine..."
    "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" "${COMPOSE_UP_ARGS[@]}"

    info "Waiting for engine health..."
    local attempts=0
    until http_ok "http://${BIND_HOST}:${PORT}/health/live" || http_ok "http://${BIND_HOST}:${PORT}/health"; do
        attempts=$((attempts + 1))
        if [[ $attempts -gt 60 ]]; then
            fail "Engine did not become healthy. Check: ${COMPOSE_CMD[*]} ${COMPOSE_FILES[*]} logs maistro-engine"
        fi
        sleep 2
    done
    ok "Engine healthy."

    info "Waiting for Conductor UI health..."
    attempts=0
    until http_ok "http://${BIND_HOST}:${HIVE_PORT:-8101}/health/ready"; do
        attempts=$((attempts + 1))
        if [[ $attempts -gt 60 ]]; then
            fail "Conductor did not become ready. Check: ${COMPOSE_CMD[*]} ${COMPOSE_FILES[*]} logs hive-conductor"
        fi
        sleep 2
    done
    ok "Conductor healthy."
}

# Best-effort secure delete for the staged credentials file: overwrite with
# zeros, then unlink. Not a guarantee on journaling/COW filesystems, but it
# beats leaving plaintext passwords recoverable after a plain rm.
shred_file() {
    local f="$1" size
    [[ -f "$f" ]] || return 0
    size="$(wc -c < "$f" | tr -d ' ')"
    head -c "$size" /dev/zero > "$f" 2>/dev/null || true
    rm -f "$f"
}

# First-run provisioning from the terminal (SPEC-072726-3439 Phase 3): POST
# the wizard-staged credentials to /v1/setup/complete, show the mnemonic
# once, then shred the file. A 409 (already provisioned) is terminal
# consumption — shred there too; only pre-commit failures keep the file for
# retry. Without a staged file, account setup continues in the web UI.
bootstrap_first_run() {
    local creds="${MAISTRO_BOOTSTRAP_CREDENTIALS_FILE:-$PLAN_DIR/bootstrap-credentials.json}"
    local base="http://${BIND_HOST}:${HIVE_PORT:-8101}"

    if [[ ! -f "$creds" ]]; then
        info "No staged bootstrap credentials — account setup continues in the web UI."
        return
    fi
    if [[ "$START_STACK" == "0" || "$START_STACK" == "false" ]]; then
        warn "Stack not started; leaving $creds staged for the next run."
        return
    fi

    ensure_python

    if curl -sf "$base/v1/setup/status" 2>/dev/null | grep -q '"setup_complete"[[:space:]]*:[[:space:]]*true'; then
        info "Setup already complete — shredding staged credentials (consumed)."
        shred_file "$creds"
        return
    fi

    info "Creating first-run accounts from staged credentials..."
    local resp_file="$PLAN_DIR/.setup-response.json" http_code
    http_code="$(curl -sS -o "$resp_file" -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        --data-binary "@$creds" \
        "$base/v1/setup/complete" 2>/dev/null || echo 000)"

    case "$http_code" in
        200)
            ok "Admin and daily-driver accounts created."
            "${PYTHON_CMD[@]}" - "$resp_file" <<'PY'
import json, sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
config = data.get("config", {})
if not config.get("vault_initialized", False):
    print("[warn] vault was not initialized (age missing?) — secrets stay env-based.")
mnemonic = data.get("mnemonic")
if mnemonic:
    words = mnemonic if isinstance(mnemonic, list) else str(mnemonic).split()
    bar = "=" * 64
    print()
    print(bar)
    print("  RECOVERY PHRASE — shown ONCE. Write these 24 words down now.")
    print(bar)
    for i in range(0, len(words), 6):
        print("   " + "  ".join(f"{n+1:2}.{w}" for n, w in enumerate(words[i:i+6], start=i)))
    print(bar)
    if not config.get("identity_persisted", False):
        print("  [warn] The seed was NOT persisted to the vault — this phrase")
        print("  is the ONLY copy of your identity root.")
    print()
PY
            if grep -q '"mnemonic"' "$resp_file" && [[ -t 0 || -r /dev/tty ]]; then
                local confirmed=""
                while [[ "$confirmed" != "yes" ]]; do
                    if [[ -t 0 ]]; then
                        read -r -p "Type 'yes' once you have written the phrase down: " confirmed
                    else
                        read -r -p "Type 'yes' once you have written the phrase down: " confirmed < /dev/tty
                    fi
                done
            fi
            shred_file "$resp_file"
            shred_file "$creds"
            ok "Staged credentials shredded. Log in to the UI with your admin or daily-driver account."
            ;;
        409)
            info "Setup already complete (409) — shredding staged credentials (consumed)."
            shred_file "$resp_file"
            shred_file "$creds"
            ;;
        *)
            warn "Bootstrap failed (HTTP $http_code). Credentials kept at $creds for retry."
            # stderr redirected before stdin, so a missing $resp_file is silent
            # (a failed input redirect reports on the stderr in effect at the time).
            warn "Response: $(head -c 400 2>/dev/null < "$resp_file")"
            warn "Retry with: curl -sS -H 'Content-Type: application/json' --data-binary @$creds $base/v1/setup/complete"
            ;;
    esac
}

# Write operator recovery commands next to the plan artifacts and echo the
# path in print_success (SPEC-072726-3439 Phase 3).
write_recovery_md() {
    mkdir -p "$PLAN_DIR"
    local compose_line="${COMPOSE_CMD[*]:-docker compose} ${COMPOSE_FILES[*]:--f $COMPOSE_FILE}"
    cat > "$PLAN_DIR/RECOVERY.md" <<EOF
# Maistro recovery & operations

Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ"). All commands run
from the repo root: $PWD

| Action   | Command |
|----------|---------|
| Status   | \`$compose_line ps\` |
| Logs     | \`$compose_line logs -f --tail=200\` |
| Restart  | \`$compose_line restart\` |
| Stop     | \`$compose_line down\` |
| Start    | \`$compose_line up -d\` |
| Backup   | \`$compose_line exec postgres pg_dump -U maistro maistro > backup.sql\` |
| Teardown | \`$compose_line down -v\`  (deletes all volumes/data) |

A generated Makefile with the same targets lives at \`$PLAN_DIR/Makefile\`.

## Identity recovery

If crypto identity was enabled at setup, the 24-word recovery phrase shown
once during install can re-materialize the identity root. Keep it offline.

## Re-running the installer

Re-running ./install.sh over a healthy install performs updates only — it
will not overwrite accounts (setup is one-shot) and will not re-prompt for
credentials.
EOF
    ok "Recovery commands written to $PLAN_DIR/RECOVERY.md"
}

# Install the host-side `maistro` CLI so `maistro builders` (the interactive
# coding TUI) works after a curl install. Installs from the checked-out source:
# maistro-core (the CLI + entrypoint) plus maistro-bootstrap (builders agent
# loop/session/sandbox, and the typer/rich the CLI imports), with textual +
# anthropic for the TUI. This sidesteps the maistro-core[builders] extra, which
# would try to resolve maistro-bootstrap from PyPI.
install_cli() {
    if [[ "$INSTALL_CLI" == "0" || "$INSTALL_CLI" == "false" ]]; then
        warn "Skipping host CLI install (--no-cli or MAISTRO_INSTALL_CLI=0)."
        return
    fi

    local core="$PWD/packages/maistro-core"
    local bootstrap="$PWD/packages/maistro-bootstrap"
    local rsi="$PWD/packages/maistro-rsi"
    local evolve="$PWD/packages/maistro-evolve"
    if [[ ! -d "$core" || ! -d "$bootstrap" ]]; then
        warn "Cannot find maistro-core/maistro-bootstrap sources; skipping CLI install."
        return
    fi

    ensure_uv
    info "Installing the 'maistro' CLI on the host (enables the 'maistro builders' TUI)..."
    # The package to install commands from is the positional argument (a path is
    # accepted); --with adds the extra requirements the CLI/TUI need at runtime.
    local -a with_args=(
        --with "$bootstrap"
        --with "textual>=0.61"
        --with "anthropic>=0.28"
    )
    # Add the RSI self-improvement stack + its objective code-quality toolchain so
    # `python -m maistro_rsi run --fitness` can score candidates (ruff/mypy/bandit/
    # radon/pylint/interrogate/complexipy/vulture/coverage must be importable, or
    # the fitness gates silently degrade to "unenforced").
    [[ -d "$rsi" ]] && with_args+=(--with "$rsi")
    [[ -d "$evolve" ]] && with_args+=(--with "$evolve")
    local qtool
    for qtool in ruff mypy bandit radon pylint interrogate complexipy vulture coverage; do
        with_args+=(--with "$qtool")
    done
    if "${UV_CMD[@]}" tool install --force "${with_args[@]}" "$core"; then
        ok "Installed the 'maistro' CLI (+ RSI fitness toolchain)."
        # Ensure the uv tool bin dir (e.g. ~/.local/bin) is on PATH for new shells.
        "${UV_CMD[@]}" tool update-shell >/dev/null 2>&1 || true
        persist_repo_root
    else
        warn "Could not install the 'maistro' CLI. Retry later from the repo root with:"
        warn "  uv tool install --with packages/maistro-bootstrap --with textual --with anthropic packages/maistro-core"
    fi
}

# `maistro builders` runs on the bare host, not in a container, so it needs to
# know where this checkout (and its .env / LiteLLM gateway) lives even when
# run from some other project directory later. Persist MAISTRO_REPO_ROOT so
# new shells pick it up without the user exporting it manually every time.
persist_repo_root() {
    local root="$PWD"
    if command -v setx >/dev/null 2>&1; then
        # Windows (including Git Bash/MSYS) — persists via the registry,
        # picked up by shells opened after this one.
        setx MAISTRO_REPO_ROOT "$root" >/dev/null 2>&1 || true
    fi
    local rc line="export MAISTRO_REPO_ROOT=\"$root\""
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        [[ -f "$rc" ]] || continue
        grep -q "MAISTRO_REPO_ROOT=" "$rc" 2>/dev/null && continue
        {
            echo ""
            echo "# maistro-engine install.sh — lets 'maistro builders' find this checkout from any directory."
            echo "$line"
        } >> "$rc"
    done
    ok "Set MAISTRO_REPO_ROOT=$root for new shells (open a new terminal for it to take effect)."
}

print_success() {
    local token
    token="$(env_get MAISTRO_ACCESS_TOKEN)"

    echo ""
    echo "maistro-engine is ready"
    echo "  Engine API:  http://${BIND_HOST}:${PORT}"
    echo "  Conductor:   http://${BIND_HOST}:${HIVE_PORT:-8101}  (chat, DAGs, deck builder)"
    echo "  Token:       ${token}"
    echo "  Install dir: $PWD"
    echo "  Plan dir:    $PLAN_DIR"
    echo ""
    echo "Commands:"
    echo "  Logs:  ${COMPOSE_CMD[*]:-docker compose} ${COMPOSE_FILES[*]:--f $COMPOSE_FILE} logs -f maistro-engine"
    echo "  Stop:  ${COMPOSE_CMD[*]:-docker compose} ${COMPOSE_FILES[*]:--f $COMPOSE_FILE} down"
    echo ""
    if [[ "$INSTALL_CLI" != "0" && "$INSTALL_CLI" != "false" ]]; then
        echo "Local CLI:"
        echo "  maistro builders   Interactive coding TUI (open a new terminal first — picks up the LiteLLM gateway automatically)"
        echo "  maistro --help     All commands"
        echo "  (If 'maistro' is not found, run 'uv tool update-shell' and open a new shell.)"
        echo ""
    fi
    echo "Security note: services are bound to localhost by default. Do not set"
    echo "MAISTRO_BIND_HOST=0.0.0.0 until auth, network, and sandbox exposure have been reviewed."
    echo ""
}

# Open the Conductor UI once the stack is up. macOS uses `open`; under WSL
# there's no X server, so hand off to the Windows side (explorer.exe/cmd.exe);
# plain Linux uses `xdg-open` when a display is present. Skipped with
# --no-open / MAISTRO_OPEN_BROWSER=0.
open_browser() {
    [[ "$OPEN_BROWSER" == "0" || "$OPEN_BROWSER" == "false" ]] && return 0
    [[ "$START_STACK" == "0" || "$START_STACK" == "false" ]] && return 0

    local url="http://${BIND_HOST}:${HIVE_PORT:-8101}"
    if is_macos && command -v open >/dev/null 2>&1; then
        info "Opening the Conductor UI: $url"
        open "$url" >/dev/null 2>&1 || true
    elif is_wsl; then
        info "Opening the Conductor UI on the Windows side: $url"
        if command -v explorer.exe >/dev/null 2>&1; then
            explorer.exe "$url" >/dev/null 2>&1 || true
        elif command -v cmd.exe >/dev/null 2>&1; then
            cmd.exe /c start "$url" >/dev/null 2>&1 || true
        fi
    elif command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
        info "Opening the Conductor UI: $url"
        xdg-open "$url" >/dev/null 2>&1 || true
    fi
}

main() {
    echo ""
    echo "maistro-engine installer"
    echo "security-first agent runtime"
    echo ""

    [[ -f "$COMPOSE_FILE" ]] || fail "Missing $COMPOSE_FILE. Run this from the maistro-engine repo root."
    run_feature_wizard
    sync_env_file
    start_engine
    bootstrap_first_run
    write_recovery_md
    install_cli
    print_success
    open_browser
}

main
