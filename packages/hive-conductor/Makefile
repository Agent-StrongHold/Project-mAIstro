.PHONY: up down test-api test-e2e test-agent test-all logs

COMPOSE := docker compose -f docker-compose.test.yml

## Start the full stack
up:
	$(COMPOSE) up --build -d
	@echo "⏳ Waiting for health..."
	@until curl -fsS http://localhost:8101/health/ready >/dev/null 2>&1; do sleep 2; done
	@echo "✅ Hive is ready at http://localhost:8101"

## Stop everything
down:
	$(COMPOSE) down -v

## Run API integration tests (PM workflow)
test-api: up
	$(COMPOSE) run --rm api-tests

## Run Playwright UI tests (PM workflow)
test-e2e: up
	$(COMPOSE) run --rm e2e-tests

## Run browser-use + Gemini Flash PM agent (requires GOOGLE_API_KEY)
test-agent: up
	HIVE_URL=http://localhost:8101 python tests/e2e/test_pm_agent.py

## Run browser-use vision tests with pytest (requires GOOGLE_API_KEY)
test-vision: up
	HIVE_URL=http://localhost:8101 pytest tests/e2e/test_pm_vision.py -v

## Run real Jira + Confluence via browser-use (requires GOOGLE_API_KEY, JIRA_URL, JIRA_USERNAME, JIRA_PASSWORD)
test-atlassian: up
	HIVE_URL=http://localhost:8101 python tests/e2e/test_pm_real_atlassian.py

## Run all tests (API + Playwright; agent tests run separately due to API key)
test-all: test-api test-e2e

## Tail logs
logs:
	$(COMPOSE) logs -f hive
