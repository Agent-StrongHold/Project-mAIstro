# Digest-pinned (#349): python:3.12.16-slim-bookworm index digest resolved 2026-11-16
# (3.12.16 CPython-binary refresh, #2304 container-gate round).
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
WORKDIR /tests
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY tests/e2e/ /tests/tests/e2e/
CMD ["pytest", "tests/e2e/test_pm_workflow_api.py", "-v"]
