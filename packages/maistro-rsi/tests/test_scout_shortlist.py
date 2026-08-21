"""Scout shortlist: a ranked list of typed improvement items, parsed leniently."""

from __future__ import annotations

from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.scout import ScoutItem, parse_shortlist, scout_shortlist


def _llm(reply: str):
    def call(messages, **_kw):
        return {"content": reply, "stop_reason": "stop"}

    return call


_JSON = (
    '[{"kind": "bug_fix", "location": "parse()", "instruction": "handle empty input"},'
    ' {"kind": "new_test", "location": "test_parse", "instruction": "cover the empty case"},'
    ' {"kind": "feature", "location": "module", "instruction": "add streaming mode"}]'
)


def test_parses_typed_ranked_items() -> None:
    items = parse_shortlist(_JSON)
    assert [i.kind for i in items] == [
        ImprovementKind.BUG_FIX,
        ImprovementKind.NEW_TEST,
        ImprovementKind.FEATURE,
    ]
    assert items[0] == ScoutItem(ImprovementKind.BUG_FIX, "parse()", "handle empty input")


def test_max_items_caps_the_list() -> None:
    assert len(parse_shortlist(_JSON, max_items=2)) == 2


def test_tolerates_code_fences_and_prose() -> None:
    fenced = "Here is the shortlist:\n```json\n" + _JSON + "\n```\nHope that helps!"
    assert len(parse_shortlist(fenced)) == 3


def test_unknown_kind_falls_back_to_doc_and_blank_instruction_dropped() -> None:
    reply = '[{"kind": "sparkle", "location": "x", "instruction": "do a thing"}, {"kind": "doc"}]'
    items = parse_shortlist(reply)
    assert len(items) == 1  # the item with no instruction is dropped
    assert items[0].kind is ImprovementKind.DOC  # unknown kind → DOC fallback


def test_garbage_yields_empty() -> None:
    assert parse_shortlist("no json here") == []
    assert parse_shortlist("") == []


def test_scout_shortlist_end_to_end() -> None:
    items = scout_shortlist("def f(): pass", "def test_f(): pass", [3, 4], _llm(_JSON))
    assert len(items) == 3
    assert items[2].kind is ImprovementKind.FEATURE


def test_scout_shortlist_swallows_errors() -> None:
    def boom(messages, **_kw):
        raise RuntimeError("gateway down")

    assert scout_shortlist("src", "", "", boom) == []
