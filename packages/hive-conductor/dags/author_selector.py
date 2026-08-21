"""Author selector — picks the right examples based on audience and length.

The user never picks authors. They say:
  - "bedtime story for my 3-year-old"
  - "my 8-year-old loves funny books"
  - "chapter book for a kid who likes Percy Jackson"

The system maps (age, length, purpose) → best author examples automatically.

ALSO: searches Goodreads and NYT bestseller lists via Brave Search to
find what's CURRENTLY popular for this age/genre — not just our static list.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dags.author_examples import (
    CAPTAIN_UNDERPANTS,
    DIARY_OF_A_WIMPY_KID,
    DOG_MAN,
    DRAGONS_LOVE_TACOS,
    ELEPHANT_AND_PIGGIE,
    ENGAGEMENT_PRINCIPLES,
    ERIC_CARLE,
    FROG_AND_TOAD,
    GOODNIGHT_MOON,
    GUESS_HOW_MUCH,
    HARRY_POTTER,
    HUNGER_GAMES_YA,
    JULIA_DONALDSON,
    JUNIE_B_JONES,
    MAGIC_TREE_HOUSE,
    MO_WILLEMS,
    PERCY_JACKSON,
    PETE_THE_CAT,
    ROALD_DAHL,
    SEUSS,
    THE_BAD_GUYS,
)
from maistro.http import shared_client


def _bedtime_authors(age: int) -> list[dict]:
    candidates = [GOODNIGHT_MOON, GUESS_HOW_MUCH]
    if age <= 3:
        candidates.insert(0, GOODNIGHT_MOON)  # weight Brown higher for youngest
    return candidates[:2]


def _picture_book_authors(purpose: str, tone: str) -> list[dict]:
    if tone == "silly" or purpose == "funny":
        candidates = [DRAGONS_LOVE_TACOS, MO_WILLEMS, PETE_THE_CAT]
    elif purpose == "educational":
        candidates = [ERIC_CARLE, PETE_THE_CAT, SEUSS]
    elif "rhyme" in tone or "sing" in tone:
        candidates = [JULIA_DONALDSON, SEUSS, PETE_THE_CAT]
    elif "interactive" in purpose:
        candidates = [MO_WILLEMS, PETE_THE_CAT, DRAGONS_LOVE_TACOS]
    else:
        candidates = [ERIC_CARLE, MO_WILLEMS, JULIA_DONALDSON]
    return candidates[:3]


def _early_reader_authors(purpose: str, tone: str) -> list[dict]:
    if tone == "silly" or purpose == "funny":
        candidates = [ELEPHANT_AND_PIGGIE, JUNIE_B_JONES, PETE_THE_CAT]
    elif tone == "warm" or purpose == "friendship":
        candidates = [FROG_AND_TOAD, ELEPHANT_AND_PIGGIE]
    elif purpose == "series":
        candidates = [JUNIE_B_JONES, ELEPHANT_AND_PIGGIE, FROG_AND_TOAD]
    else:
        candidates = [JUNIE_B_JONES, FROG_AND_TOAD, ELEPHANT_AND_PIGGIE]
    return candidates[:3]


def _chapter_book_authors(purpose: str, tone: str) -> list[dict]:
    if tone == "silly" or purpose == "funny" or "reluctant reader" in purpose:
        candidates = [DOG_MAN, CAPTAIN_UNDERPANTS, DIARY_OF_A_WIMPY_KID]
    elif purpose == "adventure" or tone == "exciting":
        candidates = [MAGIC_TREE_HOUSE, PERCY_JACKSON, ROALD_DAHL]
    elif purpose == "series":
        candidates = [MAGIC_TREE_HOUSE, DOG_MAN, DIARY_OF_A_WIMPY_KID]
    elif "villain" in tone or "dark" in tone:
        candidates = [ROALD_DAHL, THE_BAD_GUYS, PERCY_JACKSON]
    elif purpose == "educational":
        candidates = [MAGIC_TREE_HOUSE, ROALD_DAHL]
    else:
        candidates = [ROALD_DAHL, MAGIC_TREE_HOUSE, DOG_MAN]
    return candidates[:3]


def _middle_grade_authors(purpose: str, tone: str) -> list[dict]:
    if purpose == "adventure" or tone == "exciting":
        candidates = [PERCY_JACKSON, HUNGER_GAMES_YA, HARRY_POTTER]
    elif purpose == "funny" or tone == "silly":
        candidates = [DIARY_OF_A_WIMPY_KID, CAPTAIN_UNDERPANTS, THE_BAD_GUYS]
    elif purpose == "series" or "fantasy" in purpose:
        candidates = [HARRY_POTTER, PERCY_JACKSON, HUNGER_GAMES_YA]
    else:
        candidates = [HARRY_POTTER, PERCY_JACKSON, DIARY_OF_A_WIMPY_KID]
    return candidates[:3]


def select_authors(age: int, word_count: int, purpose: str = "", tone: str = "") -> list[dict]:
    """Pick 2-3 author examples based on audience and format.

    Args:
        age: target reader age (2-14)
        word_count: target length
        purpose: "bedtime", "educational", "entertainment", "adventure", "funny", "series"
        tone: "calm", "silly", "exciting", "scary", "warm"
    """
    # --- BEDTIME (any age under 7, calm tone, or explicit purpose) ---
    if purpose == "bedtime" or (tone == "calm" and age <= 6):
        return _bedtime_authors(age)
    # --- PICTURE BOOKS (ages 2-5, under 500 words) ---
    if age <= 5 and word_count <= 500:
        return _picture_book_authors(purpose, tone)
    # --- EARLY READERS (ages 5-7, 300-1000 words) ---
    if age <= 7 and word_count <= 1000:
        return _early_reader_authors(purpose, tone)
    # --- CHAPTER BOOKS (ages 7-10, 1000-5000 words) ---
    if age <= 10:
        return _chapter_book_authors(purpose, tone)
    # --- MIDDLE GRADE / YA (ages 10-14) ---
    if age <= 14:
        return _middle_grade_authors(purpose, tone)
    # Fallback
    return [ROALD_DAHL, HARRY_POTTER, PERCY_JACKSON][:2]


def format_examples_for_prompt(authors: list[dict]) -> str:
    """Format selected author examples into a prompt-ready string."""
    parts = []
    for a in authors:
        example = a.get("example", "")
        rules = a.get("rules", [])
        parts.append(
            f"**{a['author']}** ({a['books'][0]}):\n"
            f'"{example[:200]}"\n'
            f"Rules: {'; '.join(rules[:3])}"
        )
    # Add engagement principles
    parts.append(
        "\n**Why kids stay hooked:**\n"
        + "\n".join(f"- {v}" for v in list(ENGAGEMENT_PRINCIPLES.values())[:4])
    )
    return "\n\n".join(parts)


async def search_bestsellers(age: int, genre: str = "", tone: str = "") -> dict[str, Any]:
    """Search Goodreads + NYT bestseller lists for what's popular NOW for this audience.

    Returns real book titles, ratings, and why they're popular — used as
    additional context for the writing nodes alongside our static examples.
    """

    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not brave_key:
        return {"books": [], "source": "none"}

    # Build age-appropriate search query
    if age <= 5:
        age_term = "picture books toddler preschool"
    elif age <= 7:
        age_term = "early reader beginning chapter books ages 5-7"
    elif age <= 10:
        age_term = "middle grade chapter books ages 8-10"
    else:
        age_term = "middle grade YA young adult ages 10-14"

    query = f"goodreads best {age_term} {genre} {tone} 2024 highest rated".strip()

    try:
        await asyncio.sleep(1.1)  # Brave rate limit
        async with shared_client(timeout=15.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                params={"q": query, "count": 5},
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("web", {}).get("results", [])[:5]
            return {
                "query": query,
                "books": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("description", "")[:150],
                    }
                    for r in results
                ],
                "source": "brave+goodreads",
            }
    except Exception:
        return {"books": [], "source": "error"}


async def get_writing_context(
    age: int, word_count: int, purpose: str = "", tone: str = ""
) -> dict[str, Any]:
    """Full context for a creative writing DAG: static examples + live bestseller data.

    This is what gets injected into the writing prompts:
    1. Static author examples (proven techniques with real passages)
    2. Live bestseller/Goodreads data (what's popular RIGHT NOW for this audience)
    3. Engagement principles (why kids stay hooked)
    """
    # Static examples based on age/length/tone
    authors = select_authors(age, word_count, purpose, tone)
    examples_text = format_examples_for_prompt(authors)

    # Live bestseller search
    bestsellers = await search_bestsellers(age, purpose, tone)

    return {
        "static_examples": examples_text,
        "authors_selected": [a["author"] for a in authors],
        "bestseller_context": bestsellers,
        "age": age,
        "word_count": word_count,
        "purpose": purpose,
        "tone": tone,
    }
