"""Eval bootstrapper — discovers what 'good' looks like for ANY topic.

Given a new content type, this module:
1. Searches for best-in-class examples (Goodreads, bestsellers, awards, top-rated)
2. Fetches real examples of what good looks like
3. Extracts patterns/rules from those examples via LLM
4. Generates eval criteria automatically
5. Returns a RubricEval that scores output against discovered standards

No hand-coding. The system learns what 'good' means by looking at what
already succeeded in the market.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.eval_bootstrap")


async def discover_quality_bar(topic: str, audience: str = "") -> dict[str, Any]:
    """Search for what 'good' looks like for this topic.

    Returns real examples, patterns, and auto-generated eval criteria.
    """
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not brave_key:
        return {"error": "BRAVE_SEARCH_API_KEY required", "criteria": []}

    # Search for best examples
    queries = [
        f"best {topic} examples award winning",
        f"top rated {topic} {audience} goodreads OR reviews",
        f"{topic} writing craft techniques what makes good",
    ]

    all_results = []
    for q in queries:
        await asyncio.sleep(1.1)
        try:
            async with shared_client(timeout=15.0) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                    params={"q": q, "count": 5},
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("web", {}).get("results", [])[:5]
                all_results.extend(
                    [
                        {
                            "title": r.get("title", ""),
                            "snippet": r.get("description", "")[:200],
                            "url": r.get("url", ""),
                        }
                        for r in results
                    ]
                )
        except Exception as e:
            logger.warning(f"Search failed for '{q}': {e}")

    if not all_results:
        return {"examples": [], "criteria": [], "error": "no search results"}

    # Use LLM to extract patterns and generate eval criteria
    criteria = await _extract_criteria(topic, audience, all_results)

    return {
        "topic": topic,
        "audience": audience,
        "examples_found": len(all_results),
        "sources": [r["url"] for r in all_results[:10]],
        "criteria": criteria,
    }


async def _extract_criteria(
    topic: str, audience: str, examples: list[dict]
) -> list[dict[str, Any]]:
    """Use LLM to extract eval criteria from discovered examples."""
    base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    key = os.environ.get("LITELLM_API_KEY", "")

    examples_text = "\n".join(f"- {e['title']}: {e['snippet']}" for e in examples[:10])

    prompt = f"""You are analyzing what makes great {topic} (audience: {audience or "general"}).

Based on these real examples of highly-rated {topic}:

{examples_text}

Extract exactly 5 eval criteria that distinguish GREAT {topic} from mediocre ones.
These criteria will be used to score GENERATED TEXT — so the signals must be
things you'd find IN the text itself, not in reviews about it.

For each criterion, provide:
- name: short snake_case identifier
- description: what it measures in the actual output text
- weight: importance 1-30 (must sum to 100)
- positive_signals: list of 4+ words/phrases you'd find IN good output text
- negative_signals: list of 3+ words/phrases you'd find IN bad output text

Example for children's books:
  positive_signals: ["once upon", "said", "!", "again", "but then"]
  negative_signals: ["however", "furthermore", "approximately", "subsequently"]

Output JSON: {{"criteria": [{{"name": str, "description": str, "weight": int, "positive_signals": [str], "negative_signals": [str]}}]}}"""

    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": os.environ.get("CHAT_DEFAULT_MODEL", "claude-opus-4-6"),
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return data.get("criteria", [])
    except Exception as e:
        logger.error(f"Criteria extraction failed: {e}")
        return []


def build_eval_from_criteria(topic: str, criteria: list[dict[str, Any]]):
    """Build a working RubricEval class from auto-discovered criteria."""
    from eval.departments import RubricEval

    eval_criteria = []
    for c in criteria:
        positive = c.get("positive_signals", [])
        negative = c.get("negative_signals", [])
        weight = c.get("weight", 20)

        def make_check(pos, neg):
            def check(output, context):
                has_positive = any(s.lower() in output.lower() for s in pos)
                has_negative = any(s.lower() in output.lower() for s in neg) if neg else False
                return has_positive and not has_negative

            return check

        eval_criteria.append(
            {
                "name": c["name"],
                "weight": weight,
                "check": make_check(positive, negative),
            }
        )

    class AutoEval(RubricEval):
        department = "auto"
        eval_name = f"auto_{topic.replace(' ', '_')[:30]}"

    instance = AutoEval()
    instance.criteria = eval_criteria
    instance.department = "auto"
    instance.eval_name = f"auto_{topic.replace(' ', '_')[:30]}"
    return instance


async def bootstrap_eval(topic: str, audience: str = ""):
    """Full pipeline: discover what good looks like → build eval.

    Usage:
        eval_instance = await bootstrap_eval("children's picture book", "ages 3-5")
        result = await eval_instance.score(my_output)
        print(result.score)  # 0-100 based on auto-discovered criteria
    """
    discovery = await discover_quality_bar(topic, audience)
    criteria = discovery.get("criteria", [])
    if not criteria:
        return None
    return build_eval_from_criteria(topic, criteria)
