"""PM Vision Agent Tests — browser-use + Gemini 3.5 Flash.

Uses an AI agent with vision to navigate the UI like a real PM.
Each test gives the agent a task and asserts it completed successfully.

Requirements:
  pip install browser-use pytest-asyncio
  export GOOGLE_API_KEY=your-key

Usage:
  HIVE_URL=http://localhost:8101 pytest tests/e2e/test_pm_vision.py -v
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

# C1 (#286): collect-and-skip rather than error at import. `browser_use` is
# deliberately absent from the default image — the browser surface lives in
# `Dockerfile.research` (see the main Dockerfile's header) — and these tests
# additionally need a live conductor at HIVE_URL plus a real GOOGLE_API_KEY.
# Importing it unguarded made the whole module an ImportError at collection,
# so these tests were invisible rather than reported. Now they enumerate with
# a stated reason.
_browser_use = pytest.importorskip(
    "browser_use",
    reason="browser-use not installed (research image only — see Dockerfile.research)",
)
Agent = _browser_use.Agent
Browser = _browser_use.Browser
ChatGoogle = _browser_use.ChatGoogle

HIVE_URL = os.environ.get("HIVE_URL", "http://localhost:8101")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-preview")

# Both marks apply to every test here: they drive a real browser against a live
# conductor. `importorskip` above already covers the missing-dependency case;
# this covers "dependency present but no credentials / no running stack".
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_API_KEY"),
        reason="needs a live conductor at HIVE_URL and a real GOOGLE_API_KEY (#286)",
    ),
]


@pytest_asyncio.fixture(scope="module")
async def browser():
    b = Browser()
    yield b
    await b.close()


@pytest_asyncio.fixture(scope="module")
def llm():
    return ChatGoogle(model=MODEL)


async def run_agent(task: str, llm, browser) -> str:
    agent = Agent(task=task, llm=llm, browser=browser)
    result = await agent.run()
    return str(result)


class TestPMVisionWorkflow:
    """AI agent walks through the PM workflow with vision verification."""

    async def test_01_setup_or_login(self, llm, browser):
        result = await run_agent(
            f"Go to {HIVE_URL}. If you see a setup wizard, complete it "
            f"(name: 'Test Hive', hardware: Beast, skip modules, launch). "
            f"If you see login, log in with username 'user' password 'pmpass1234'. "
            f"Report 'SUCCESS' if you reach the main app, or 'FAILED' with reason.",
            llm,
            browser,
        )
        assert "FAILED" not in result.upper() or "SUCCESS" in result.upper()

    async def test_02_dashboard_renders(self, llm, browser):
        result = await run_agent(
            f"Go to {HIVE_URL}. Look at the page. "
            f"Does it look like a working dashboard/app? "
            f"Are there navigation items in a sidebar? "
            f"Report 'LOOKS_GOOD' if the UI is functional, "
            f"'BROKEN' if there are error messages or blank screens.",
            llm,
            browser,
        )
        assert "BROKEN" not in result.upper()

    async def test_03_can_navigate_fleet(self, llm, browser):
        result = await run_agent(
            f"Navigate to {HIVE_URL}/fleet. "
            f"Does the page load? Can you see DAGs or a way to create one? "
            f"Report 'FLEET_OK' if the page works, 'FLEET_BROKEN' if not.",
            llm,
            browser,
        )
        assert "BROKEN" not in result.upper()

    async def test_04_create_dag(self, llm, browser):
        result = await run_agent(
            f"On the Fleet page ({HIVE_URL}/fleet), create a new DAG: "
            f"name='Vision Test DAG', description='Created by AI agent'. "
            f"Look for a create/new button. If you find a form, fill it and submit. "
            f"Report 'CREATED' if successful, 'COULD_NOT_CREATE' if not.",
            llm,
            browser,
        )
        assert "COULD_NOT" not in result.upper()

    async def test_05_optimization_inbox_accessible(self, llm, browser):
        result = await run_agent(
            f"Navigate to {HIVE_URL}/optimization. "
            f"Does the Optimization Inbox page load? "
            f"What do you see — proposals, empty state, or an error? "
            f"Report 'INBOX_OK' if the page renders, 'INBOX_BROKEN' if error.",
            llm,
            browser,
        )
        assert "BROKEN" not in result.upper()

    async def test_06_settings_page(self, llm, browser):
        result = await run_agent(
            f"Navigate to {HIVE_URL}/settings. "
            f"Can you see configuration options (model, hardware preset, etc)? "
            f"Report 'SETTINGS_OK' or 'SETTINGS_BROKEN'.",
            llm,
            browser,
        )
        assert "BROKEN" not in result.upper()

    async def test_07_visual_quality_check(self, llm, browser):
        """The real value: AI judges if the UI looks professional."""
        result = await run_agent(
            f"Go to {HIVE_URL}/chat. Take a careful look at the page. "
            f"As a project manager evaluating this tool, rate it: "
            f"1. Is the layout clean and professional? "
            f"2. Are fonts readable? "
            f"3. Is navigation intuitive? "
            f"4. Any visual glitches (overlapping elements, broken images)? "
            f"Give a score 1-10 and explain. "
            f"Report 'VISUAL_PASS' if score >= 6, 'VISUAL_FAIL' if < 6.",
            llm,
            browser,
        )
        assert "VISUAL_FAIL" not in result.upper()
