"""Pipeline orchestrator: scan → build+test (external CI) → deploy (Launch API)."""

import os

from maistro.http import shared_client
from services import tork_client

LAUNCH_API = os.environ.get("DEPLOY_API_URL") or os.environ.get("DEPLOY_TARGET_API_URL") or ""
FANTASIA_BASE = os.environ.get("FANTASIA_BASE_URL", "http://127.0.0.1:8101")


async def trigger_deploy(
    project_id: str,
    repo_url: str = "",
    branch: str = "main",
    dockerfile_path: str = "Dockerfile",
    scan_summary: dict | None = None,
    force: bool = False,
) -> dict:
    """Submit build+test job to the external CI system. Raises if scan is blocking and force=False."""
    if scan_summary and scan_summary.get("blocking") and not force:
        raise Exception("blocking: scan has critical/high findings. Use force=True to override.")

    callback_url = f"{FANTASIA_BASE}/v1/projects/webhooks/external-build"
    yaml = tork_client.build_job_yaml(
        project_id=project_id,
        repo_url=repo_url,
        branch=branch,
        dockerfile_path=dockerfile_path,
        callback_url=callback_url,
    )
    job_id = await tork_client.submit_job(yaml)
    return {"tork_job_id": job_id, "status": "building"}


async def deploy_to_launch(project_name: str, repo_url: str, branch: str = "main") -> dict:
    """Create a Launch app and trigger deployment. Returns {app_name, url}."""
    api_key = os.environ.get("DEPLOY_API_KEY") or os.environ.get("DEPLOY_TARGET_API_KEY") or ""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with shared_client(timeout=30) as client:
        # Create the app
        r = await client.post(
            f"{LAUNCH_API}/launch/apps",
            json={"name": project_name, "repo_url": repo_url, "branch": branch},
            headers=headers,
        )
        r.raise_for_status()
        app_data = r.json()
        app_slug = app_data.get("slug", project_name)
        app_url = app_data.get("url", "")

        # Trigger deploy
        deploy_hook = app_data.get("deploy_hook_url")
        if deploy_hook:
            await client.post(deploy_hook, json={"branch": branch}, headers=headers)

        return {"app_name": app_slug, "url": app_url}
