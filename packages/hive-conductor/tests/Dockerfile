# Digest-pinned (#349): python:3.12-slim index digest resolved 2026-09-30.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /tests
# `tzdata` is deliberate (#290): the scheduler-timezone container tests
# compute expected next-fire instants from an independent zone database, so
# the verification does not silently depend on whatever the base image ships.
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1 tzdata==2026.3
COPY tests/e2e/ /tests/tests/e2e/
CMD ["pytest", "tests/e2e/test_pm_workflow_api.py", "tests/e2e/test_scheduler_timezone_container.py", "-v"]
