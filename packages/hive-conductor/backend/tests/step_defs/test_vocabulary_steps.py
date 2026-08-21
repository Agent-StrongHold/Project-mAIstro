"""pytest-bdd step definitions for features/vocabulary.feature."""

from __future__ import annotations

import sys
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

FEATURES = Path(__file__).resolve().parents[3] / "features"
TEMPLATES = Path(__file__).resolve().parents[3] / "eval" / "departments" / "yaml"
scenarios(str(FEATURES / "vocabulary.feature"))


# ---------------------------------------------------------------------------
# Given — check ops
# ---------------------------------------------------------------------------


@given(
    parsers.parse('a check op "keywords_any" with words {words_repr}'), target_fixture="check_spec"
)
def keywords_any_op(words_repr: str) -> dict:
    import ast

    return {"op": "keywords_any", "words": ast.literal_eval(words_repr)}


@given('a check op "keywords_any" with an empty word list', target_fixture="check_spec")
def keywords_any_empty() -> dict:
    return {"op": "keywords_any", "words": []}


@given(
    parsers.parse('a check op "keywords_none" with words {words_repr}'), target_fixture="check_spec"
)
def keywords_none_op(words_repr: str) -> dict:
    import ast

    return {"op": "keywords_none", "words": ast.literal_eval(words_repr)}


@given(parsers.parse('a check op "word_count" with max {n:d}'), target_fixture="check_spec")
def word_count_max_op(n: int) -> dict:
    return {"op": "word_count", "max": n}


@given(parsers.parse('a check op "word_count" with min {n:d}'), target_fixture="check_spec")
def word_count_min_op(n: int) -> dict:
    return {"op": "word_count", "min": n}


@given(parsers.parse('a check op "regex" with pattern "{pattern}"'), target_fixture="check_spec")
def regex_op(pattern: str) -> dict:
    return {"op": "regex", "pattern": pattern}


@given(
    parsers.parse('a check op "regex_absent" with pattern "{pattern}" and flags "{flags}"'),
    target_fixture="check_spec",
)
def regex_absent_op(pattern: str, flags: str) -> dict:
    return {"op": "regex_absent", "pattern": pattern, "flags": flags}


@given(
    'a check op "any" combining keywords_any["calm"] and keywords_any["local pickup"]',
    target_fixture="check_spec",
)
def any_op() -> dict:
    return {
        "op": "any",
        "of": [
            {"op": "keywords_any", "words": ["calm"]},
            {"op": "keywords_any", "words": ["local pickup"]},
        ],
    }


@given(
    'a check op "all" combining keywords_any["calm"] and keywords_any["local pickup"]',
    target_fixture="check_spec",
)
def all_op() -> dict:
    return {
        "op": "all",
        "of": [
            {"op": "keywords_any", "words": ["calm"]},
            {"op": "keywords_any", "words": ["local pickup"]},
        ],
    }


@given(
    parsers.parse('a new YAML template "{path}" with kind "{kind}" and name "{name}"'),
    target_fixture="tmp_template_path",
)
def new_yaml_template(tmp_path, path: str, kind: str, name: str) -> Path:
    import yaml

    dest = TEMPLATES / Path(path).name
    dest.write_text(
        yaml.dump(
            {
                "department": name,
                "evals": [
                    {
                        "name": "test_eval",
                        "criteria": [
                            {
                                "name": "has_test_word",
                                "weight": 100,
                                "check": {"op": "keywords_any", "words": ["test"]},
                            }
                        ],
                    }
                ],
            }
        )
    )
    return dest


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('I evaluate "{text}"'), target_fixture="eval_result")
def evaluate_text(check_spec: dict, text: str) -> bool:
    from eval.vocabulary import evaluate

    return evaluate(check_spec, text, {})


@when("I call all_departments()", target_fixture="all_depts")
def call_all_departments() -> dict:
    # reload to pick up newly written template
    import importlib

    import eval.loader as loader_mod

    importlib.reload(loader_mod)
    return loader_mod.all_departments()


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("the result is {expected}"))
def check_result(eval_result: bool, expected: str) -> None:
    assert eval_result is (expected.strip() == "True")


@then(parsers.parse('"{name}" appears in the department registry'))
def dept_in_registry(all_depts: dict, name: str) -> None:
    assert name in all_depts, f"{name!r} not found in {list(all_depts)}"


@then("I remove the temporary template")
def remove_temp_template(tmp_template_path: Path) -> None:
    if tmp_template_path.exists():
        tmp_template_path.unlink()
