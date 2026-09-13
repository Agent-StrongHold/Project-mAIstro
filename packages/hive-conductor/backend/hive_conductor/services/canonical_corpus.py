"""Canonical corpus builder — finds 100 examples of what good looks like, then hill-climbs against them.

This is the core loop:
1. Pick a domain (children's books, UI design, press releases, anything)
2. Search for 100 canonically good examples in that domain
3. Extract what makes them good (patterns, not rules)
4. Score new output by similarity to the corpus
5. Hill-climb: mutate, re-score against the corpus, accept if closer to good

The corpus IS the eval. Not abstract criteria — real examples of real things that won.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("hive.corpus")


class CanonicalCorpus:
    """A collection of 100 canonically good examples for a domain.

    The corpus is the quality bar. Scoring = how similar is your output
    to the things that already won in this domain?
    """

    def __init__(self, domain: str, audience: str = ""):
        self.domain = domain
        self.audience = audience
        self.examples: list[dict[str, Any]] = []  # {title, source, snippet, url, why_good}
        self.patterns: list[str] = []  # extracted from the corpus
        self._built = False

    @property
    def size(self) -> int:
        return len(self.examples)

    async def build(self, target_size: int = 100) -> None:
        """Search and collect canonically good examples until we hit target_size."""
        brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
        if not brave_key:
            logger.error("BRAVE_SEARCH_API_KEY required to build corpus")
            return

        # Generate diverse search queries to find examples from different angles
        queries = await self._generate_search_queries(target_size)

        for q in queries:
            if self.size >= target_size:
                break
            await asyncio.sleep(1.1)  # rate limit
            results = await self._search(q, brave_key)
            for r in results:
                if self.size >= target_size:
                    break
                # Deduplicate by URL
                if not any(e.get("url") == r.get("url") for e in self.examples):
                    self.examples.append(r)

        # Extract patterns from the corpus
        if self.examples:
            self.patterns = await self._extract_patterns()
            self._built = True

        logger.info(
            f"Corpus built: {self.size} examples, {len(self.patterns)} patterns for '{self.domain}'"
        )

    async def _generate_search_queries(self, target_size: int) -> list[str]:
        """Generate diverse queries to find examples from multiple angles."""
        base_queries = [
            f"best {self.domain} examples {self.audience}",
            f"award winning {self.domain} {self.audience}",
            f"top rated {self.domain} goodreads OR reviews OR G2",
            f"{self.domain} bestseller list 2024",
            f"most popular {self.domain} {self.audience} all time",
            f"{self.domain} masterclass examples what makes great",
            f"canonical {self.domain} examples every professional should study",
            f"{self.domain} hall of fame best ever made",
            f"why {self.domain} works analysis breakdown",
            f"{self.domain} case study success metrics",
            f"reddit best {self.domain} recommendations {self.audience}",
            f"{self.domain} portfolio examples inspiration",
            f"NYT bestseller {self.domain} OR amazon top {self.domain}",
            f"{self.domain} that changed the industry examples",
            f"beginner {self.domain} vs expert {self.domain} difference",
            f"{self.domain} competition winners 2024 2023",
            f"most shared {self.domain} viral examples",
            f"{self.domain} templates proven to convert",
            f"expert {self.domain} critique what works",
            f"{self.domain} before and after improvement examples",
        ]
        # Need ~target_size/5 queries (each returns ~5 results)
        needed = (target_size // 5) + 2
        return base_queries[:needed]

    async def _search(self, query: str, api_key: str) -> list[dict[str, Any]]:
        """Search Brave for examples."""
        try:
            async with shared_client(timeout=15.0) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params={"q": query, "count": 5},
                )
                r.raise_for_status()
                data = r.json()
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("description", "")[:200],
                        "query": query,
                    }
                    for r in data.get("web", {}).get("results", [])[:5]
                ]
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            return []

    async def _extract_patterns(self) -> list[str]:
        """Use LLM to extract what makes these examples good — patterns, not rules."""
        base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        key = os.environ.get("LITELLM_API_KEY", "")

        sample = self.examples[:30]  # Use first 30 for pattern extraction
        examples_text = "\n".join(f"- {e['title']}: {e['snippet']}" for e in sample)

        prompt = f"""You have {len(sample)} examples of canonically good {self.domain} (audience: {self.audience or "general"}).

Examples:
{examples_text}

Extract 10 PATTERNS (not rules) that these examples share. A pattern is something you'd recognize in the output itself — a structural choice, a rhythm, a technique.

Format: JSON array of strings. Each string is one pattern described in 1-2 sentences.
Example: ["Uses short sentences that build momentum", "Opens with a specific concrete detail, not an abstraction"]

Output: {{"patterns": [str]}}"""

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
                return data.get("patterns", [])
        except Exception as e:
            logger.error(f"Pattern extraction failed: {e}")
            return []

    async def discover_new_holdout(self, n: int = 5) -> list[dict[str, Any]]:
        """Find genuinely NEW examples the corpus has never seen.

        Anti-overfitting: each hill-climb pass searches with a novel query,
        finds examples that aren't in the corpus yet. The system literally
        cannot overfit to these because it didn't know they existed.
        """
        brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
        if not brave_key:
            return []

        known_urls = {e.get("url") for e in self.examples}

        import random

        angles = [
            f"new {self.domain} 2024 2025 released recently",
            f"{self.domain} underrated hidden gem {self.audience}",
            f"reddit recommend {self.domain} {self.audience} this month",
            f"{self.domain} trending viral recent",
            f"indie {self.domain} breakout success {self.audience}",
            f"{self.domain} debut award nominee 2024",
            f"tiktok booktok {self.domain} popular {self.audience}",
            f"best new {self.domain} nobody talks about",
        ]
        query = random.choice(angles)

        await asyncio.sleep(1.1)
        results = await self._search(query, brave_key)
        new_examples = [r for r in results if r.get("url") not in known_urls]

        for ex in new_examples[:n]:
            ex["discovered_at_pass"] = self.size
            ex["holdout"] = True
            self.examples.append(ex)

        return new_examples[:n]

    async def hill_climb_pass(self, output_baseline: str, output_mutated: str) -> dict[str, Any]:
        """One hill-climb pass with genuinely new held-out examples.

        1. Score baseline against known corpus
        2. Discover NEW examples (never seen before — no lookahead bias)
        3. Score mutated against known corpus (target)
        4. Score mutated against NEW examples (held-out)
        5. Accept only if improves on known AND doesn't fail on new
        """
        baseline_result = await self.score(output_baseline)
        new_examples = await self.discover_new_holdout(n=3)
        mutated_result = await self.score(output_mutated)
        holdout_result = await self._score_against_new(output_mutated, new_examples)

        target_improved = mutated_result.get("score", 0) > baseline_result.get("score", 0)
        holdout_ok = holdout_result.get("score", 0) >= 40

        return {
            "accepted": target_improved and holdout_ok,
            "baseline_score": baseline_result.get("score", 0),
            "mutated_score": mutated_result.get("score", 0),
            "holdout_score": holdout_result.get("score", 0),
            "new_examples_found": len(new_examples),
            "reason": "improved + passed on genuinely new"
            if (target_improved and holdout_ok)
            else (
                "no improvement on known" if not target_improved else "failed on unseen examples"
            ),
            "new_examples": [e.get("title", "") for e in new_examples],
        }

    async def _score_against_new(self, output: str, examples: list[dict]) -> dict[str, Any]:
        """Score against specific newly-discovered examples."""
        if not examples:
            return {"score": 50}

        base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        key = os.environ.get("LITELLM_API_KEY", "")

        examples_text = "\n".join(f"- {e['title']}: {e['snippet']}" for e in examples)
        prompt = f"""Score this {self.domain} output against these NEWLY DISCOVERED examples of what's currently good.
These are fresh — they represent what's succeeding RIGHT NOW.

New examples found:
{examples_text}

Output to score:
{output[:2000]}

Does this output match the quality bar set by these new examples? Score 0-100.
Reply JSON: {{"score": int, "rationale": str}}"""

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
                return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            return {"score": 0, "error": str(e)}

    async def score(self, output: str) -> dict[str, Any]:
        """Score output against the corpus. How close is it to canonically good?"""
        if not self._built:
            return {"score": 0, "error": "corpus not built yet"}

        base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        key = os.environ.get("LITELLM_API_KEY", "")

        patterns_text = "\n".join(f"- {p}" for p in self.patterns)
        sample_titles = "\n".join(f"- {e['title']}" for e in self.examples[:20])

        prompt = f"""You are scoring output against a corpus of {self.size} canonically good examples of {self.domain}.

The corpus includes things like:
{sample_titles}

Patterns found in the corpus (what makes them good):
{patterns_text}

Score this output 0-100. How close is it to the quality bar set by the corpus?
- 90-100: Could be in the corpus. Matches the patterns. Would win in this domain.
- 70-89: Good but missing 1-2 patterns. Close to corpus quality.
- 50-69: Mediocre. Has some patterns but feels amateur compared to corpus.
- 0-49: Doesn't belong in the same category as the corpus examples.

Output to score:
{output[:3000]}

Reply JSON: {{"score": int, "matches": [str], "missing": [str], "suggestion": str}}"""

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
                return json.loads(content)
        except Exception as e:
            return {"score": 0, "error": str(e)}

    def to_dict(self) -> dict[str, Any]:
        """Serialize corpus for storage."""
        return {
            "domain": self.domain,
            "audience": self.audience,
            "examples": self.examples,
            "patterns": self.patterns,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalCorpus:
        """Load corpus from storage."""
        c = cls(data["domain"], data.get("audience", ""))
        c.examples = data.get("examples", [])
        c.patterns = data.get("patterns", [])
        c._built = bool(c.examples and c.patterns)
        return c
