"""Architecture-fit signal: does a change conform to the ADRs/specs *as designed*?

Registry validation (schema/lint/link-check) is a mechanical gate. This is the
*semantic* signal, and it's two LLM steps, not a rule check:

  1. **Retrieve** — from the ADR/spec corpus (frontmatter: id, title, status,
     relationships), have the model pick which decisions actually govern the
     proposed change. 233 titles fit in one prompt; the `related` graph lets a
     hit pull in its neighbours.
  2. **Head-to-head judge** — given the change and two candidate options plus the
     full text of the retrieved ADRs/specs, decide which option best fits the
     architecture *as designed*, citing the specific decisions relied on.

The verdict (winner + cited ids + rationale) slots straight into evolve's Elo
tournament as another battle dimension — a candidate that diverges from an
Accepted ADR loses architecture-fit battles even if it scores well elsewhere.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

LlmCall = Callable[..., Awaitable[str]]


@dataclass
class DocRef:
    id: str
    title: str
    kind: str  # "adr" | "spec"
    status: str
    path: Path
    related: list[str] = field(default_factory=list)
    body: str = ""


@dataclass
class ArchFitVerdict:
    winner: str  # "A" | "B" | "tie"
    cited: list[str]
    rationale: str
    confidence: float


def _parse_doc(path: Path) -> DocRef | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict) or not fm.get("id"):
        return None
    related = fm.get("related") or []
    return DocRef(
        id=str(fm.get("id", "")),
        title=str(fm.get("title", "")),
        kind=str(fm.get("kind", "")),
        status=str(fm.get("status", "")),
        path=path,
        related=[str(r) for r in related] if isinstance(related, list) else [],
        body=parts[2].strip(),
    )


def load_corpus(repo_root: str | Path) -> list[DocRef]:
    """Parse every ADR/spec under docs/adr and docs/specs into DocRefs."""
    root = Path(repo_root)
    docs: list[DocRef] = []
    for sub in ("docs/adr", "docs/specs"):
        for md in sorted((root / sub).glob("*.md")):
            ref = _parse_doc(md)
            if ref is not None:
                docs.append(ref)
    return docs


def _extract_json(text: str) -> object:
    # Models wrap JSON in prose/fences; grab the first {...} or [...] block.
    for pattern in (r"```(?:json)?\s*(.*?)```", r"(\{.*\}|\[.*\])"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def select_relevant(
    change: str, corpus: list[DocRef], llm_call: LlmCall, *, k: int = 6, max_tokens: int = 1500
) -> list[DocRef]:
    """Ask the model which ADRs/specs govern the change; return them (+ neighbours).

    ``max_tokens`` is generous because reasoning models spend hidden tokens before
    emitting the id array — a tight budget returns an empty completion.
    """
    catalog = "\n".join(f"{d.id}: {d.title} [{d.kind},{d.status}]" for d in corpus)
    prompt = (
        f"A proposed change to the codebase:\n{change}\n\n"
        f"From this catalog of architecture decisions (ADRs) and specs, list the IDs "
        f"MOST relevant to judging whether the change fits the designed architecture. "
        f"Return ONLY a JSON array of up to {k} ids, most relevant first.\n\nCatalog:\n{catalog}"
    )
    resp = await llm_call([{"role": "user", "content": prompt}], max_tokens=max_tokens)
    ids = _extract_json(resp)
    if not isinstance(ids, list):
        return []
    by_id = {d.id: d for d in corpus}
    selected: dict[str, DocRef] = {}
    for raw in ids:
        doc = by_id.get(str(raw))
        if doc is None:
            continue
        selected[doc.id] = doc
        for rel in doc.related:  # pull in directly-related decisions
            rid = rel.split("#")[-1]
            if rid in by_id and rid not in selected:
                selected[rid] = by_id[rid]
    return list(selected.values())


async def judge_architecture_fit(
    change: str,
    option_a: str,
    option_b: str,
    docs: list[DocRef],
    llm_call: LlmCall,
    *,
    doc_char_budget: int = 1500,
    max_docs: int = 6,
    max_tokens: int = 2500,
) -> ArchFitVerdict:
    """Head-to-head: which option best fits the architecture the ADRs/specs describe?

    ``max_docs`` caps how many retrieved decisions are shown (most-relevant first)
    and ``max_tokens`` is deliberately generous — reasoning models spend hidden
    tokens before emitting the JSON verdict, and starving them returns empty.
    """
    context = "\n\n".join(
        f"### {d.id}: {d.title}\n{d.body[:doc_char_budget]}" for d in docs[:max_docs]
    )
    prompt = (
        f"Proposed change:\n{change}\n\n"
        f"Option A:\n{option_a}\n\nOption B:\n{option_b}\n\n"
        f"Relevant architecture decisions and specs:\n{context}\n\n"
        "Judge which option best fits the architecture AS DESIGNED in these ADRs/specs — "
        "not general preference, and not expedience. Compare head-to-head. Return ONLY JSON: "
        '{"winner": "A" | "B" | "tie", "cited": ["ADR-###", ...], '
        '"rationale": "<=3 sentences", "confidence": 0.0-1.0}'
    )
    resp = await llm_call(
        [
            {
                "role": "system",
                "content": (
                    "You are a software architect enforcing this project's ADRs and specs. "
                    "Judge strictly by the designed architecture; cite the decisions you rely on."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
    )
    data = _extract_json(resp)
    if not isinstance(data, dict):
        return ArchFitVerdict(
            winner="tie", cited=[], rationale=f"unparseable: {resp[:200]}", confidence=0.0
        )
    cited = data.get("cited") or []
    return ArchFitVerdict(
        winner=str(data.get("winner", "tie")),
        cited=[str(c) for c in cited] if isinstance(cited, list) else [],
        rationale=str(data.get("rationale", "")),
        confidence=float(data.get("confidence", 0.0) or 0.0),
    )
