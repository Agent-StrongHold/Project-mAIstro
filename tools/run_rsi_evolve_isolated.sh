#!/usr/bin/env bash
set -euo pipefail
# Run the RSI *evolution* loop (genome population + hyper-mutator, ADR-070126-6386
# v2 stage 3) with the same COMPLETE isolation as tools/run_rsi_isolated.sh: the
# agents, git, tests, coverage, and the whole fitness scorecard execute inside an
# ephemeral container. The only outputs that leave are the population DB and the
# run log, written to a host-mounted dir OUTSIDE /workspace.
#
# Prereqs:
#   docker build -f Dockerfile.rsi-runner -t maistro-rsi-runner:latest .
#   A running LiteLLM gateway with a `code` model group (see the run wrapper).
#
# Usage:
#   tools/run_rsi_evolve_isolated.sh [CYCLES] [TARGET] [OUT_DIR] [MODELS] [GOAL]
#     CYCLES   evolution cycles                       (default 10)
#     TARGET   file the genomes compete to improve    (default mutate.py)
#     OUT_DIR  host dir for population.db + log       (default ./rsi-reports/evolve-<ts>)
#     MODELS   comma-separated gateway aliases        (default code)
#     GOAL     operator goal for the hyper-mutator    (default: test-first fixes)
#
# LINEAGE SURVIVES: population.db carries the evolved slots and the
# hyper-mutator's written learnings. Pass the SAME OUT_DIR to continue a lineage
# (seeding is top-up only — it never buries an existing population in randoms);
# the timestamped default starts a fresh one. Feed the champion into real
# tournament runs with `maistro_rsi run --genome-db <OUT_DIR>/population.db`.

CYCLES="${1:-10}"
TARGET="${2:-packages/maistro-evolve/src/maistro_evolve/mutate.py}"
OUT_DIR="${3:-}"
MODELS="${4:-code}"
GOAL="${5:-Produce accepted, high-composite code fixes: prefer adding real tests \
that raise coverage and assertion strength on the target module; fix real bugs \
test-first; never weaken existing docstrings.}"
IMAGE="${MAISTRO_RSI_IMAGE:-maistro-rsi-runner:latest}"

if [[ -z "$OUT_DIR" ]]; then
    OUT_DIR="$(pwd)/rsi-reports/evolve-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

# Locate the .env holding the gateway key: explicit override first, then the
# installer locations, then the repo-root .env (the documented
# `docker compose up -d` setup keeps the credentials there).
ENV_FILE="${MAISTRO_RSI_ENV_FILE:-}"
if [[ -z "$ENV_FILE" ]]; then
    for c in "/c/maistro/.env" "$HOME/.maistro/maistro-engine/.env" "C:/maistro/.env" "./.env"; do
        [[ -f "$c" ]] && { ENV_FILE="$c"; break; }
    done
fi
[[ -f "$ENV_FILE" ]] || { echo "error: no gateway .env found (set MAISTRO_RSI_ENV_FILE)"; exit 2; }

# Same network story as the run wrapper: the gateway is loopback-published, so
# join the compose network and use the fixed container name (not the `litellm`
# alias, which responses_callable rewrites to 127.0.0.1 for bare-host use).
NETWORK="${MAISTRO_RSI_NETWORK:-}"
if [[ -z "$NETWORK" ]]; then
    NETWORK="$(docker inspect maistro-litellm \
        --format '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' \
        2>/dev/null | head -1)"
    NETWORK="${NETWORK:-maistro_default}"
fi
GATEWAY_URL="${MAISTRO_RSI_GATEWAY_URL:-http://maistro-litellm:4000}"

# Windows/git-bash mount hygiene (see the run wrapper for the war story).
ENV_MOUNT="$ENV_FILE"
OUT_MOUNT="$OUT_DIR"
if command -v cygpath >/dev/null 2>&1; then
    ENV_MOUNT="$(cygpath -m "$ENV_FILE")"
    OUT_MOUNT="$(cygpath -m "$OUT_DIR")"
    export MSYS_NO_PATHCONV=1
fi

TEST_CMD='python -m pytest packages/maistro-evolve/tests packages/maistro-rsi/tests --ignore=packages/maistro-evolve/tests/benchmarks -q'
COV_ARGS='packages/maistro-evolve/tests packages/maistro-rsi/tests --ignore=packages/maistro-evolve/tests/benchmarks'
COV_SOURCE='packages/maistro-evolve/src,packages/maistro-rsi/src'

echo "RSI evolve (full isolation) -> image=$IMAGE cycles=$CYCLES target=$TARGET"
echo "  models=$MODELS network=$NETWORK gateway=$GATEWAY_URL"
echo "  out -> $OUT_DIR (population.db persists lineage)"

# GOAL travels as a docker env var, not interpolated into the inner command —
# it's documented free-form text, and shell syntax inside it must reach --goal
# literally, never be parsed by the inner bash. pipefail so a failing evolve is
# not masked by tee's exit 0.
exec docker run --rm \
    --network "$NETWORK" \
    --add-host=host.docker.internal:host-gateway \
    -v "${ENV_MOUNT}:/run/gateway.env:ro" \
    -v "${OUT_MOUNT}:/run/out" \
    -e "PYTHONPATH=packages/maistro-core/src:packages/maistro-evolve/src:packages/maistro-rsi/src:packages/maistro-bootstrap/src" \
    -e "RSI_GOAL=$GOAL" \
    "$IMAGE" \
    bash -lc "set -o pipefail; sed 's/\r\$//' /run/gateway.env > /tmp/gw.env; set -a; . /tmp/gw.env; set +a; \
        export LITELLM_URL='$GATEWAY_URL' LITELLM_BASE_URL='$GATEWAY_URL' LITELLM_PROXY_URL='$GATEWAY_URL'; \
        unset DB_PASSWORD LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_NEXTAUTH_SECRET LANGFUSE_SALT \
              API_KEYS MAISTRO_ACCESS_TOKEN OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY MISTRAL_API_KEY \
              GROQ_API_KEY CEREBRAS_API_KEY COHERE_API_KEY NVIDIA_API_KEY OPENROUTER_API_KEY SAMBANOVA_API_KEY \
              XAI_API_KEY DEEPSEEK_API_KEY TOGETHER_API_KEY FIREWORKS_API_KEY DEEPINFRA_API_KEY 2>/dev/null || true; \
        source /workspace/.venv/bin/activate && \
        python -m maistro_rsi evolve \
        --repo /workspace \
        --test-cmd '$TEST_CMD' \
        --target '$TARGET' \
        --cycles $CYCLES \
        --population 4 \
        --models '$MODELS' \
        --coverage-source '$COV_SOURCE' \
        --coverage-pytest-args '$COV_ARGS' \
        --agent-turns 6 \
        --db /run/out/population.db \
        --goal \"\$RSI_GOAL\" \
        --work-root /tmp/rsi-evo 2>&1 | tee /run/out/evolve.log"
