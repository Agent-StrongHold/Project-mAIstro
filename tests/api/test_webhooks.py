"""Tests for webhook endpoints — signature verification and content wrapping."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro.tasks.queue import get_task_queue
from maistro_server.main import app


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def app_with_webhook_secret():
    """Create app with webhook secrets configured."""
    secret = "test-webhook-secret-123"
    settings = Settings(
        require_auth=False,
        github_webhook_secret=secret,
        ci_webhook_secret=_CI_TOKEN,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield secret
    app.dependency_overrides.clear()


def _make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


_CI_TOKEN = "ci-token-abc"


def _post_github(client: TestClient, payload: dict, event: str, secret: str):
    """POST a *signed* GitHub webhook.

    The functionality tests below used to post unsigned bodies and rely on the
    route's old "no secret configured => skip verification" branch. That branch
    is now a 503 (review finding C5), so exercising routing requires a genuine
    signature. This is a correction, not a workaround: the unsigned path was
    never a supported way to deliver a webhook, only an unauthenticated one.
    """
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": _make_signature(body, secret),
        },
    )


def _post_ci(client: TestClient, payload: dict):
    return client.post("/webhooks/ci", json=payload, headers={"X-CI-Token": _CI_TOKEN})


class TestGitHubWebhookSignature:
    """CRIT-03: Webhook signature must be verified when secret is configured."""

    def test_missing_signature_rejected(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = client.post(
            "/webhooks/github",
            json={"action": "opened"},
            headers={"X-GitHub-Event": "push"},
        )
        assert response.status_code == 401

    def test_invalid_signature_rejected(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = client.post(
            "/webhooks/github",
            json={"action": "opened"},
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        assert response.status_code == 403

    def test_valid_signature_accepted(self, app_with_webhook_secret: str) -> None:
        client = _client()
        payload = json.dumps({"action": "opened"}).encode()
        sig = _make_signature(payload, app_with_webhook_secret)
        response = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
            },
        )
        assert response.status_code == 200


class TestCIWebhookAuth:
    """CRIT-03: CI webhook must require token when secret is configured."""

    def test_missing_token_rejected(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = client.post("/webhooks/ci", json={"status": "failure"})
        assert response.status_code == 401

    def test_wrong_token_rejected(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = client.post(
            "/webhooks/ci",
            json={"status": "failure"},
            headers={"X-CI-Token": "wrong-token"},
        )
        assert response.status_code == 401

    def test_valid_token_accepted(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = client.post(
            "/webhooks/ci",
            json={"status": "success"},
            headers={"X-CI-Token": _CI_TOKEN},
        )
        assert response.status_code == 200


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestUnconfiguredWebhooksFailClosed:
    """Review finding C5: an unconfigured receiver must refuse, not accept.

    With no secret set, both routes previously logged a warning and processed
    the request anyway — so any unauthenticated caller could enqueue tasks that
    the runner executes against a workspace path derived from their own payload.
    Deployment simply forgetting an env var was the whole exploit.

    Both tests fail without the fix: they returned 200 before it.
    """

    @pytest.fixture(autouse=True)
    def _no_secrets(self):
        settings = Settings(require_auth=False)
        assert settings.github_webhook_secret == ""
        assert settings.ci_webhook_secret == ""
        app.dependency_overrides[get_settings] = lambda: settings
        yield
        app.dependency_overrides.clear()

    def test_github_without_secret_is_refused(self) -> None:
        response = _client().post(
            "/webhooks/github",
            json={
                "action": "opened",
                "pull_request": {"title": "Add auth", "number": 42},
                "repository": {"full_name": "org/repo"},
            },
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert response.status_code == 503

    def test_ci_without_secret_is_refused(self) -> None:
        response = _client().post(
            "/webhooks/ci",
            json={"status": "failure", "repository": "org/repo", "branch": "main"},
        )
        assert response.status_code == 503


class TestGitHubWebhookFunctionality:
    """Webhook routing, exercised over the authenticated (signed) path."""

    def test_pr_opened_creates_task(self, app_with_webhook_secret: str) -> None:
        """Evidence: PR opened events should auto-create a review task."""
        client = _client()
        response = _post_github(
            client,
            {
                "action": "opened",
                "pull_request": {"title": "Add auth", "number": 42},
                "repository": {"full_name": "org/repo"},
            },
            "pull_request",
            app_with_webhook_secret,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "pr_review_queued"
        assert "task_id" in data

        # Verify the task was actually created in the queue with correct content
        queue = get_task_queue()
        task = queue.get(data["task_id"])
        assert task is not None, "Task must actually exist in the queue"
        assert "Add auth" in task.description
        assert "#42" in task.description
        assert task.workspace == "/repos/org/repo"

    def test_issue_opened_creates_task(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = _post_github(
            client,
            {
                "action": "opened",
                "issue": {"title": "Bug in login", "number": 7, "body": "Steps to reproduce..."},
                "repository": {"full_name": "org/repo"},
            },
            "issues",
            app_with_webhook_secret,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "issue_task_queued"

        # Verify task content
        queue = get_task_queue()
        task = queue.get(data["task_id"])
        assert task is not None
        assert "Bug in login" in task.description
        assert "#7" in task.description
        assert "Steps to reproduce" in task.description

    def test_ignored_event(self, app_with_webhook_secret: str) -> None:
        client = _client()
        response = _post_github(
            client, {"action": "closed"}, "pull_request", app_with_webhook_secret
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @pytest.mark.parametrize(
        "repo",
        [
            "",
            "org",
            "org/repo/extra",
            "../repo",
            "org/../repo",
            "https://github.com/org/repo",
        ],
    )
    def test_task_creating_events_reject_invalid_repository_names(
        self, repo: str, app_with_webhook_secret: str
    ) -> None:
        client = _client()
        response = _post_github(
            client,
            {
                "action": "opened",
                "pull_request": {"title": "Add auth", "number": 42},
                "repository": {"full_name": repo},
            },
            "pull_request",
            app_with_webhook_secret,
        )
        assert response.status_code == 422
        assert response.json()["error"]["message"] == "Repository must be in owner/name form"


class TestCIWebhookFunctionality:
    @pytest.mark.parametrize(
        "repository",
        ["", "org", "org/repo/extra", "../repo", "org/../repo", "https://example.com/org/repo"],
    )
    def test_failure_rejects_invalid_repository_names(
        self, repository: str, app_with_webhook_secret: str
    ) -> None:
        response = _post_ci(
            _client(), {"status": "failure", "repository": repository, "branch": "main"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["message"] == "Repository must be in owner/name form"

    def test_failure_creates_fix_task(self, app_with_webhook_secret: str) -> None:
        response = _post_ci(
            _client(),
            {
                "status": "failure",
                "repository": "org/repo",
                "branch": "main",
                "log_url": "https://ci.example.com/logs/123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "ci_fix_queued"
        assert "task_id" in data

        # Verify task content
        queue = get_task_queue()
        task = queue.get(data["task_id"])
        assert task is not None
        assert "org/repo" in task.description
        assert "main" in task.description

    def test_success_ignored(self, app_with_webhook_secret: str) -> None:
        response = _post_ci(_client(), {"status": "success", "repository": "org/repo"})
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestWebhookBodyLimits:
    def test_github_rejects_oversized_actual_body_without_content_length(self) -> None:
        settings = Settings(require_auth=False, max_webhook_body_bytes=10)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = _client()
            response = client.post(
                "/webhooks/github",
                content=b'{"action":"closed"}',
                headers={"X-GitHub-Event": "pull_request", "Content-Type": "application/json"},
            )
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 413

    def test_github_rejects_malformed_content_length(self) -> None:
        settings = Settings(require_auth=False, max_webhook_body_bytes=1000)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = _client()
            response = client.post(
                "/webhooks/github",
                content=b'{"action":"closed"}',
                headers={
                    "X-GitHub-Event": "pull_request",
                    "Content-Type": "application/json",
                    "Content-Length": "not-a-number",
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "Invalid Content-Length header"
