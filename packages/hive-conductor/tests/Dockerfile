FROM python:3.12-slim
WORKDIR /tests
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY tests/e2e/ /tests/tests/e2e/
CMD ["pytest", "tests/e2e/test_pm_workflow_api.py", "-v"]
