"""The Python entry point validates its own model arguments (#309).

The wrapper is one caller. `python -m maistro_rsi run` is another, and it is
the one that holds the roster the wrapper never sees: `_model_arguments`
expands a free-router sentinel against OpenRouter and gets a remote party's
strings back. Validating only at the launcher would leave that expansion — the
single most obviously untrusted value in the path — unchecked.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from maistro_rsi import __main__ as entry
from maistro_rsi.model_identifiers import MAX_ROSTER_SIZE, InvalidModelIdentifier

PAYLOAD = "x'; cat /run/gateway.env #"


def _args(**overrides: str) -> argparse.Namespace:
    defaults = {
        "genome_models": "",
        "emergency_models": "",
        "scout_fallback_models": "",
        "local_fallback_model": "",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestEveryModelArgumentIsValidated:
    @pytest.mark.parametrize(
        "argument",
        ["genome_models", "emergency_models", "scout_fallback_models", "local_fallback_model"],
    )
    def test_a_hostile_value_is_refused(self, argument: str) -> None:
        """All four, not just the one the issue names. Three of them reach the
        same downstream command line, and a check on one door is a check on one
        door."""
        with pytest.raises(InvalidModelIdentifier):
            entry._model_arguments(_args(**{argument: PAYLOAD}))

    def test_real_arguments_survive_unchanged(self) -> None:
        models = entry._model_arguments(
            _args(
                genome_models="code, gemini/gemini-2.5-flash",
                emergency_models="openrouter/x/y:free",
                scout_fallback_models="code",
                local_fallback_model="qwen2.5-coder:7b",
            )
        )

        assert models.genome == ["code", "gemini/gemini-2.5-flash"]
        assert models.emergency == ["openrouter/x/y:free"]
        assert models.scout_fallback == ["code"]
        assert models.local_fallback == "qwen2.5-coder:7b"

    def test_everything_unset_is_the_ordinary_non_evolving_run(self) -> None:
        models = entry._model_arguments(_args())

        assert (models.genome, models.emergency, models.scout_fallback) == ([], [], [])
        assert models.local_fallback == ""


class TestTheSingleValuedFlag:
    def test_a_list_is_refused_rather_than_used_as_one_long_name(self) -> None:
        """`--local-fallback-model a,b` is a mistake with a silent failure mode:
        the value is compared as one identifier downstream and would match no
        model at all, so the fallback would simply never fire."""
        with pytest.raises(InvalidModelIdentifier, match="expected one"):
            entry._model_arguments(_args(local_fallback_model="a,b"))

    def test_one_value_is_accepted(self) -> None:
        assert entry._model_arguments(_args(local_fallback_model=" code ")).local_fallback == "code"


class TestTheExpandedRosterIsRevalidated:
    """The free-router sentinel resolves against OpenRouter. Whatever comes back
    is a remote party's strings and gets the same grammar as everything else.
    """

    @pytest.fixture
    def sentinel(self, monkeypatch: pytest.MonkeyPatch):
        def _expand_returns(value: list[str]) -> None:
            monkeypatch.setattr(entry, "make_free_selector", lambda: object())
            monkeypatch.setattr(entry, "expand_free_router", lambda *_a: value)

        return _expand_returns

    def test_a_hostile_expansion_is_refused(self, sentinel: Any) -> None:
        sentinel([PAYLOAD])

        with pytest.raises(InvalidModelIdentifier):
            entry._model_arguments(_args(genome_models="openrouter/free"))

    def test_an_entry_containing_a_comma_is_refused_not_split(self, sentinel: Any) -> None:
        """Re-joining on commas and re-parsing would turn one bad name into two
        good ones. The roster has to end up holding what the router returned, or
        holding nothing."""
        sentinel(["good/model,other/model"])

        with pytest.raises(InvalidModelIdentifier):
            entry._model_arguments(_args(genome_models="openrouter/free"))

    def test_an_oversized_expansion_is_refused(self, sentinel: Any) -> None:
        sentinel([f"m{i}" for i in range(MAX_ROSTER_SIZE + 1)])

        with pytest.raises(InvalidModelIdentifier, match="free-router returned"):
            entry._model_arguments(_args(genome_models="openrouter/free"))

    def test_a_clean_expansion_replaces_the_sentinel(self, sentinel: Any) -> None:
        sentinel(["openrouter/a/b:free", "openrouter/c/d:free"])

        models = entry._model_arguments(_args(genome_models="openrouter/free"))

        assert models.genome == ["openrouter/a/b:free", "openrouter/c/d:free"]

    def test_an_empty_expansion_leaves_the_sentinel_in_place(self, sentinel: Any) -> None:
        """Pre-existing behaviour — `or genome` — kept deliberately: with no
        OpenRouter key the in-loop mapping downstream is what pins the sentinel,
        and refusing here would break the keyless path this fix has no business
        touching."""
        sentinel([])

        assert entry._model_arguments(_args(genome_models="openrouter/free")).genome == [
            "openrouter/free"
        ]


class TestTheRefusalReachesTheCaller:
    def test_run_exits_non_zero_without_starting_a_loop(
        self, tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The check has to sit before the clone and before the agent runs, or
        it is a diagnostic rather than a gate."""
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        started = []
        monkeypatch.setattr(entry, "LocalRsiLoop", lambda *a, **k: started.append(a))

        code = entry.main(
            [
                "run",
                "--repo",
                str(repo),
                "--test-cmd",
                "true",
                "--genome-models",
                PAYLOAD,
            ]
        )

        assert code == 2
        assert started == []
        assert "refusing model roster" in capsys.readouterr().err
