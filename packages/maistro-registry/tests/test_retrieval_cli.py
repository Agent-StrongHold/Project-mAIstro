"""CLI surface of the retrieval commands (issue #26).

The `--terms` and `--json` flags exist so the pipeline's audit trail has
a production consumer: `matched_terms` (per result) and `matched_relevant`
(per golden case) are the "why" behind a rank and a miss, and a flag that
nobody drives is indistinguishable from a field nobody reads. These tests
pin both flags against a synthetic corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from maistro_registry import cli
from maistro_registry.cli import build_parser, cmd_eval, cmd_search
from maistro_registry.retrieval import ExpansionError


@pytest.fixture()
def corpus(tmp_path: Path, make_doc: Any) -> Path:
    # Four documents so topic terms stay below the 0.5 df-share ceiling
    # (with two, "queue" sits at 0.5 and is rejected as corpus glue).
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-queue.md",
        "ADR-001",
        "Queue discipline",
        body="Tasks queue for durable work.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-002-vault.md",
        "ADR-002",
        "Vault of secrets",
        body="Vault prose about durable secrets.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-003-render.md",
        "ADR-003",
        "Rendering pipeline",
        body="Pixels are composited per frame.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-004-network.md",
        "ADR-004",
        "Networking substrate",
        body="Peers exchange envelopes.",
    )
    return tmp_path


def _args(argv: list[str]) -> Any:
    return build_parser().parse_args(argv)


def test_search_terms_flag_prints_what_each_result_matched(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(["search", "queue", str(corpus), "--terms"])
    assert cmd_search(args) == 0
    out = capsys.readouterr().out
    # The audit trail is attached to the ranked result it explains.
    assert "matched: queue" in out


def test_search_without_terms_flag_stays_clean(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(["search", "queue", str(corpus)])
    assert cmd_search(args) == 0
    assert "matched:" not in capsys.readouterr().out


def test_eval_json_flag_prints_the_serialized_report(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(["eval", str(corpus), "--json"])
    assert cmd_eval(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) >= {"k", "mean_recall", "mean_mrr", "mean_ndcg", "cases"}
    for case in report["cases"]:
        # The serialized audit trail carries which relevant docs matched.
        assert set(case) >= {"query", "ranked_ids", "relevant_ids", "matched_relevant"}


def test_eval_default_renders_for_humans(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _args(["eval", str(corpus)])
    assert cmd_eval(args) == 0
    out = capsys.readouterr().out
    assert "retrieval quality over" in out
    assert '"mean_mrr"' not in out


def test_index_command_writes_the_index_file(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "idx" / "retrieval-index.json"
    args = _args(["index", str(corpus), "--output", str(out_path)])
    from maistro_registry.cli import cmd_index

    assert cmd_index(args) == 0
    assert out_path.exists()
    assert "indexed 4 documents" in capsys.readouterr().err


def test_index_command_rejects_missing_root_and_empty_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from maistro_registry.cli import cmd_index

    missing = _args(["index", str(tmp_path / "nope")])
    assert cmd_index(missing) == 2
    empty = tmp_path / "hollow"
    empty.mkdir()
    assert cmd_index(_args(["index", str(empty)])) == 2
    err = capsys.readouterr().err
    assert "is not a directory" in err and "no corpus documents" in err


def test_search_uses_a_prebuilt_index_and_custom_ceiling(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    index_path = tmp_path / "retrieval-index.json"
    from maistro_registry.cli import cmd_index

    assert cmd_index(_args(["index", str(corpus), "--output", str(index_path)])) == 0
    capsys.readouterr()
    args = _args(
        ["search", "queue", str(corpus), "--index", str(index_path), "--max-df-share", "0.4"]
    )
    assert cmd_search(args) == 0
    out = capsys.readouterr().out
    assert "ADR-001" in out


def test_search_endpoint_without_model_is_a_clean_error(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(["search", "queue", str(corpus), "--expand-endpoint", "http://llm.test"])
    assert cmd_search(args) == 2
    assert "--expand-model is required" in capsys.readouterr().err


def test_search_reports_an_expansion_skip_and_still_ranks(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A down gateway must degrade visibly: stderr says why, stdout still
    carries the lexical-only ranking."""

    class _DownExpander:
        def expand(self, query: str) -> list[str]:
            raise ExpansionError("expansion request failed: gateway down")

    monkeypatch.setattr(cli, "OpenAICompatExpander", lambda **kwargs: _DownExpander())
    args = _args(
        [
            "search",
            "queue",
            str(corpus),
            "--expand-endpoint",
            "http://llm.test",
            "--expand-model",
            "m",
        ]
    )
    assert cmd_search(args) == 0
    captured = capsys.readouterr()
    assert "expansion skipped:" in captured.err
    assert "ADR-001" in captured.out


def test_search_with_no_hits_says_so(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_search(_args(["search", "zzzzqqqq", str(corpus)])) == 0
    assert "no results" in capsys.readouterr().out


def test_eval_fails_below_the_threshold(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _args(["eval", str(corpus), "--min-mrr", "1.0", "--min-recall", "1.0"])
    assert cmd_eval(args) == 1
    err = capsys.readouterr().err
    assert "FAIL: mean mrr" in err and "FAIL: mean recall@" in err
