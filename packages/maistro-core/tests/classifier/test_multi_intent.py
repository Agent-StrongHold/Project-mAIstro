"""Coverage for maistro.classifier.multi_intent (was 19%)."""

from __future__ import annotations

from maistro.classifier.multi_intent import (
    _match_config_keyword,
    _match_strong_indicator,
    _split_into_parts,
    detect_multi_intent,
)
from maistro.types.config import TaskTypeConfig

# ─── _split_into_parts ────────────────────────────────────────────────────────


def test_split_on_and_then():
    parts = _split_into_parts("write a function and then deploy it to prod")
    assert parts == ["write a function", "deploy it to prod"]


def test_split_on_plain_and():
    parts = _split_into_parts("buy milk and walk the dog")
    assert parts == ["buy milk", "walk the dog"]


def test_split_drops_fragments_of_5_chars_or_fewer():
    parts = _split_into_parts("fix it and go")
    # "go" (2 chars) is dropped, "fix it" (6 chars) kept.
    assert parts == ["fix it"]


def test_no_splitter_present_returns_single_part():
    parts = _split_into_parts("just one simple request here")
    assert parts == ["just one simple request here"]


def test_multiple_splitters_in_one_string_all_applied():
    parts = _split_into_parts("write code and also debug this and deploy")
    assert parts == ["write code", "debug this", "deploy"]


# ─── _match_strong_indicator ──────────────────────────────────────────────────


def test_match_strong_indicator_finds_known_phrase():
    assert _match_strong_indicator("please write a function for me") == "code"


def test_match_strong_indicator_returns_none_when_no_phrase_matches():
    assert _match_strong_indicator("good morning everyone") is None


def test_match_strong_indicator_requires_word_boundaries():
    # "debug this" is a strong indicator; a substring without padding shouldn't match
    # via a different unrelated phrase ("fix the bug" requires the exact phrase).
    assert _match_strong_indicator("debug this issue please") == "code"


# ─── _match_config_keyword ─────────────────────────────────────────────────────


def _task_types():
    return {
        "automation": TaskTypeConfig(keywords=["turn on", "lights"]),
        "trading": TaskTypeConfig(keywords=["buy stock", "sell shares"]),
    }


def test_match_config_keyword_finds_first_matching_task():
    result = _match_config_keyword("please turn on the lights", _task_types(), [])
    assert result == "automation"


def test_match_config_keyword_skips_already_seen_types():
    result = _match_config_keyword("turn on the lights", _task_types(), ["automation"])
    assert result is None


def test_match_config_keyword_returns_none_when_nothing_matches():
    result = _match_config_keyword("tell me a joke", _task_types(), [])
    assert result is None


# ─── detect_multi_intent (integration) ────────────────────────────────────────


def test_single_part_message_is_never_compound():
    result = detect_multi_intent("just write a function for me please", {})
    assert result == []


def test_same_intent_repeated_via_strong_indicators_is_not_compound():
    # Both parts hit "code" via strong indicators -> only one distinct type ->
    # not compound (requires >= 2 DISTINCT types).
    result = detect_multi_intent("write a function and then debug this issue", {})
    assert result == []


def test_two_genuinely_distinct_intents_detected_via_config_keywords():
    task_types = {
        "automation": TaskTypeConfig(keywords=["turn on the lights"]),
        "trading": TaskTypeConfig(keywords=["buy some stock"]),
    }
    result = detect_multi_intent("turn on the lights and also buy some stock", task_types)
    assert result == ["automation", "trading"]


def test_strong_indicator_and_config_keyword_combine_to_two_distinct_types():
    task_types = {"automation": TaskTypeConfig(keywords=["turn on the lights"])}
    result = detect_multi_intent("write a function and then turn on the lights", task_types)
    assert result == ["code", "automation"]


def test_three_parts_two_distinct_types_still_compound():
    task_types = {"automation": TaskTypeConfig(keywords=["turn on the lights"])}
    result = detect_multi_intent(
        "write a function and then turn on the lights and also debug this", task_types
    )
    assert result == ["code", "automation"]


def test_no_keyword_matches_anywhere_returns_empty():
    result = detect_multi_intent("good morning and also good evening to you", {})
    assert result == []


def test_duplicate_type_across_parts_does_not_inflate_distinct_count():
    task_types = {"automation": TaskTypeConfig(keywords=["turn on the lights"])}
    result = detect_multi_intent("turn on the lights and also turn on the lights again", task_types)
    # Same type detected twice -> only 1 distinct type -> not compound.
    assert result == []
