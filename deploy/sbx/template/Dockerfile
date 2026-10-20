# maistro-engine Docker Sandboxes (sbx) template.
#
# Build from the monorepo root via deploy/sbx/build.sh (which also produces
# the preseed tars this Dockerfile copies in):
#   ./deploy/sbx/build.sh
#
# Base: shell-docker = Docker's arbitrary-code sandbox template WITH a private
# Docker daemon inside the microVM — required because RSI's nested test
# sandbox (maistro.tools.sandbox.docker) shells out to `docker run`.
FROM docker/sandbox-templates:shell-docker@sha256:1560168ac5fb9ce23d413c878349334c5845c07e264cd675d7867f0c78ad1761

USER root

# git   — clone/branch/commit (host-side git in maistro.tools.git)
# gh    — PR creation when maistro-rsi runs with --open-prs
# python-is-python3 — builders' run_tests execs `python -m pytest`, and the
#   agent subprocess PATH is /usr/local/bin:/usr/bin:/bin (no venv), so both
#   the `python` name and the packages below must be system-level.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git gh python3 python3-venv python-is-python3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# uv is the installer tool image — pinned to the 0.12.21 release by digest
# (#349): a `:latest` tag could swap the installer under every build, and an
# immutable digest cannot. The same pinned uv generated the committed uv.lock
# this image installs from (#348).
COPY --from=ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_MAX_RETRIES=10

# Install the maistro packages from this repo's LOCK, system-wide so they
# are on the builders _SAFE_ENV PATH (#348). Previously this was
# `uv pip install --system <source paths> "fastmcp>=2.0" pytest ruff`, which
# re-resolved every transitive at build time — the sandbox where agent-authored
# code runs shipped whichever snapshot PyPI served that day.
#
# The export selects the workspace root (dev dependency group included:
# pytest/ruff are what the agent's run_tests/run_lint tools invoke, and the
# sibling Dockerfile.tests image warms its cache from the same locked group)
# plus maistro-rsi/-evolve/-bootstrap so their closures (typer/rich/fastmcp)
# are locked too. `--no-emit-workspace` keeps third-party pins only, every line
# carrying hashes; the workspace members are installed from the copied sources
# with --no-deps — a local wheel build, not a dependency resolution.
#   --locked          fails the build on lock-vs-pyproject drift;
#   --require-hashes  fails the build on an unresolvable locked artifact.
COPY pyproject.toml uv.lock README.md /opt/maistro-engine/
COPY packages/ /opt/maistro-engine/packages/
# The workspace's extension members are not installed here, but their
# pyproject.toml is what the export needs: `uv export --locked --package ...`
# resolves the selection by building the workspace root, and that build
# fails without the member's metadata in the context ("reference-greeter
# references a workspace in tool.uv.sources ... but is not a workspace
# member").
COPY extensions/ /opt/maistro-engine/extensions/
RUN cd /opt/maistro-engine \
    && uv export --locked \
        --package maistro-workspace \
        --package maistro-rsi --package maistro-evolve --package maistro-bootstrap \
        --no-emit-workspace \
        --format requirements-txt --output-file /tmp/lock-requirements.txt \
    && uv pip install --system --break-system-packages \
        --require-hashes --no-cache -r /tmp/lock-requirements.txt \
    && uv pip install --system --break-system-packages --no-deps --no-cache \
        /opt/maistro-engine/packages/maistro-core \
        /opt/maistro-engine/packages/maistro-bootstrap \
        /opt/maistro-engine/packages/maistro-evolve \
        /opt/maistro-engine/packages/maistro-rsi \
    && uv pip check --system

# Preseeded images for the PRIVATE docker daemon: loaded at first boot by the
# kit's sbx-setup.sh. Baking tars (rather than pulling at runtime) is what
# keeps sandbox egress limited to GitHub + LiteLLM — no registry domains.
COPY deploy/sbx/template/preseed/ /opt/preseed/
COPY deploy/sbx/kit/sbx-setup.sh /opt/maistro/sbx-setup.sh
RUN chmod +x /opt/maistro/sbx-setup.sh

USER agent
