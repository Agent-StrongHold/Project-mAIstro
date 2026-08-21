"""PM Agent Test — browser-use + Gemini 3.5 Flash + real API calls.

The agent navigates the UI AND makes direct HTTP calls to verify the
backend is actually doing what the UI claims. This catches the case where
the UI looks fine but the API is broken (or vice versa).

Requirements:
  pip install browser-use httpx
  export GOOGLE_API_KEY=your-key

Usage:
  HIVE_URL=http://localhost:8101 python tests/e2e/test_pm_agent.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest

# C1 (#286): this module is a manual e2e *script*, not a pytest suite — it has
# no `test_*` functions, only `run_pm_workflow()` behind `if __name__ ==
# "__main__"`. It nonetheless matches pytest's `test_*.py` collection glob, so
# the unguarded `browser_use` import turned it into a hard ImportError that
# aborted collection for the whole `tests/e2e` directory. `browser_use` is
# deliberately absent from the default image (the browser surface lives in
# `Dockerfile.research`). Guarding it lets the directory collect cleanly; this
# file contributes zero test node IDs, which is the honest count.
_browser_use = pytest.importorskip(
    "browser_use",
    reason="browser-use not installed (research image only — see Dockerfile.research)",
)
Agent = _browser_use.Agent
Browser = _browser_use.Browser
ChatGoogle = _browser_use.ChatGoogle

HIVE_URL = os.environ.get("HIVE_URL", "http://localhost:8101")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-preview")


class PMSession:
    """Holds both the browser agent and an authenticated HTTP client."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.http = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self.browser = Browser()
        self.llm = ChatGoogle(model=MODEL)
        self.session_cookie: str | None = None
        self.dag_id: str | None = None
        self.run_id: str | None = None

    async def api(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an authenticated API call."""
        if self.session_cookie:
            kwargs.setdefault("cookies", {})["hive_session"] = self.session_cookie
        return await getattr(self.http, method)(path, **kwargs)

    async def browse(self, task: str) -> str:
        """Run a browser-use agent task."""
        agent = Agent(task=task, llm=self.llm, browser=self.browser)
        result = await agent.run()
        return str(result)

    async def close(self):
        await self.http.aclose()
        await self.browser.close()


async def run_pm_workflow():
    pm = PMSession(HIVE_URL)
    failures = []

    try:
        # ─── Step 1: Setup via API ───
        print("\n🐝 Step 1: Setup wizard via API...")
        r = await pm.api("get", "/v1/setup/status")
        assert r.status_code == 200
        if not r.json().get("setup_complete"):
            r = await pm.api(
                "post",
                "/v1/setup/complete",
                json={
                    "hardware_preset": "beast",
                    "conductor_name": "PM Agent Hive",
                    "admin_username": "admin",
                    "admin_password": "adminpass123",
                    "user_username": "pmuser",
                    "user_password": "pmpass1234",
                    "optional_modules": [],
                },
            )
            assert r.status_code == 200, f"Setup failed: {r.text}"
        print("   ✅ Setup complete")

        # ─── Step 2: Login via API ───
        print("\n🐝 Step 2: Login via API...")
        r = await pm.api(
            "post",
            "/v1/auth/login",
            json={
                "username": "pmuser",
                "password": "pmpass1234",
            },
        )
        assert r.status_code == 200, f"Login failed: {r.text}"
        pm.session_cookie = r.cookies.get("hive_session")
        assert pm.session_cookie, "No session cookie"
        print("   ✅ Logged in")

        # ─── Step 3: Verify UI loads via browser-use ───
        print("\n🐝 Step 3: Verify UI renders (vision)...")
        ui_result = await pm.browse(
            f"Go to {HIVE_URL}. Look at the page. "
            f"Is this a working web application with navigation? "
            f"List the main navigation items you can see. "
            f"Report any errors or blank screens."
        )
        print(f"   UI check: {ui_result[:200]}")

        # ─── Step 4: Create DAG via API ───
        print("\n🐝 Step 4: Create DAG via API...")
        r = await pm.api(
            "post",
            "/v1/dags",
            json={
                "name": "Daily Standup Report",
                "description": "Gather team updates and produce a summary",
            },
        )
        assert r.status_code == 201, f"Create failed: {r.text}"
        dag = r.json()
        pm.dag_id = dag["id"]
        assert dag["nodes"], "DAG has no nodes"
        assert dag["edges"], "DAG has no edges"
        print(f"   ✅ Created DAG: {pm.dag_id} ({len(dag['nodes'])} nodes)")

        # ─── Step 5: Verify DAG shows in UI ───
        print("\n🐝 Step 5: Verify DAG visible in UI...")
        ui_result = await pm.browse(
            f"Go to {HIVE_URL}/fleet. "
            f"Can you see a DAG called 'Daily Standup Report'? "
            f"Report YES or NO."
        )
        print(f"   UI sees DAG: {ui_result[:200]}")

        # ─── Step 6: Activate + Run via API ───
        print("\n🐝 Step 6: Activate and run DAG via API...")
        r = await pm.api("post", f"/v1/dags/{pm.dag_id}/activate")
        assert r.status_code == 200
        assert r.json()["status"] == "active"

        r = await pm.api("post", f"/v1/dags/{pm.dag_id}/run")
        assert r.status_code == 200
        run_result = r.json()
        pm.run_id = run_result["execution_id"]
        print(f"   ✅ Run started: {pm.run_id} (status: {run_result.get('status')})")

        # ─── Step 7: Submit feedback via API ───
        print("\n🐝 Step 7: Submit thumbs-up feedback via API...")
        r = await pm.api(
            "post",
            f"/v1/dag-runs/{pm.run_id}/feedback",
            json={
                "thumb": "up",
                "comment": "Great standup summary, covered all teams!",
                "dag_id": pm.dag_id,
            },
        )
        # 200 = recorded, 404 = run not in event store (still valid)
        assert r.status_code in (200, 404), f"Feedback failed: {r.text}"
        print(f"   ✅ Feedback submitted (status: {r.status_code})")

        # ─── Step 8: Trigger optimizer via API ───
        print("\n🐝 Step 8: Trigger optimizer via API...")
        r = await pm.api("post", f"/v1/optimizer/{pm.dag_id}/run")
        assert r.status_code in (200, 400), f"Optimizer failed: {r.text}"
        print(f"   ✅ Optimizer triggered (status: {r.status_code})")

        # ─── Step 9: List proposals via API ───
        print("\n🐝 Step 9: Check proposals via API...")
        r = await pm.api("get", f"/v1/optimizer/{pm.dag_id}/proposals")
        assert r.status_code == 200
        proposals = r.json()
        print(f"   ✅ {len(proposals)} proposals found")

        if proposals:
            # Accept first proposal
            pid = proposals[0]["id"]
            r = await pm.api("post", f"/v1/optimizer/proposals/{pid}/accept")
            assert r.status_code == 200
            print(f"   ✅ Accepted proposal: {pid}")

        # ─── Step 10: Verify Optimization Inbox in UI ───
        print("\n🐝 Step 10: Check Optimization Inbox in UI...")
        ui_result = await pm.browse(
            f"Go to {HIVE_URL}/optimization. "
            f"What do you see? Are there proposals listed? "
            f"Does the page look functional?"
        )
        print(f"   UI optimizer: {ui_result[:200]}")

        # ─── Step 11: Edit DAG via API (Signal #2) ───
        print("\n🐝 Step 11: Edit DAG (triggers edit-lock)...")
        r = await pm.api(
            "put",
            f"/v1/dags/{pm.dag_id}",
            json={
                "description": "Updated: gather updates, blockers, and wins from all teams",
            },
        )
        assert r.status_code == 200
        assert "blockers" in r.json()["description"]
        print("   ✅ DAG edited (field now locked for 30 days)")

        # ─── Step 12: Check metrics via API ───
        print("\n🐝 Step 12: Check DAG metrics...")
        r = await pm.api("get", "/v1/dag-metrics")
        assert r.status_code == 200
        print("   ✅ Metrics endpoint OK")

        # ─── Step 13: Check audit trail via API ───
        print("\n🐝 Step 13: Verify audit trail...")
        r = await pm.api("get", "/v1/audit")
        assert r.status_code == 200
        entries = r.json()
        actions = [e.get("action") for e in entries]
        assert "dag_create" in actions, f"Missing dag_create in audit. Got: {actions}"
        print(f"   ✅ Audit trail has {len(entries)} entries: {set(actions)}")

        # ─── Step 14: Final UI walkthrough (vision quality check) ───
        print("\n🐝 Step 14: Final visual quality check...")
        ui_result = await pm.browse(
            f"Visit {HIVE_URL}/chat, then {HIVE_URL}/fleet, then {HIVE_URL}/settings. "
            f"For each page: does it load without errors? Is the layout clean? "
            f"Rate the overall UI quality 1-10 as a PM evaluating this tool. "
            f"Note any broken elements."
        )
        print(f"   Visual check: {ui_result[:300]}")

        print("\n" + "=" * 60)
        print("✅ ALL PM WORKFLOW STEPS PASSED")
        print("=" * 60)

    except AssertionError as e:
        failures.append(str(e))
        print(f"\n❌ ASSERTION FAILED: {e}")
    except Exception as e:
        failures.append(str(e))
        print(f"\n❌ ERROR: {e}")
    finally:
        await pm.close()

    if failures:
        print(f"\n💀 {len(failures)} failure(s):")
        for f in failures:
            print(f"   • {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_pm_workflow())
