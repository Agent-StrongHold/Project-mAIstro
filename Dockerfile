# maistro-engine API image — Chainguard/Wolfi (glibc, nonroot uid 65532, low CVE).
# Runtime uses the -dev variant so `git` can be apk-installed for the git tools;
# this image is not vuln-gated, so that trade is free (see runtime stage below).
#
# The RESEARCH browser surface (browser-use + Playwright + Chromium) — previously
# baked in here and "the single largest remaining CVE source" — has been split
# into Dockerfile.research. Chromium needs a Debian/X-libs base and can't run on
# distroless Wolfi, so shedding it is what lets this image go near-zero-CVE.
# maistro's browser client lazy-imports browser_use (tools/browser/client.py), so
# this image boots fine without it and the tool raises a clear, actionable error
# if invoked here — point deployments at Dockerfile.research for that role.
#
# Pattern mirrors Dockerfile.chainguard: a fat -dev builder produces a
# self-contained venv; the thin runtime copies only the venv + app sources.

# ─── fat Wolfi builder: self-contained venv (has shell/pip/apk, glibc) ───
# Pin the interpreter major/minor.  The identity stack includes native crypto
# dependencies (notably coincurve), so following `latest` across a Python major
# can turn an otherwise reproducible image into a source-build failure.
FROM python:3.13.15-slim-bookworm AS builder
WORKDIR /app
# uv is pinned to the release that generated the committed uv.lock: `uv export
# --locked` (below) is version-sensitive, and a floating installer is exactly
# the kind of unexamined resolution this image must not do (#348).
COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy

# The lock covers the whole workspace, so uv needs every member's
# pyproject.toml to verify `--locked` (lock-vs-pyproject drift fails the
# build). Only the two packages the image installs end up in the venv; the
# other members are build-time metadata and never reach the runtime stage.
COPY pyproject.toml uv.lock README.md ./
COPY packages/ packages/

# Export the exact locked requirement set for this image's dependency contract
# (maistro-server plus core's identity and observability extras), then install
# it with --require-hashes:
#   --locked    fails the build if uv.lock is out of date with any
#               pyproject.toml - lock drift is a red build, not a silent
#               re-resolution;
#   --no-dev    dev tooling never ships;
#   --no-emit-workspace
#               third-party pins only, every line carrying hashes; the
#               workspace members are installed separately (below) from the
#               copied sources, non-editable;
#   --require-hashes
#               every downloaded artifact is verified against the lock's
#               hashes, so an unresolvable locked artifact fails the build
#               instead of silently substituting whatever the index serves.
# This replaces the previous `pip install ./packages/... "alembic>=1.14" ...`
# line, which re-resolved every transitive at build time while the scanners
# inspected the lock - the shipped set and the scanned set were different
# sets (#348). alembic and psycopg[binary] need no explicit pin here: both are
# hard dependencies of maistro-server and arrive through the lock. The
# explicit anyio/httpx security floors are superseded the same way: the lock
# pins exact versions, so a rebuild cannot pick newer transitives.
# pydantic-ai-slim remains deliberately NOT installed: ADR-094 cut pydantic-ai
# from the codebase (zero src imports) and nothing in the lock names it. The
# old explicit `openai>=1.40,<2` pin is gone with it: the only openai import
# in the tree is the optional fallback inside core's browser tool, which this
# browser-free image does not ship - installing an SDK nothing can import was
# exactly the unexamined surface this change removes.
RUN uv export --locked --package maistro-server \
      --extra identity --extra observability \
      --no-dev --no-emit-workspace \
      --format requirements-txt --output-file /tmp/lock-requirements.txt \
 && uv venv --python 3.13 /app/venv \
 && uv pip install --python /app/venv/bin/python \
      --require-hashes --no-cache -r /tmp/lock-requirements.txt

# First-party packages: installed from the copied sources with --no-deps so
# nothing re-resolves - their third-party requirements are already installed,
# exact and hash-verified, from the export. Non-editable so the venv is fully
# self-contained (nothing from the source trees is needed on sys.path at
# runtime); the wheel build is local code, not dependency resolution.
RUN uv pip install --python /app/venv/bin/python --no-deps --no-cache \
      ./packages/maistro-core ./packages/maistro-server \
 && uv pip check --python /app/venv/bin/python \
 && /app/venv/bin/python -c "import importlib.metadata as m; assert m.version('maistro-core') and m.version('maistro-server'); import maistro_server.main; print('builder smoke ok')"

# ─── Wolfi runtime (-dev variant): low-CVE, has apk so `git` is available ───
# This image is NOT vuln-gated (only the hive-conductor image is trivy/grype
# scanned), so the -dev variant's slightly larger surface has no gate cost. It
# stays Wolfi (low-CVE) while providing the `git` binary the orchestrator's git
# tools (maistro.tools.git — used by orchestrator/waves/fan_in.py) exec directly;
# the previous distroless runtime shed git and broke those tools.
FROM python:3.13.15-slim-bookworm
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
# /usr/local/bin is on PATH so the static docker CLI (copied below) is found when
# the sandbox tool shells out to `docker run`.
ENV PATH="/app/venv/bin:/usr/local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /app/venv /app/venv
# On-disk assets the app reads at runtime (agent YAML, prompts, migrations).
COPY packages/maistro-core   packages/maistro-core
COPY packages/maistro-server packages/maistro-server
COPY alembic/ alembic/
COPY alembic.ini .
COPY pyproject.toml uv.lock README.md ./
# Static docker CLI (talks to a mounted /var/run/docker.sock) — a single static
# binary, no daemon. 29-cli ships a binary built with go1.26.8; older 27-cli
# binaries embedded go1.22.11 (CVE-2025-68121 crypto/tls + 21 HIGHs, trivy).
COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker
EXPOSE 8000
STOPSIGNAL SIGTERM
# Drop to an unprivileged numeric uid for runtime.
USER 65532
# exec-form, stdlib healthcheck — no curl in the image.
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live', timeout=4).status==200 else 1)"]
# The entrypoint owns schema migration under a PostgreSQL advisory lock, then
# execs uvicorn. Readiness is therefore impossible until the current schema is
# installed, including on an empty volume.
ENTRYPOINT ["python", "-m", "maistro_server.entrypoint"]
