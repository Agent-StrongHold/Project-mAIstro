# Build from monorepo root:
#   docker build -f packages/hive-conductor/Dockerfile . -t hive-conductor
# Or via docker-compose (context is set to monorepo root in docker-compose.yml).
#
# The Conductor identity contract is pinned to CPython 3.13: coincurve 21.0.0
# publishes the required Linux wheels for cp313, but not cp314. Keep the exact
# patch version here so a moving base tag cannot silently change that contract.
# A fat builder makes a self-contained venv; the runtime copies only the venv and
# app sources.
# ---- frontend build ----
# Digest-pinned (#349); node:22-alpine resolved to this index digest 2026-09-30.
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS frontend
WORKDIR /build
COPY packages/hive-conductor/frontend/package.json packages/hive-conductor/frontend/package-lock.json ./
RUN npm ci
COPY packages/hive-conductor/frontend/ ./
ARG VITE_POC_MODE=
ENV VITE_POC_MODE=${VITE_POC_MODE}
# Lets the gateway serve Hive at a sub-path (e.g. VITE_BASE_PATH=/pm/) without
# breaking asset URLs. Defaults to / so standalone builds are unaffected.
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
# Perceived-load telemetry (#1420). Collection stays OFF unless the builder
# sets VITE_RUM_ENABLED=true (and the runtime sets RUM_INGEST_ENABLED=true):
# both sides must opt in before any observation exists. docs/RUM.md is the
# contract; the sample rate defaults to 1.0 and the build id defaults to
# "dev" when the builder does not name the build.
ARG VITE_RUM_ENABLED=
ENV VITE_RUM_ENABLED=${VITE_RUM_ENABLED}
ARG VITE_RUM_SAMPLE_RATE=1
ENV VITE_RUM_SAMPLE_RATE=${VITE_RUM_SAMPLE_RATE}
ARG VITE_RUM_BUILD_ID=
ENV VITE_RUM_BUILD_ID=${VITE_RUM_BUILD_ID}
RUN npm run build

# ---- age build ----
# age v1.3.1 remains the latest upstream release, but its prebuilt Linux binary
# was compiled before several 2026 Go/x/crypto and stdlib fixes, and no released
# age artifact embeds a toolchain carrying the 2026 stdlib fixes (trivy:
# CVE-2026-78667/78669/97031 HIGH in stdlib 1.25.x). Build the exact immutable
# release tag ourselves with a patched Go toolchain/dependency set so the
# runtime does not inherit vulnerabilities from an otherwise-current source
# release. The release tag resolves to b8564ad; fail if upstream ever disagrees.
FROM golang:1.27.2-alpine@sha256:f92b6ef800e499660581efdabdf25d9d817a9d124eaf900924f0504e7e27e12d AS agebuild
ARG AGE_VERSION=1.3.1
ARG AGE_COMMIT_SHORT=b8564ad
RUN apk add --no-cache git && \
    git clone --branch "v${AGE_VERSION}" --depth 1 https://github.com/FiloSottile/age.git /src/age && \
    cd /src/age && \
    test "$(git rev-parse --short=7 HEAD)" = "${AGE_COMMIT_SHORT}" && \
    go get golang.org/x/crypto@v0.55.0 && \
    mkdir -p /out && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/age ./cmd/age && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/age-keygen ./cmd/age-keygen

# ---- builder: self-contained venv (has shell/pip) ----
# Digest-pinned (#349); shared with the runtime stage below so both resolve to
# the same CPython build.
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS pybuild
WORKDIR /app
# uv is the installer tool image — pinned to the 0.12.21 release by digest
# (#349); a `:latest` tag could swap the installer under every build with no
# repository diff, and an immutable digest cannot. The same pinned uv
# generated the committed uv.lock this image installs from (#348).
COPY --from=ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 /uv /usr/local/bin/uv
ENV PATH="/app/venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_MAX_RETRIES=10
# The lock covers the whole workspace, so uv needs every member's
# pyproject.toml to verify `--locked` (lock-vs-pyproject drift fails the
# build). Only the five members the image installs end up in the venv; the
# other members are build-time metadata and never reach the runtime stage.
# `extensions/` is copied for the same reason: the reference extension is a
# workspace member, and the export resolves its selection by building the
# workspace root, which fails without the member's pyproject.toml in the
# context. It is never installed and never reaches the runtime stage.
COPY pyproject.toml uv.lock README.md ./
COPY packages/ packages/
COPY extensions/ extensions/
# Install the exact locked requirement set for this image's dependency contract
# (hive-conductor over maistro-core[bcrypt,identity] + design/evolve/bootstrap
# + canvas), then the workspace members themselves, non-editable, --no-deps:
#   --locked   fails the build if uv.lock is out of date with any
#              pyproject.toml — lock drift is a red build, not a silent
#              re-resolution;
#   --require-hashes
#              every downloaded artifact is verified against the lock's
#              hashes, so an unresolvable locked artifact fails the build
#              instead of silently substituting whatever the index serves;
#   --no-config
#              the install consumes the export and nothing else. The root
#              pyproject.toml carries a `constraint-dependencies` floor
#              (aiohttp>=3.14.4 — the CVE-2026-111064 floor the pip-audit
#              gate needs over the dev environment), and `uv pip install`
#              run inside the project folds that floor into the install
#              request. `--require-hashes` rejects an unpinned requirement,
#              so the build would fail on a floor for a package this image
#              does not ship aiohttp for. The floor still binds where it
#              belongs: `uv lock` and `uv sync` read the manifest, and the
#              lock is what this image installs.
# This replaces the previous `pip install /packages/... -r
# backend/requirements.txt`, which re-resolved every transitive at build time
# from range floors while the scanners audited the lock (#348). The identity
# wheel contract below is unchanged in kind and now enforced by the lock
# itself: the lock's bip-utils/coincurve/pynacl pins ARE the contract, the ARGs
# assert them, and the smoke test at the end of this stage fails the build on
# any mismatch. backend/requirements.txt remains the CI test resolution (the
# backend suite installs only that file); the shipped image no longer reads it,
# so the test tools it carried (pytest, hypothesis) also leave the image.
# setuptools stays an EXACT pin (the lock's own setuptools version, satisfying
# the >= 78.1.1 security floor) — a pin, not a resolution.
ARG BIP_UTILS_VERSION=2.12.2
ARG COINCURVE_VERSION=21.0.0
ARG PYNACL_VERSION=1.6.2
RUN uv export --locked --package hive-conductor \
      --no-dev --no-emit-workspace \
      --format requirements-txt --output-file /tmp/lock-requirements.txt \
 && uv venv --python 3.13 /app/venv \
 && uv pip install --python /app/venv/bin/python \
      --no-config --require-hashes --no-cache -r /tmp/lock-requirements.txt \
 && uv pip install --python /app/venv/bin/python --no-deps --no-cache \
      ./packages/maistro-core ./packages/maistro-bootstrap ./packages/maistro-canvas \
      ./packages/maistro-design ./packages/maistro-evolve \
 && uv pip install --python /app/venv/bin/python --no-cache "setuptools==84.0.0" \
 && uv pip check --python /app/venv/bin/python
# Tracing is opt-in at build time, and this is the door (#668).
#
# `backend/adapters/telemetry_langfuse.py` speaks OTLP using the OpenTelemetry
# API, SDK and HTTP exporter. Those are `maistro-core[observability]`, and the
# image deliberately does not carry an exporter it will not use -- the adapter
# is inert unless OTEL_EXPORTER_OTLP_ENDPOINT is set. But #514 left no way to
# opt *in* either: setting the endpoint on a container built from this file
# could not work, and the adapter reported that as tracing being switched off.
#
# Default 0, so the ordinary image is unchanged in size and contents. A build
# that wants tracing says so:
#
#     docker build --build-arg INSTALL_OBSERVABILITY=1 ...
ARG INSTALL_OBSERVABILITY=0
# Same lock discipline as the base install: the observability profile is a
# second `uv export --locked` of the SAME package (its `[observability]`
# extra), so the exporter dists are the locked, hash-verified pins too (#348).
RUN if [ "$INSTALL_OBSERVABILITY" = "1" ]; then \
        uv export --locked --package hive-conductor --extra observability \
          --no-dev --no-emit-workspace \
          --format requirements-txt --output-file /tmp/lock-requirements-otel.txt \
        && uv pip install --python /app/venv/bin/python --no-config --require-hashes --no-cache \
             -r /tmp/lock-requirements-otel.txt \
        && uv pip check --python /app/venv/bin/python; \
    fi

# #406: bip-utils pins pytoniq-core-fork, whose wheel installs a generic
# top-level `examples` namespace package. Both PyPI releases of the fork ship
# it and pip cannot exclude a subpath, so the payload is pruned at build time
# and the whole environment is then re-checked in production mode — placed
# AFTER every install that can touch site-packages (identity stack, backend
# requirements, optional observability), because a gate that runs before the
# last dependency lands does not gate that dependency. A silent no-op prune
# fails this build, not the next audit. RECORD is rewritten, so the syft SBOM
# keeps the fork provenance (pkg:pypi/pytoniq-core-fork) with the pruned file
# inventory.
COPY scripts/check-dependency-namespaces.py scripts/prune-dependency-namespaces.py /tmp/
RUN python /tmp/prune-dependency-namespaces.py \
    && python /tmp/check-dependency-namespaces.py --production \
    && rm -rf /tmp/check-dependency-namespaces.py /tmp/prune-dependency-namespaces.py
# The image build is the first contract test: exercise the same identity import
# and derivation that setup uses, and fail if a native wheel was not selected.
RUN python -c "import importlib.metadata as m, sys; from maistro.identity import ConductorSeed; assert sys.version_info[:3] == (3, 13, 16), sys.version; assert m.version('bip-utils') == '${BIP_UTILS_VERSION}'; assert m.version('coincurve') == '${COINCURVE_VERSION}'; assert m.version('pynacl') == '${PYNACL_VERSION}'; seed = ConductorSeed.generate(); assert seed.did_key().startswith('did:key:z'); seed.zero()" && \
    if [ "$INSTALL_OBSERVABILITY" = "1" ]; then \
        python -c "import opentelemetry, opentelemetry.sdk, opentelemetry.exporter.otlp"; \
    fi
# Seed dir for conductor state (SQLite/vault/state). Created under the writable
# /app workdir because the -dev base runs as nonroot and cannot write to /. The
# runtime stage COPY --chown's it to /data so a mounted named volume inherits
# writable nonroot ownership.
RUN mkdir -p /app/state_seed

# ---- thin runtime: same pinned CPython ABI, nonroot ----
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
WORKDIR /app
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONPATH=/app/backend:/app \
    CONDUCTOR_DATA_DIR=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=pybuild /app/venv /app/venv
COPY --from=agebuild /out/age /out/age-keygen /usr/bin/
COPY packages/hive-conductor/backend/ /app/backend/
COPY packages/hive-conductor/cage/ /app/cage/
COPY packages/hive-conductor/eval/ /app/eval/
COPY packages/hive-conductor/dags/ /app/dags/
# The canonical agent roster. The default MAISTRO_AGENTS_DIR ("agents")
# resolves against the backend directory, and the embedded bridge builds its
# roster with require_agents=True: without these files it fails to start, and
# with DATABASE_URL set every Workspace request then fails closed (#37).
COPY agents/ /app/backend/agents/
COPY --from=frontend /build/dist /app/frontend/dist
# Persistent conductor state dir, pre-owned by the nonroot uid (see pybuild).
COPY --from=pybuild --chown=65532:65532 /app/state_seed /data
# Security patches the pinned base digest froze at its 2026-09-30 build (trivy:
# perl-base x3 CRITICAL + x4 HIGH, libpcre2 HIGH on debian 12.15, all fixed in
# current point releases). Same hardening policy as Dockerfile.research.
RUN apt-get update && apt-get upgrade -y \
    && apt-get autoremove -y --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*
# pip is a build-time tool, not a runtime surface: nothing in the shipped app
# invokes it, and its vendored dependency tree (pip/_vendor/vendor.txt: msgpack
# 1.1.2, urllib3 2.7.0, setuptools 70.3.0 -- present in both the venv's pip and
# the base interpreter's) is exactly what the trivy gate flagged. Drop pip from
# the shipped filesystem; the venv keeps everything the app imports.
RUN rm -rf /app/venv/lib/python3.13/site-packages/pip* \
           /app/venv/bin/pip* \
           /usr/local/lib/python3.13/site-packages/pip* \
           /usr/local/bin/pip*
EXPOSE 8101
WORKDIR /app/backend
# Keep the app nonroot even though the pinned runtime is a slim Python image.
USER 65532
# exec-form, stdlib healthcheck — no curl/shell dependency.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8101/health/ready', timeout=4).status==200 else 1)"]
# Base image's ENTRYPOINT is `python`, so invoke uvicorn via `python -m`.
ENTRYPOINT ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8101"]
