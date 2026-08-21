"""PM Fleet enhancements — knowledge distillation, tool config, topK optimization.

Phase 7 additions:
  - Chatbot model hill-climb integration
  - Knowledge distillation: Opus answers → focused FAQ → Flash Lite serves
  - Jira project key: MAISTRO
  - GitHub/GitLab tool definitions
  - topK value testing (4 vs 8 vs 12)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.pm_fleet_v2")

# Jira project key for MAISTRO
JIRA_PROJECT_KEY = "MAISTRO"
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", os.environ.get("JIRA_SERVER_URL", ""))

# topK configurations to test
TOPK_CONFIGS = [4, 8, 12]
DEFAULT_TOPK = 8


# --- Knowledge Distillation ---


class KnowledgeDistiller:
    """Opus answers → focused FAQ → Flash Lite serves.

    Collects high-quality answers from expensive models (Opus/Pro),
    distills them into a FAQ, then serves from cheap models (Flash Lite).
    """

    def __init__(self):
        self.opus_answers: list[dict[str, str]] = []
        self.faq: list[dict[str, str]] = []
        self._distilled = False

    def record_opus_answer(self, question: str, answer: str, score: float = 0.0):
        """Record a high-quality answer from an expensive model."""
        self.opus_answers.append({"question": question, "answer": answer, "score": score})
        self._distilled = False

    async def distill(self) -> list[dict[str, str]]:
        """Distill collected answers into a focused FAQ."""
        if not self.opus_answers:
            return []

        base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        key = os.environ.get("LITELLM_API_KEY", "")

        # Use a mid-tier model to synthesize the FAQ
        prompt = (
            "You have a collection of high-quality Q&A pairs. "
            "Distill them into a focused FAQ (max 20 entries). "
            "Merge similar questions, keep answers concise but complete. "
            'Output JSON array: [{"q": str, "a": str}]\n\n'
            f"Source Q&A pairs:\n{json.dumps(self.opus_answers[:50], indent=2)}"
        )

        try:
            async with shared_client(timeout=60.0) as client:
                r = await client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": "gemini-3.5-flash",
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                    },
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                self.faq = data if isinstance(data, list) else data.get("faq", [])
                self._distilled = True
                return self.faq
        except Exception as e:
            logger.error(f"Distillation failed: {e}")
            return []

    def lookup(self, question: str) -> str | None:
        """Try to answer from FAQ (Flash Lite path). Returns None if no match."""
        if not self.faq:
            return None
        q_lower = question.lower()
        for entry in self.faq:
            if any(word in q_lower for word in entry.get("q", "").lower().split()[:3]):
                return entry.get("a")
        return None


# --- GitHub/GitLab Tools ---

GITHUB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "github_list_prs",
            "description": "List open pull requests for a repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo format"},
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "all"],
                        "default": "open",
                    },
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_create_issue",
            "description": "Create a new GitHub issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["repo", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_get_file",
            "description": "Get file contents from a repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {"type": "string", "default": "main"},
                },
                "required": ["repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gitlab_list_mrs",
            "description": "List merge requests for a GitLab project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["opened", "closed", "merged", "all"],
                        "default": "opened",
                    },
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gitlab_create_issue",
            "description": "Create a new GitLab issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "labels": {"type": "string"},
                },
                "required": ["project_id", "title"],
            },
        },
    },
]


async def execute_github_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a GitHub tool call."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return {"error": "GITHUB_TOKEN not configured"}

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    base = "https://api.github.com"

    async with shared_client(timeout=30.0, headers=headers) as client:
        if name == "github_list_prs":
            r = await client.get(
                f"{base}/repos/{args['repo']}/pulls", params={"state": args.get("state", "open")}
            )
            r.raise_for_status()
            return {
                "pulls": [
                    {
                        "number": p["number"],
                        "title": p["title"],
                        "user": p["user"]["login"],
                        "url": p["html_url"],
                    }
                    for p in r.json()[:20]
                ]
            }

        elif name == "github_create_issue":
            body = {
                "title": args["title"],
                "body": args.get("body", ""),
                "labels": args.get("labels", []),
            }
            r = await client.post(f"{base}/repos/{args['repo']}/issues", json=body)
            r.raise_for_status()
            return {"issue_url": r.json()["html_url"], "number": r.json()["number"]}

        elif name == "github_get_file":
            r = await client.get(
                f"{base}/repos/{args['repo']}/contents/{args['path']}",
                params={"ref": args.get("ref", "main")},
            )
            r.raise_for_status()
            import base64

            content = base64.b64decode(r.json()["content"]).decode()
            return {"content": content[:5000], "path": args["path"]}

    return {"error": f"Unknown tool: {name}"}


async def execute_gitlab_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a GitLab tool call."""
    token = os.environ.get("GITLAB_TOKEN", "")
    base = os.environ.get("GITLAB_URL", "https://gitlab.com/api/v4")
    if not token:
        return {"error": "GITLAB_TOKEN not configured"}

    headers = {"PRIVATE-TOKEN": token}

    async with shared_client(timeout=30.0, headers=headers) as client:
        if name == "gitlab_list_mrs":
            r = await client.get(
                f"{base}/projects/{args['project_id']}/merge_requests",
                params={"state": args.get("state", "opened")},
            )
            r.raise_for_status()
            return {
                "merge_requests": [
                    {
                        "iid": m["iid"],
                        "title": m["title"],
                        "author": m["author"]["username"],
                        "url": m["web_url"],
                    }
                    for m in r.json()[:20]
                ]
            }

        elif name == "gitlab_create_issue":
            body = {
                "title": args["title"],
                "description": args.get("description", ""),
                "labels": args.get("labels", ""),
            }
            r = await client.post(f"{base}/projects/{args['project_id']}/issues", json=body)
            r.raise_for_status()
            return {"issue_url": r.json()["web_url"], "iid": r.json()["iid"]}

    return {"error": f"Unknown tool: {name}"}


# --- topK Testing ---


class TopKTester:
    """Test different topK values and track which performs best."""

    def __init__(self):
        self.results: dict[int, list[float]] = {k: [] for k in TOPK_CONFIGS}
        self.current_topk = DEFAULT_TOPK

    def record_result(self, topk: int, score: float):
        if topk in self.results:
            self.results[topk].append(score)

    def get_best_topk(self) -> int:
        """Return the topK value with the highest average score."""
        best_k, best_avg = DEFAULT_TOPK, 0.0
        for k, scores in self.results.items():
            if scores:
                avg = sum(scores) / len(scores)
                if avg > best_avg:
                    best_avg = avg
                    best_k = k
        return best_k

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "current": self.current_topk,
            "best": self.get_best_topk(),
            "results": {
                k: {"count": len(v), "avg": sum(v) / len(v) if v else 0}
                for k, v in self.results.items()
            },
        }


# Singletons
_distiller = KnowledgeDistiller()
_topk_tester = TopKTester()


def get_distiller() -> KnowledgeDistiller:
    return _distiller


def get_topk_tester() -> TopKTester:
    return _topk_tester
