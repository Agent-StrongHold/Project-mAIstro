# maistro-engine Docker Sandboxes (sbx) template.
#
# Build from the monorepo root via deploy/sbx/build.sh (which also produces
# the preseed tars this Dockerfile copies in):
#   ./deploy/sbx/build.sh
#
# Base: shell-docker = Docker's arbitrary-code sandbox template WITH a private
# Docker daemon inside the microVM — required because RSI's nested test
# sandbox (maistro.tools.sandbox.docker) shells out to `docker run`.
FROM docker/sandbox-templates:shell-docker

USER root

# git   — clone/branch/commit (host-side git in maistro.tools.git)
# gh    — PR creation when maistro-rsi runs with --open-prs
# python-is-python3 — builders' run_tests execs `python -m pytest`, and the
#   agent subprocess PATH is /usr/local/bin:/usr/bin:/bin (no venv), so both
#   the `python` name and the packages below must be system-level.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git gh python3 python3-venv python-is-python3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install the maistro packages from this repo's source, system-wide so they
# are on the builders _SAFE_ENV PATH. pytest/ruff are what the agent's
# run_tests/run_lint tools invoke.
COPY packages/ /opt/maistro-engine/packages/
RUN uv pip install --system --break-system-packages \
    /opt/maistro-engine/packages/maistro-core \
    /opt/maistro-engine/packages/maistro-bootstrap \
    /opt/maistro-engine/packages/maistro-evolve \
    /opt/maistro-engine/packages/maistro-rsi \
    "fastmcp>=2.0" \
    pytest ruff

# Preseeded images for the PRIVATE docker daemon: loaded at first boot by the
# kit's sbx-setup.sh. Baking tars (rather than pulling at runtime) is what
# keeps sandbox egress limited to GitHub + LiteLLM — no registry domains.
COPY deploy/sbx/template/preseed/ /opt/preseed/
COPY deploy/sbx/kit/sbx-setup.sh /opt/maistro/sbx-setup.sh
RUN chmod +x /opt/maistro/sbx-setup.sh

USER agent
