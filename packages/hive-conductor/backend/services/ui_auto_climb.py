"""Autonomous UI hill-climber — no human in the loop.

Runs end-to-end:
1. Playwright screenshots the running app
2. Vision model scores the screenshot against canonical UIs
3. Code model scores the component code
4. Identifies the single top issue
5. Generates a targeted edit
6. Applies it
7. Compiles + rebuilds
8. Screenshots again
9. Re-scores — accept if improved, revert if not
10. Repeat until converged or max passes

Usage:
    python -m services.ui_auto_climb --component Chat --passes 10 --url http://localhost:8101
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.ui_auto")

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
PAGES_DIR = FRONTEND_DIR / "src" / "pages"


async def screenshot(url: str, path: str = "/chat") -> str:
    """Screenshot the running app via Playwright. Returns base64 PNG."""
    script = f"""
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={{"width": 1280, "height": 800}})
        await page.goto("{url}{path}", wait_until="networkidle", timeout=15000)
        await page.wait_for_timeout(1000)
        buf = await page.screenshot(type="png", full_page=False)
        await browser.close()
        import base64
        print(base64.b64encode(buf).decode())
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.error(f"Screenshot failed: {result.stderr[:200]}")
        return ""
    return result.stdout.strip()


async def score_visual(screenshot_b64: str) -> dict[str, Any]:
    """Score screenshot with vision model."""
    if not screenshot_b64:
        return {"score": 0, "error": "no screenshot"}

    base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    key = os.environ.get("LITELLM_API_KEY", "")

    prompt = """Score this AI tool UI screenshot 0-100. Compare to ChatGPT, Linear, Notion.

Criteria:
1. CLARITY (20): Obvious what to do in 3 seconds?
2. DENSITY (20): Info-rich without clutter?
3. SPEED (20): Feels fast? No unnecessary elements?
4. HIERARCHY (20): One clear primary action? Eyes flow naturally?
5. FUNCTIONALITY (20): Features accessible without hunting?

Reply JSON: {"score": int, "clarity": int, "density": int, "speed": int, "hierarchy": int, "functionality": int, "top_issue": str, "fix": str}"""

    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "gemini-3.5-flash",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                                },
                            ],
                        }
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"score": 0, "error": str(e)}


async def generate_edit(
    code: str, visual_feedback: dict, code_feedback: dict
) -> dict[str, Any] | None:
    """Generate one targeted edit based on feedback."""
    base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    key = os.environ.get("LITELLM_API_KEY", "")

    prompt = f"""Make ONE targeted fix to this React component.

VISUAL ISSUE: {visual_feedback.get("top_issue", "none")}
CODE ISSUE: {code_feedback.get("top_issue", "none")}
SUGGESTED FIX: {visual_feedback.get("fix", code_feedback.get("fix", "none"))}

CURRENT CODE (first 4000 chars):
```
{code[:4000]}
```

Return JSON: {{"description": "what this fixes", "old": "exact substring to find in code", "new": "replacement"}}
The "old" MUST be an exact substring of the code above."""

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
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        logger.error(f"Edit generation failed: {e}")
        return None


def apply_edit(component_path: Path, edit: dict) -> bool:
    """Apply edit, compile-check, rebuild. Returns True if successful."""
    code = component_path.read_text()
    old = edit.get("old", "")
    new = edit.get("new", "")

    if not old or old not in code:
        logger.warning(f"Find string not in code: {old[:60]}")
        return False

    mutated = code.replace(old, new, 1)
    component_path.write_text(mutated)

    # Compile check
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"], cwd=str(FRONTEND_DIR), capture_output=True, text=True
    )
    if result.returncode != 0:
        logger.warning("Compile failed, reverting")
        component_path.write_text(code)
        return False

    # Rebuild
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), capture_output=True)
    return True


async def auto_climb(
    component: str, url: str = "http://localhost:8101", path: str = "/chat", max_passes: int = 10
) -> dict[str, Any]:
    """Autonomous hill-climb loop. No human needed.

    Args:
        component: component filename (e.g. "Chat.tsx")
        url: running app URL
        path: page path to screenshot
        max_passes: max iterations
    """
    component_path = PAGES_DIR / component
    if not component_path.exists():
        return {"error": f"{component} not found"}

    history = []
    best_score = 0

    for i in range(max_passes):
        print(f"\n{'=' * 40} PASS {i + 1}/{max_passes} {'=' * 40}")

        # 1. Screenshot
        img = await screenshot(url, path)

        # 2. Score visual
        visual = await score_visual(img) if img else {"score": 0, "top_issue": "screenshot failed"}

        # 3. Score code
        from services.ui_hill_climber import score_ui_code

        code_result = await score_ui_code(component_path.read_text())

        combined = (visual.get("score", 0) + code_result.get("score", 0)) // 2
        print(
            f"  Visual: {visual.get('score', '?')}/100 | Code: {code_result.get('score', '?')}/100 | Combined: {combined}/100"
        )
        print(f"  Visual issue: {visual.get('top_issue', '?')[:80]}")
        print(f"  Code issue: {code_result.get('top_issue', '?')[:80]}")

        if i == 0:
            best_score = combined
            history.append({"pass": i + 1, "score": combined, "action": "baseline"})
            # Continue to first edit
        elif combined > best_score:
            best_score = combined
            history.append({"pass": i + 1, "score": combined, "action": "accepted"})
        else:
            history.append({"pass": i + 1, "score": combined, "action": "no_improvement"})

        # 4. Generate edit
        edit = await generate_edit(component_path.read_text(), visual, code_result)
        if not edit:
            print("  ✗ No edit generated")
            continue

        print(f"  Edit: {edit.get('description', '?')}")

        # 5. Apply, compile, rebuild
        if apply_edit(component_path, edit):
            print("  ✓ Applied + rebuilt")
        else:
            print("  ✗ Edit failed (find not matched or compile error)")

    print(f"\n{'=' * 40} DONE {'=' * 40}")
    print(f"Best score: {best_score}/100 over {max_passes} passes")
    return {"best_score": best_score, "passes": max_passes, "history": history}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--component", default="Chat.tsx")
    parser.add_argument("--passes", type=int, default=5)
    parser.add_argument("--url", default="http://localhost:8101")
    parser.add_argument("--path", default="/chat")
    args = parser.parse_args()

    asyncio.run(auto_climb(args.component, args.url, args.path, args.passes))
