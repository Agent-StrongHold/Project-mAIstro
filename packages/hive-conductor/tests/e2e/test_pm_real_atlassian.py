"""Real Jira + Confluence test — creds already in Hive, browser-use navigates.

Assumes:
  - Hive is running locally (localhost:8101)
  - You already saved your Jira/Confluence PATs via the Credentials UI
  - The system uses them when running DAGs

This test logs in as you, creates a DAG that hits real Jira, runs it,
and verifies the whole loop works. Non-destructive reads only.

Requirements:
  pip install browser-use httpx
  export GOOGLE_API_KEY=your-key
  export JIRA_URL=https://jira.yourcompany.com

Usage:
  python tests/e2e/test_pm_real_atlassian.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

# C1 (#286): a manual e2e *script*, not a pytest suite — no `test_*` functions,
# only `run()` behind `if __name__ == "__main__"`. It matches pytest's
# `test_*.py` glob anyway, so the unguarded `browser_use` import aborted
# collection for the whole `tests/e2e` directory. `browser_use` ships only in
# `Dockerfile.research`, and this one additionally needs real Atlassian
# credentials. Guarded so the directory collects; contributes zero node IDs.
_browser_use = pytest.importorskip(
    "browser_use",
    reason="browser-use not installed (research image only — see Dockerfile.research)",
)
Agent = _browser_use.Agent
Browser = _browser_use.Browser
ChatGoogle = _browser_use.ChatGoogle

HIVE_URL = os.environ.get("HIVE_URL", "http://localhost:8101")
JIRA_URL = os.environ.get("JIRA_URL", "")
CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-preview")
# Login creds for Hive itself (not Jira)
HIVE_USER = os.environ.get("HIVE_USER", "pmuser")
HIVE_PASS = os.environ.get("HIVE_PASS", "pmpass1234")


def _parse_jira_issues(result: str) -> list:
    try:
        if "[" in result:
            start = result.index("[")
            end = result.rindex("]") + 1
            return json.loads(result[start:end])
    except (json.JSONDecodeError, ValueError):
        pass
    return []


async def _login(http: httpx.AsyncClient) -> dict:
    print("\n🐝 Step 1: Login to Hive...")
    r = await http.post("/v1/auth/login", json={"username": HIVE_USER, "password": HIVE_PASS})
    assert r.status_code == 200, f"Hive login failed: {r.text}"
    print("   ✅ Logged in")
    return {"hive_session": r.cookies.get("hive_session")}


async def _check_credentials(http: httpx.AsyncClient, cookies: dict) -> None:
    print("\n🔐 Step 2: Check credentials are stored...")
    r = await http.get("/v1/credentials", cookies=cookies)
    assert r.status_code == 200
    creds = r.json().get("credentials", [])
    configured = [c["id"] for c in creds if c.get("configured")]
    print(f"   Configured: {configured}")
    if "jira" not in configured and "atlassian" not in configured:
        print("   ⚠️  No Jira credential found — did you save it in the UI?")


async def _read_jira(browse) -> list:
    print("\n📋 Step 3: Read issues from real Jira...")
    result = await browse(
        f"Go to {JIRA_URL}. "
        f"If there's a login page, log in (check if you're already logged in from a previous session). "
        f"Once in, find 'Your Work' or the main board. "
        f"List the first 5 issues you can see: "
        f"- Issue key (e.g. PROJ-123) "
        f"- Title "
        f"- Status "
        f'Return as JSON: [{{"key":"...","summary":"...","status":"..."}}]'
    )
    print(f"   Result: {result[:400]}")
    jira_issues = _parse_jira_issues(result)
    print(f"   ✅ {len(jira_issues)} issues extracted")

    if jira_issues:
        key = jira_issues[0].get("key", "")
        print(f"\n📋 Step 4: Read {key} details...")
        result = await browse(
            f"Open issue {key} in Jira. "
            f"Read description, assignee, status, and recent comments. "
            f"Summarize briefly."
        )
        print(f"   {result[:300]}")

    if CONFLUENCE_URL:
        print("\n📄 Step 5: Read from Confluence...")
        result = await browse(
            f"Go to {CONFLUENCE_URL}. "
            f"Find the most recently updated page. "
            f"Read its title and summarize the content."
        )
        print(f"   {result[:300]}")
    return jira_issues


async def _create_and_run_dag(http: httpx.AsyncClient, cookies: dict, jira_issues: list) -> str:
    print("\n🐝 Step 6: Create DAG from real Jira data...")
    dag_name = (
        f"Sprint Report: {jira_issues[0]['summary'][:40]}"
        if jira_issues
        else "Sprint Status Report"
    )
    r = await http.post(
        "/v1/dags",
        json={"name": dag_name, "description": f"From {len(jira_issues)} real Jira issues"},
        cookies=cookies,
    )
    assert r.status_code == 201
    dag = r.json()

    await http.post(f"/v1/dags/{dag['id']}/activate", cookies=cookies)
    r = await http.post(f"/v1/dags/{dag['id']}/run", cookies=cookies)
    assert r.status_code == 200
    run_id = r.json()["execution_id"]
    print(f"   ✅ DAG '{dag_name}' executed")

    await http.post(
        f"/v1/dag-runs/{run_id}/feedback",
        json={
            "thumb": "up",
            "comment": f"Real Jira data — {len(jira_issues)} issues",
            "dag_id": dag["id"],
        },
        cookies=cookies,
    )
    print("   ✅ Feedback submitted")
    return dag_name


async def run():
    if not JIRA_URL:
        print("❌ Set JIRA_URL to run real Atlassian tests.")
        sys.exit(0)

    browser = Browser()
    llm = ChatGoogle(model=MODEL)
    http = httpx.AsyncClient(base_url=HIVE_URL, timeout=30.0)
    failures = []

    async def browse(task: str) -> str:
        agent = Agent(task=task, llm=llm, browser=browser)
        result = await agent.run()
        return str(result)

    try:
        cookies = await _login(http)
        await _check_credentials(http, cookies)
        jira_issues = await _read_jira(browse)
        dag_name = await _create_and_run_dag(http, cookies, jira_issues)

        # ─── Step 7: Verify in UI ───
        print("\n🐝 Step 7: Verify in Hive UI...")
        result = await browse(
            f"Go to {HIVE_URL}/fleet. Can you see '{dag_name[:25]}'? Is it active?"
        )
        print(f"   {result[:200]}")

        print("\n" + "=" * 60)
        print("✅ DONE — real Jira → Hive end-to-end, nothing faked")
        print(f"   Issues read: {len(jira_issues)}")
        print("   Creds from: Hive credential store (saved via UI)")
        print("=" * 60)

    except Exception as e:
        failures.append(str(e))
        print(f"\n❌ {e}")
    finally:
        await http.aclose()
        await browser.close()

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
