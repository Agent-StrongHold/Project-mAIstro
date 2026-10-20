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
# Digest-pinned (#349): a tag move must not change what installs every
# dependency without a repository diff. Refresh via Dependabot's docker
# ecosystem and record the new digest in quality/image-pins.json.
FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS builder
WORKDIR /app
# uv is the installer tool image — digest-pinned to the 0.12.21 release
# (#349): a `:latest` tag could swap the installer under every build with no
# repository diff, and an immutable digest cannot. The same pinned uv
# generated the committed uv.lock, and `uv export --locked` below is
# version-sensitive (#348).
COPY --from=ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 /uv /usr/local/bin/uv
# The venv is created below, and this PATH is what makes the prune step at
# the end of the builder stage act on the VENV's site-packages instead of the
# base image's: `python` resolves to /app/venv/bin/python once the venv
# exists, and the prune script prunes the purelib of the interpreter that
# runs it. Without this line the prune would patch the base image's
# site-packages, leave the venv's `examples` payload in place, and the
# build-time assertion would check an environment nobody ships.
ENV PATH="/app/venv/bin:$PATH" \
    UV_LINK_MODE=copy
ENV UV_HTTP_TIMEOUT=120
ENV UV_MAX_RETRIES=10

# The lock covers the whole workspace, so uv needs every member's
# pyproject.toml to verify `--locked` (lock-vs-pyproject drift fails the
# build). Only the three packages the image installs end up in the venv; the
# other members are build-time metadata and never reach the runtime stage.
#
# `extensions/` is copied for the same reason. The reference extension is a
# workspace member, and `uv export --locked --package ...` resolves the
# selection by building the workspace root — which fails without the
# member's pyproject.toml in the context ("reference-greeter references a
# workspace in tool.uv.sources ... but is not a workspace member"). The
# extension is not installed and never reaches the runtime stage; its
# metadata is what the lock check needs.
COPY pyproject.toml uv.lock README.md ./
COPY packages/ packages/
COPY extensions/ extensions/

# Export the exact locked requirement set for THIS image's contract, then
# install it with --require-hashes:
#   --package maistro-server --extra image
#               the image's contract is maistro-server's `image` extra: the
#               core surfaces the API server ships (identity, llm, sandbox,
#               observability), the Canvas package (#1825 — without it
#               `_wire_canvas_ability()` hit ImportError and every Canvas
#               route answered 503 forever), and the openai pin the image
#               has always carried. Naming the contract in the lock — rather
#               than in a pip command line in this file — is what makes "the
#               shipped dependency set is exactly the locked one" a property
#               of the repository instead of a promise;
#   --locked    fails the build if uv.lock is out of date with any
#               pyproject.toml — lock drift is a red build, not a silent
#               re-resolution;
#   --no-dev    dev tooling never ships. Without it `uv export` also exports
#               the workspace's dev dependency group, and the image would
#               carry pytest, ruff and mypy: the set the scanners audit
#               would no longer be the set the image ships;
#   --no-emit-workspace
#               third-party pins only, every line carrying hashes; the
#               workspace members are installed separately (below) from the
#               copied sources, non-editable;
#   --require-hashes
#               every downloaded artifact is verified against the lock's
#               hashes, so an unresolvable locked artifact fails the build
#               instead of silently substituting whatever the index serves.
RUN uv export --locked --package maistro-server --extra image \
      --no-dev --no-emit-workspace \
      --format requirements-txt --output-file /tmp/lock-requirements.txt \
 && uv venv --python 3.13 /app/venv \
 && uv pip install --python /app/venv/bin/python \
      --require-hashes --no-cache -r /tmp/lock-requirements.txt \
 && uv pip install --python /app/venv/bin/python --no-deps --no-cache \
      ./packages/maistro-core ./packages/maistro-server ./packages/maistro-canvas \
 && uv pip check --python /app/venv/bin/python \
 && /app/venv/bin/python -c "import importlib.metadata as m; assert m.version('maistro-core') and m.version('maistro-server') and m.version('maistro-canvas'); import maistro_server.main; print('builder smoke ok')"
# #406: the identity stack's locked bip-utils pins pytoniq-core-fork, whose
# wheel installs a generic top-level `examples` namespace package into this
# venv (examples/boc/*, examples/hashmaps/dict.py, examples/tl/*). It cannot
# be upgraded away (both PyPI releases ship it; bip-utils pins <0.2.0), and
# pip cannot exclude a subpath at install time, so the payload is pruned here
# — build-time and asserted in the same layer so a silent no-op prune fails
# the image build instead of the next audit. RECORD is rewritten, so the syft
# SBOM keeps recording the fork distribution (pkg:pypi/pytoniq-core-fork)
# with a file inventory that shows exactly what the patch removed.
COPY scripts/check-dependency-namespaces.py scripts/prune-dependency-namespaces.py /tmp/
RUN python /tmp/prune-dependency-namespaces.py \
    && python /tmp/check-dependency-namespaces.py --production \
    && rm -rf /tmp/check-dependency-namespaces.py /tmp/prune-dependency-namespaces.py

# ─── Wolfi runtime (-dev variant): low-CVE, has apk so `git` is available ───
# This image is NOT vuln-gated (only the hive-conductor image is trivy/grype
# scanned), so the -dev variant's slightly larger surface has no gate cost. It
# stays Wolfi (low-CVE) while providing the `git` binary the orchestrator's git
# tools (maistro.tools.git — used by orchestrator/waves/fan_in.py) exec directly;
# the previous distroless runtime shed git and broke those tools.
FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
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
# maistro-canvas is deliberately NOT copied here: the wheel carries no on-disk
# assets (pure Python), so the runtime must resolve `maistro_canvas` from the
# venv alone — which is exactly what the #1825 smoke asserts, on image contents
# only, with no network and no mounts. Copying the source tree would blur that
# proof boundary without serving any runtime read.
COPY alembic/ alembic/
COPY alembic.ini .
COPY config/ config/
COPY pyproject.toml uv.lock README.md ./
# Static docker CLI (talks to a mounted /var/run/docker.sock) — a single static
# binary, no daemon. 29-cli ships a binary built with go1.26.8; older 27-cli
# binaries embedded go1.22.11 (CVE-2025-68121 crypto/tls + 21 HIGHs, trivy).
# Digest-pinned (#349): the installer/tool image is as immutable as the base.
COPY --from=docker:29-cli@sha256:018edbc908e08fcc9dbf029c812c34251e9b4719e6f71ca0e5eae2a987d014ca /usr/local/bin/docker /usr/local/bin/docker
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
