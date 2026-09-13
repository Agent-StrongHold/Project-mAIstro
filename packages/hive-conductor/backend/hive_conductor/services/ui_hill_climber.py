"""UI hill-climber — scores both screenshots AND code against canonical examples.

Two evaluation axes:
1. VISUAL: screenshot of our UI vs screenshots of top sites (vision model)
2. CODE: our component code vs code from top open-source UI projects

The hill-climber mutates the code, renders it, screenshots it, and scores
both the visual result AND the code quality against the corpus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.ui_eval")

# Canonical examples of good UI — the sites billions of people use
CANONICAL_UIS = [
    {"name": "Google", "url": "google.com", "why": "One input, zero clutter, instant value"},
    {"name": "ChatGPT", "url": "chatgpt.com", "why": "Single thread, streaming, minimal chrome"},
    {"name": "Linear", "url": "linear.app", "why": "Fast, keyboard-first, beautiful density"},
    {"name": "Notion", "url": "notion.so", "why": "Blocks, slash commands, progressive disclosure"},
    {
        "name": "Vercel",
        "url": "vercel.com/dashboard",
        "why": "Status at a glance, deploy in one click",
    },
    {
        "name": "Stripe Dashboard",
        "url": "dashboard.stripe.com",
        "why": "Data-dense but scannable, clear hierarchy",
    },
]


async def score_ui_visual(
    screenshot_b64: str, reference_descriptions: list[str] | None = None
) -> dict[str, Any]:
    """Score a UI screenshot against canonical examples using vision model.

    Args:
        screenshot_b64: base64-encoded PNG of our UI
        reference_descriptions: optional text descriptions of what good looks like
    """
    base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    key = os.environ.get("LITELLM_API_KEY", "")

    refs = reference_descriptions or [f"{c['name']}: {c['why']}" for c in CANONICAL_UIS]
    refs_text = "\n".join(f"- {r}" for r in refs)

    prompt = f"""You are a UI/UX expert evaluating a web application screenshot.

Score this UI 0-100 against these canonical examples of what good looks like:
{refs_text}

Evaluate on:
1. CLARITY (20 pts): Is it immediately obvious what to do? Can a non-technical user figure it out in 3 seconds?
2. DENSITY (20 pts): Is information presented efficiently without clutter? Like Linear/Stripe — dense but scannable.
3. SPEED PERCEPTION (20 pts): Does it FEEL fast? Minimal loading states, instant feedback, no unnecessary transitions.
4. VISUAL HIERARCHY (20 pts): Is there one clear primary action? Do eyes flow naturally? Like Google — one input dominates.
5. FUNCTIONALITY ACCESS (20 pts): Can you reach ALL features without hunting? Like Linear — everything is there but layered. Dashboard shows what needs attention NOW, actions are obvious, deep features are one click away not buried in menus.

Key principle: A great dashboard presents ALL the info you need quickly AND makes it clear how to act on it. Not fewer features — better presentation of features.

Reply JSON: {{"score": int, "clarity": int, "density": int, "speed": int, "hierarchy": int, "functionality": int, "top_issue": str, "fix": str}}"""

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
        logger.error(f"Visual scoring failed: {e}")
        return {"score": 0, "error": str(e)}


async def score_ui_code(component_code: str) -> dict[str, Any]:
    """Score UI component code against patterns from top open-source projects.

    Evaluates: readability, component structure, accessibility, performance patterns.
    """
    base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    key = os.environ.get("LITELLM_API_KEY", "")

    prompt = f"""You are evaluating React/TypeScript UI component code against the standards of top open-source projects (Linear, Vercel, Shadcn, Radix).

Score this code 0-100:

1. SIMPLICITY (20 pts): Minimal state, no unnecessary abstractions, easy to read top-to-bottom.
2. ACCESSIBILITY (20 pts): aria-labels, keyboard navigation, semantic HTML, focus management.
3. PERFORMANCE (20 pts): No unnecessary re-renders, lazy loading where appropriate, minimal bundle impact.
4. COMPONENT DESIGN (20 pts): Single responsibility, composable, props make sense, no prop drilling.
5. RESPONSIVE (20 pts): Works on mobile without separate code paths, uses modern CSS (grid/flex/container queries).

Code to evaluate:
```tsx
{component_code[:4000]}
```

Reply JSON: {{"score": int, "simplicity": int, "accessibility": int, "performance": int, "design": int, "responsive": int, "top_issue": str, "fix": str}}"""

    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "claude-opus-4-6",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        logger.error(f"Code scoring failed: {e}")
        return {"score": 0, "error": str(e)}


async def score_ui_full(screenshot_b64: str, component_code: str) -> dict[str, Any]:
    """Score both visual AND code. Combined score is the quality bar."""
    visual, code = await asyncio.gather(
        score_ui_visual(screenshot_b64),
        score_ui_code(component_code),
    )
    combined = (visual.get("score", 0) + code.get("score", 0)) // 2
    return {
        "combined_score": combined,
        "visual": visual,
        "code": code,
    }


async def generate_ui_mutation(
    current_code: str, visual_feedback: dict, code_feedback: dict
) -> str:
    """Generate a TARGETED EDIT — fix the single top issue, not a rewrite.

    Like the DAG hill-climber: one mutation per pass. Small, testable, reversible.
    """
    base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    key = os.environ.get("LITELLM_API_KEY", "")

    prompt = f"""You are making ONE targeted edit to improve a React component.

DO NOT rewrite the file. Make the SMALLEST change that fixes the top issue.

TOP ISSUE (visual): {visual_feedback.get("top_issue", "none")}
TOP ISSUE (code): {code_feedback.get("top_issue", "none")}
SUGGESTED FIX: {code_feedback.get("fix", visual_feedback.get("fix", "none"))}

Pick the SINGLE highest-impact fix. Output a JSON diff:
{{
  "description": "what this edit does in one sentence",
  "find": "exact string to find in the current code (copy-paste exact, including whitespace)",
  "replace": "what to replace it with"
}}

If the fix requires adding new code (not replacing), use:
{{
  "description": "what this adds",
  "insert_after": "exact line to insert after",
  "code": "new code to insert"
}}

CURRENT CODE (first 3000 chars):
```tsx
{current_code[:3000]}
```

Output ONLY the JSON object. One edit. Smallest possible change for maximum score improvement."""

    try:
        async with shared_client(timeout=60.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "claude-opus-4-6",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            edit = json.loads(content)

            # Apply the targeted edit
            if "find" in edit and "replace" in edit:
                if edit["find"] in current_code:
                    result = current_code.replace(edit["find"], edit["replace"], 1)
                    logger.info(f"UI mutation applied: {edit.get('description', 'edit')}")
                    return result
                else:
                    logger.warning(f"UI mutation find string not found: {edit['find'][:80]}")
                    return current_code
            elif "insert_after" in edit and "code" in edit:
                if edit["insert_after"] in current_code:
                    idx = current_code.index(edit["insert_after"]) + len(edit["insert_after"])
                    result = current_code[:idx] + "\n" + edit["code"] + current_code[idx:]
                    logger.info(f"UI mutation inserted: {edit.get('description', 'insert')}")
                    return result
                else:
                    logger.warning(
                        f"UI mutation insert_after not found: {edit['insert_after'][:80]}"
                    )
                    return current_code
            else:
                logger.warning(f"UI mutation unknown format: {list(edit.keys())}")
                return current_code
    except Exception as e:
        logger.error(f"Mutation generation failed: {e}")
        return current_code  # return unchanged on failure


async def hill_climb_ui(component_path: str, screenshot_fn, n_passes: int = 5) -> dict[str, Any]:
    """Hill-climb a UI component: score → mutate → screenshot → re-score → accept/reject.

    Args:
        component_path: path to the .tsx file
        screenshot_fn: async callable that returns base64 PNG of the rendered component
        n_passes: number of optimization passes
    """
    current_code = Path(component_path).read_text()
    best_score = 0
    history = []

    for i in range(n_passes):
        # Screenshot current state
        screenshot = await screenshot_fn()

        # Score both visual and code
        result = await score_ui_full(screenshot, current_code)
        score = result["combined_score"]

        if i == 0:
            best_score = score
            history.append({"pass": i, "score": score, "action": "baseline"})
            continue

        if score > best_score:
            best_score = score
            history.append({"pass": i, "score": score, "action": "accepted"})
        else:
            history.append({"pass": i, "score": score, "action": "rejected"})
            # Revert
            current_code = Path(component_path).read_text()
            continue

        # Generate mutation based on feedback
        mutated = await generate_ui_mutation(current_code, result["visual"], result["code"])

        # Write mutation
        Path(component_path).write_text(mutated)
        current_code = mutated

    return {"best_score": best_score, "passes": n_passes, "history": history}
