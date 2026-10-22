# maistro-engine API image — Debian slim runtime (glibc, nonroot uid 65532).
# The runtime keeps `git` apt-installed for the git tools. The image is
# vuln-gated like the rest (#346): security.yml scans PR/merge-queue/nightly
# candidates and release.yml re-scans every pushed release digest, so its apt
# layer applies the security patches the pinned base digest froze.
#
# The RESEARCH browser surface (browser-use + Playwright + Chromium) — previously
# baked in here and "the single largest remaining CVE source" — has been split
# into Dockerfile.research. Chromium needs a Debian/X-libs base and can't run on
# a distroless runtime, so shedding it is what keeps this image's CVE surface
# small.
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
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS builder
WORKDIR /app
# CI evidence (run 36835563311, job 110282105809): both buildx attempts of the
# sibling research image died inside pip on `files.pythonhosted.org` read
# timeouts -- pip's 15s default, under runner load, on multi-hundred-KB wheels.
# The resolution itself is sound (a pip --dry-run of the same requirements
# resolves cleanly), so the defect is transport patience, not pinning. State
# the patience instead of rediscovering it on the next registry slow spell;
# buildx-build-retry.sh still retries the whole invocation above this layer.
ENV PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10
ENV PATH="/app/venv/bin:$PATH"
RUN python -m venv /app/venv
COPY pyproject.toml uv.lock README.md ./
COPY packages/maistro-core   packages/maistro-core
COPY packages/maistro-server packages/maistro-server
# #1825: the engine mounts /v2/canvas and advertises the Canvas ability, but
# only the server was installed — `_wire_canvas_ability()` hit ImportError at
# startup and every Canvas route answered 503 forever, invisibly to a healthy
# API container. The Canvas package ships in the supported image.
COPY packages/maistro-canvas packages/maistro-canvas
# Non-editable install so the venv is fully self-contained (nothing from the
# source trees is needed on sys.path at runtime).
# psycopg is listed for alembic, not for the application. Alembic reaches
# PostgreSQL through SQLAlchemy's *sync* engine, and `to_sync_url` names psycopg
# 3 explicitly because a bare `postgresql://` resolves to psycopg2 instead; the
# app path uses asyncpg and touches neither. The driver is declared in the
# workspace root, which this image never installs — it installs the two packages
# by path — so without naming it here `alembic upgrade head` in the shipped
# container stops at ModuleNotFoundError before it reaches the schema.
# pydantic-ai-slim is deliberately NOT installed: ADR-094 cut pydantic-ai from
# the codebase (zero src imports) and the CVE-2026-25580 fix line (>=1.56.0)
# requires openai>=2, which cannot co-install with the openai pin below.
RUN pip install --no-cache-dir \
      "./packages/maistro-core[identity,llm,sandbox,observability,sqlite]" \
      "./packages/maistro-server" \
      "./packages/maistro-canvas" \
      "alembic>=1.14" \
      "psycopg[binary]>=3.2" \
      "openai>=1.40,<2" \
      "anyio>=4.14.2" \
      "httpx>=0.27.0"

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

# ---- docker CLI build ----
# The published docker:29-cli binary ships an unpatched Go stdlib (trivy:
# published go1.26.8 hit CVE-2026-78667/78669/97031 HIGH, fixed in
# go1.26.9/1.27.2; 1.27.2 itself then hit CVE-2026-111943 HIGH in
# crypto, fixed in go1.26.10/1.27.3) and no released docker:xx-cli tag
# ships a newer toolchain (29.1/29.2 ship older ones). Build the exact
# same immutable release tag ourselves on the patched toolchain -- the
# same policy as the age stage in packages/hive-conductor/Dockerfile. The
# tag resolves to dfc520d; fail if upstream ever disagrees. docker/cli has no
# root go.mod (vendor.mod + vendor/ instead); renaming them is the module-mode
# build the vendored tree is designed for.
# Toolchain treadmill log: go1.26.8 -> 1.27.2 (2026-10-21, CVE-2026-78667/
# 78669/97031) -> 1.27.3 (2026-10-22, CVE-2026-111943 crypto HIGH). Bump
# the pin (tag+digest) whenever trivy's DB flags the embedded stdlib again.
FROM golang:1.27.3-alpine@sha256:d530cf60723abf1ffae0cd16bb546b379ec0550d2f3815e5b16ed69dbc00fba4 AS dockerclibuild
ARG DOCKER_CLI_VERSION=29.9.1
ARG DOCKER_CLI_COMMIT_SHORT=dfc520d
RUN apk add --no-cache git && \
    git clone --branch "v${DOCKER_CLI_VERSION}" --depth 1 https://github.com/docker/cli.git /src/docker-cli && \
    cd /src/docker-cli && \
    test "$(git rev-parse --short=7 HEAD)" = "${DOCKER_CLI_COMMIT_SHORT}" && \
    cp vendor.mod go.mod && cp vendor.sum go.sum && \
    mkdir -p /out && \
    CGO_ENABLED=0 go build -trimpath -tags grpcnotrace \
      -ldflags="-s -w -X github.com/docker/cli/cli/version.Version=v${DOCKER_CLI_VERSION} -X github.com/docker/cli/cli/version.GitCommit=${DOCKER_CLI_COMMIT_SHORT}" \
      -o /out/docker ./cmd/docker

# ─── Thin Debian runtime: apt keeps `git` available ─────────────────────
# Provides the `git` binary the orchestrator's git tools (maistro.tools.git —
# used by orchestrator/waves/fan_in.py) exec directly; the previous distroless
# runtime shed git and broke those tools. This image IS vuln-gated like the
# rest (#346): security.yml/release.yml scan it, so the apt layer also applies
# the security patches the pinned base digest froze (trivy: libpcre2 HIGH on
# debian 12.15), matching Dockerfile.research's hardening.
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get upgrade -y \
    && apt-get autoremove -y --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*
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
# Static docker CLI built from the pinned upstream release tag on the patched
# Go toolchain (stage above) — talks to a mounted /var/run/docker.sock, a single
# static binary, no daemon. Historically: 29-cli's published binary embedded
# go1.26.8 stdlib (trivy HIGHs), then our 1.27.2 rebuild (CVE-2026-111943);
# before that 27-cli embedded go1.22.11 (CVE-2025-68121 crypto/tls + 21 HIGHs, trivy).
COPY --from=dockerclibuild /out/docker /usr/local/bin/docker
# pip (and its vendored dependency tree — trivy flagged msgpack 1.1.2,
# urllib3 2.7.0 and setuptools 70.3.0 from pip/_vendor/vendor.txt in both the
# venv's pip and the base interpreter's) is build tooling; nothing in the
# shipped app invokes it at runtime.
RUN rm -rf /app/venv/lib/python3.13/site-packages/pip* \
           /app/venv/bin/pip* \
           /usr/local/lib/python3.13/site-packages/pip* \
           /usr/local/bin/pip*
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
