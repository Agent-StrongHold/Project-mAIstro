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
FROM cgr.dev/chainguard/python:latest-dev AS builder
WORKDIR /app
ENV PATH="/app/venv/bin:$PATH"
RUN python -m venv /app/venv
COPY pyproject.toml uv.lock README.md ./
COPY packages/maistro-core   packages/maistro-core
COPY packages/maistro-server packages/maistro-server
# Non-editable install so the venv is fully self-contained (nothing from the
# source trees is needed on sys.path at runtime).
RUN pip install --no-cache-dir \
      "./packages/maistro-core[llm,sandbox,observability]" \
      "./packages/maistro-server" \
      "alembic>=1.14" \
      "pydantic-ai-slim[openai]>=0.1" \
      "openai>=1.40,<2" \
      "httpx>=0.27.0"

# ─── Wolfi runtime (-dev variant): low-CVE, has apk so `git` is available ───
# This image is NOT vuln-gated (only the hive-conductor image is trivy/grype
# scanned), so the -dev variant's slightly larger surface has no gate cost. It
# stays Wolfi (low-CVE) while providing the `git` binary the orchestrator's git
# tools (maistro.tools.git — used by orchestrator/waves/fan_in.py) exec directly;
# the previous distroless runtime shed git and broke those tools.
FROM cgr.dev/chainguard/python:latest-dev
WORKDIR /app
USER root
RUN apk add --no-cache git
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
# binary, no daemon.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
EXPOSE 8000
STOPSIGNAL SIGTERM
# Drop back to the base image's nonroot uid for runtime (apk install needed root).
USER 65532
# exec-form, stdlib healthcheck — no curl in the image.
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live', timeout=4).status==200 else 1)"]
# Base image's ENTRYPOINT is `python`, so invoke uvicorn via `python -m`.
ENTRYPOINT ["python", "-m", "uvicorn", "maistro_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
