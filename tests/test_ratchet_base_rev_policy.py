"""Every `RATCHET_BASE_REV` must survive a rebased topic branch.

A workflow that names the ratchet base itself overrides
`ratchet_provenance._push_event_base`, which already draws the line correctly:
a protected-branch push really does replace `github.event.before`, so that is
its base; a topic-branch push does not, so its base is the integration branch
its pull-request run uses.

Three job-level expressions had drifted off that line and fell through to
`github.event.before` for *every* push. On a topic branch `before` is the
branch's own previous tip, which any rebase orphans -- unreachable from every
ref, so `fetch-depth: 0` (which fetches refs, not orphans) cannot supply it and
the ratchet refuses with "base revision could not be resolved". The candidate
reds on a base-provenance error while its pull-request run passes on byte-identical
content, and a re-run cannot clear it because `github.event.before` is fixed in
the stored event payload.

Nothing pinned the expressions, so the two that were right and the three that
were wrong drifted apart silently. This is that pin.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

BASE_REV_KEY = "RATCHET_BASE_REV"

#: Pushes whose `before` genuinely is the revision being replaced.
PROTECTED_REFS = ("develop", "integration", "main")


def _env_values(node: Any) -> list[str]:
    """Every `RATCHET_BASE_REV` value anywhere in a workflow document.

    Job-level and step-level `env:` blocks both carry it, so this walks rather
    than reaching for either shape.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "env" and isinstance(value, dict) and BASE_REV_KEY in value:
                found.append(str(value[BASE_REV_KEY]))
            found.extend(_env_values(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_env_values(item))
    return found


def _declarations() -> list[tuple[str, str]]:
    declarations: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        declarations.extend((path.name, value) for value in _env_values(document))
    return declarations


def test_the_repository_still_names_the_ratchet_base_somewhere() -> None:
    """Guards the walk itself: a rename must fail loudly, not vacuously pass."""
    assert _declarations(), (
        f"no {BASE_REV_KEY} declaration found under {WORKFLOWS} -- "
        "if the variable was renamed, retarget this test rather than deleting it"
    )


@pytest.mark.parametrize("workflow, expression", _declarations())
def test_a_topic_push_never_falls_back_to_the_branchs_own_previous_tip(
    workflow: str, expression: str
) -> None:
    """`github.event.before` is never the unguarded final fallback.

    The failure this pins is exactly the fall-through: an expression whose last
    alternative is `before` hands a topic-branch push the orphaned SHA. Each use
    of `before` has to sit behind a `github.ref ==` guard naming a protected
    branch, and something else has to catch everything that reaches the end.
    """
    if "github.event.before" not in expression:
        return

    collapsed = " ".join(expression.split())
    assert not re.search(r"\|\|\s*github\.event\.before\s*\}\}\s*$", collapsed), (
        f"{workflow}: {BASE_REV_KEY} falls through to github.event.before for every push. "
        "A topic branch's `before` is its own previous tip and any rebase orphans it, so "
        "the ratchet cannot resolve the base. Guard it with `github.ref == 'refs/heads/...'` "
        "and give the chain an integration-base fallback."
    )


@pytest.mark.parametrize("workflow, expression", _declarations())
def test_every_before_is_guarded_by_a_protected_ref(workflow: str, expression: str) -> None:
    """A `before` term is reachable only for a protected-branch push."""
    if "github.event.before" not in expression:
        return

    collapsed = " ".join(expression.split())
    guards = re.findall(r"github\.ref == 'refs/heads/([a-z]+)'", collapsed)
    uses = collapsed.count("github.event.before")
    assert len(guards) >= uses, (
        f"{workflow}: {uses} use(s) of github.event.before but only {len(guards)} "
        f"`github.ref ==` guard(s); every use must name a protected branch"
    )
    unknown = set(guards) - set(PROTECTED_REFS)
    assert not unknown, (
        f"{workflow}: {BASE_REV_KEY} guards an unexpected ref {sorted(unknown)}; "
        f"`before` is the replaced revision only on {list(PROTECTED_REFS)}"
    )
