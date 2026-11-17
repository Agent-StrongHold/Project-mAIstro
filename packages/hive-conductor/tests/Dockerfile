# Digest-pinned (#349): python:3.12-slim index digest resolved 2026-10-24.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /tests
# `tzdata` is deliberate (#290): the scheduler-timezone container tests
# compute expected next-fire instants from an independent zone database, so
# the verification does not silently depend on whatever the base image ships.
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1 tzdata==2026.3
COPY tests/e2e/ /tests/tests/e2e/
CMD ["pytest", "tests/e2e/test_pm_workflow_api.py", "tests/e2e/test_scheduler_timezone_container.py", "-v"]
