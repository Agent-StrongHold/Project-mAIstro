"""Webhook receivers for GitHub and CI events."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from maistro.config.settings import Settings, get_settings
from maistro.constants import WEBHOOK_BODY_PREVIEW_LEN
from maistro.security.external_content import ContentSource, detect_injection, wrap_external_content
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue, get_task_queue
from maistro_server.api.schemas import CIWebhookIgnored, WebhookAccepted, WebhookIgnored

# WebDAV's 423 Locked is repurposed here (as elsewhere in the security layer,
# see `security/gate.py`'s account lockout) to mean "held back by a security
# gate" -- distinct from 403 (auth/signature failure) so callers can tell
# "you're not who you say you are" apart from "you are who you say you are,
# but the content you sent tripped injection detection".
_HTTP_423_LOCKED = 423

logger = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_REPO_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def _sanitize(text: str) -> str:
    """Detect injection and wrap external content for safe LLM consumption."""
    violations = detect_injection(text)
    if violations:
        logger.warning("injection_detected_in_webhook", violations=violations)
    wrapped: str = wrap_external_content(text, ContentSource.WEBHOOK)
    return wrapped


def _check_body_size(request: Request, settings: Settings) -> None:
    """Raise if Content-Length is malformed or exceeds the configured limit."""
    content_length = request.headers.get("content-length")
    if not content_length:
        return
    try:
        size = int(content_length)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Content-Length header",
        ) from exc
    if size > settings.max_webhook_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request body too large (max {settings.max_webhook_body_bytes} bytes)",
        )


def _check_actual_body_size(body: bytes, settings: Settings) -> None:
    if len(body) > settings.max_webhook_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request body too large (max {settings.max_webhook_body_bytes} bytes)",
        )


def _repo_workspace(repository: str) -> str:
    if not _REPO_FULL_NAME_RE.fullmatch(repository):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Repository must be in owner/name form",
        )
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Repository must be in owner/name form",
        )
    return f"/repos/{repository}"


@router.post("/github")
async def github_webhook(
    request: Request,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_github_event: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
) -> WebhookAccepted | WebhookIgnored:
    _check_body_size(request, settings)
    body = await request.body()
    _check_actual_body_size(body, settings)

    # Verify GitHub webhook signature
    if settings.github_webhook_secret:
        if not x_hub_signature_256:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Hub-Signature-256 header",
            )
        if not _verify_github_signature(body, x_hub_signature_256, settings.github_webhook_secret):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature",
            )
    else:
        await logger.aerror(
            "github_webhook_rejected_no_secret",
            msg="GITHUB_WEBHOOK_SECRET not set — refusing to process an unauthenticated webhook",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook receiver not configured (GITHUB_WEBHOOK_SECRET unset)",
        )

    payload = json.loads(body)
    event = x_github_event or "unknown"
    action = payload.get("action", "")

    await logger.ainfo("github_webhook", github_event=event, action=action)

    # Handle PR events
    if event == "pull_request" and action in ("opened", "synchronize"):
        pr = payload.get("pull_request", {})
        title = _sanitize(pr.get("title", ""))
        number = pr.get("number", "")
        repo = payload.get("repository", {}).get("full_name", "")

        raw_description = f"Review PR #{number}: {title} in {repo}"
        wrapped = wrap_external_content(
            raw_description,
            ContentSource.WEBHOOK,
            sender=f"github/{repo}",
        )
        injections = detect_injection(title)
        if injections:
            await logger.awarn("injection_detected_in_pr", pr=number, patterns=injections)
            raise HTTPException(
                status_code=_HTTP_423_LOCKED,
                detail=(
                    f"PR #{number} quarantined: potential prompt injection detected "
                    f"in title ({', '.join(injections)})"
                ),
            )

        task = TaskCreate(
            description=wrapped,
            workspace=_repo_workspace(repo),
        )
        result = await queue.submit(task)
        return WebhookAccepted(task_id=result.task_id, action="pr_review_queued")

    # Handle issue events
    if event == "issues" and action == "opened":
        issue = payload.get("issue", {})
        title = _sanitize(issue.get("title", ""))
        number = issue.get("number", "")
        body_text = _sanitize(issue.get("body", "")[:WEBHOOK_BODY_PREVIEW_LEN])
        repo = payload.get("repository", {}).get("full_name", "")

        raw_description = f"Investigate issue #{number}: {title}\n\n{body_text[:500]}"
        wrapped = wrap_external_content(
            raw_description,
            ContentSource.WEBHOOK,
            sender=f"github/{repo}",
        )
        injections = detect_injection(title) + detect_injection(body_text[:500])
        if injections:
            await logger.awarn("injection_detected_in_issue", issue=number, patterns=injections)
            raise HTTPException(
                status_code=_HTTP_423_LOCKED,
                detail=(
                    f"Issue #{number} quarantined: potential prompt injection detected "
                    f"in title/body ({', '.join(injections)})"
                ),
            )

        task = TaskCreate(
            description=wrapped,
            workspace=_repo_workspace(repo),
        )
        result = await queue.submit(task)
        return WebhookAccepted(task_id=result.task_id, action="issue_task_queued")

    return WebhookIgnored(status="ignored", event=event, action=action)


class CIWebhookPayload(BaseModel):
    """Typed request body for CI webhook."""

    status: str
    repository: str = ""
    branch: str = "main"
    log_url: str = ""
    commit_sha: str = ""


@router.post("/ci")
async def ci_webhook(
    request: Request,
    payload: CIWebhookPayload,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_ci_token: str | None = Header(None),
) -> WebhookAccepted | CIWebhookIgnored:
    _check_body_size(request, settings)

    # Require CI webhook authentication
    if settings.ci_webhook_secret:
        if not x_ci_token or not hmac.compare_digest(x_ci_token, settings.ci_webhook_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing CI webhook token",
            )
    else:
        await logger.aerror(
            "ci_webhook_rejected_no_secret",
            msg="CI_WEBHOOK_SECRET not set — refusing to process an unauthenticated webhook",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook receiver not configured (CI_WEBHOOK_SECRET unset)",
        )

    if payload.status == "failure":
        log_ref = _sanitize(payload.log_url) if payload.log_url else "no log"
        raw_description = (
            f"Fix CI failure on {payload.branch} in {payload.repository}. Log: {log_ref}"
        )
        wrapped = wrap_external_content(raw_description, ContentSource.WEBHOOK, sender="ci")

        task = TaskCreate(
            description=wrapped,
            workspace=_repo_workspace(payload.repository),
            branch=payload.branch,
        )
        result = await queue.submit(task)
        return WebhookAccepted(task_id=result.task_id, action="ci_fix_queued")

    return CIWebhookIgnored(status="ignored", ci_status=payload.status)
