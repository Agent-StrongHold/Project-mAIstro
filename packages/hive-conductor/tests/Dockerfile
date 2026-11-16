# Digest-pinned (#349): python:3.12-slim index digest resolved 2026-11-16
# (refreshed 2026-11-16, #1836 containers-gate repair: prior index pinned
# CPython 3.12.15, grype CVE-2026-115557 CRITICAL fixed *3.12.16).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /tests
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY tests/e2e/ /tests/tests/e2e/
CMD ["pytest", "tests/e2e/test_pm_workflow_api.py", "-v"]
