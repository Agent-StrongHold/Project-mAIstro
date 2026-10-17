# Digest-pinned (#349): python:3.12-slim index digest resolved 2026-09-30.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
WORKDIR /tests
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY tests/e2e/ /tests/tests/e2e/
CMD ["pytest", "tests/e2e/test_pm_workflow_api.py", "-v"]
