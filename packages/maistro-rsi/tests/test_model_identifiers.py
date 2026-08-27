"""The grammar refuses everything that would have executed (#309).

`tools/run_rsi_isolated.sh` interpolated `GENOME_MODELS` into a `bash -lc`
payload that had just sourced `/run/gateway.env`. The wrapper no longer
interpolates anything, which is the fix; this is the belt to that pair of
braces, applied on the host before the credentials are mounted.

The cases below are the acceptance criteria's list, one class each: quotes,
command substitution, newlines, option injection, Unicode separators, and
oversized lists.
"""

from __future__ import annotations

import pytest

from maistro_rsi.model_identifiers import (
    MAX_IDENTIFIER_LENGTH,
    MAX_ROSTER_SIZE,
    InvalidModelIdentifier,
    canonical_roster,
    main,
    parse_roster,
    validate_identifier,
)


class TestTheAliasesRealDeploymentsUse:
    """A grammar that refuses the payloads and also refuses the product is not
    a fix, so the shapes that have to keep working come first."""

    @pytest.mark.parametrize(
        "identifier",
        [
            "code",
            "gemini/gemini-2.5-flash",
            "openrouter/meta-llama/llama-3.1-8b-instruct:free",
            "cerebras-qwen-3-235b-a22b-2507",
            "mistral.large",
            "openai/gpt-4o-mini",
            "local_fallback",
            "qwen2.5-coder:7b",
        ],
    )
    def test_it_is_accepted_unchanged(self, identifier: str) -> None:
        assert validate_identifier(identifier) == identifier

    def test_a_roster_round_trips(self) -> None:
        roster = "code,gemini/gemini-2.5-flash,openrouter/x/y:free"

        assert canonical_roster(roster) == roster

    def test_surrounding_ascii_space_is_trimmed(self) -> None:
        """A CSV a human typed has spaces after the commas."""
        assert parse_roster("code, gemini/flash ,\tlocal") == ("code", "gemini/flash", "local")

    def test_an_empty_roster_is_empty_rather_than_an_error(self) -> None:
        """`GENOME_MODELS` unset is the classic non-evolving run, not a fault."""
        assert parse_roster("") == ()
        assert parse_roster("   ") == ()


class TestTheDemonstratedPayload:
    def test_the_quote_that_broke_out_of_the_payload_is_refused(self) -> None:
        """The exact shape from the issue: close the quote, run a command, and
        comment out the rest — in a container that has just sourced the gateway
        credentials."""
        with pytest.raises(InvalidModelIdentifier):
            parse_roster("x'; cat /run/gateway.env #")

    @pytest.mark.parametrize(
        "payload",
        [
            "x$(id)",
            "x`id`",
            "x${OPENROUTER_API_KEY}",
            "x;id",
            "x|id",
            "x&id",
            "x>out",
            "x&&id",
        ],
    )
    def test_every_shell_metacharacter_is_refused(self, payload: str) -> None:
        with pytest.raises(InvalidModelIdentifier):
            parse_roster(payload)

    @pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
    def test_a_newline_is_refused_rather_than_treated_as_a_separator(self, newline: str) -> None:
        """Splitting on it would silently accept the payload as two entries."""
        with pytest.raises(InvalidModelIdentifier):
            parse_roster(f"code{newline}id")

    @pytest.mark.parametrize("option", ["--free-count", "-r", "--roster=evil"])
    def test_an_identifier_that_would_be_read_as_an_option_is_refused(self, option: str) -> None:
        """Well-formed by every character rule and still not a model: the
        receiving CLI would take it as a flag."""
        with pytest.raises(InvalidModelIdentifier, match="option"):
            parse_roster(option)

    @pytest.mark.parametrize(
        ("name", "separator"),
        [
            ("LINE SEPARATOR", "\u2028"),
            ("PARAGRAPH SEPARATOR", "\u2029"),
            ("NO-BREAK SPACE", "\u00a0"),
            ("OGHAM SPACE MARK", "\u1680"),
            ("EN QUAD", "\u2000"),
            ("MEDIUM MATHEMATICAL SPACE", "\u205f"),
            ("IDEOGRAPHIC SPACE", "\u3000"),
            ("NEXT LINE", "\u0085"),
        ],
    )
    def test_a_unicode_separator_is_refused(self, name: str, separator: str) -> None:
        """Not enumerated in the code — the ASCII allow-list refuses the whole
        family — but enumerated here, because "the allow-list covers it" is a
        claim and these are the characters that test it.

        Written as escapes rather than as themselves: several of these are
        invisible, and a test whose input cannot be seen in the diff is a test
        nobody can review.
        """
        with pytest.raises(InvalidModelIdentifier) as caught:
            parse_roster(f"code{separator}id")

        assert f"U+{ord(separator):04X}" in str(caught.value), name

    def test_a_unicode_separator_is_not_quietly_trimmed_at_an_edge(self) -> None:
        """`str.strip()` removes U+00A0. Trimming only ASCII means a value
        engineered to carry one is reported rather than repaired."""
        with pytest.raises(InvalidModelIdentifier, match="U\\+00A0"):
            parse_roster("\u00a0code")


class TestTheLimits:
    def test_an_identifier_at_the_limit_is_accepted(self) -> None:
        assert validate_identifier("m" * MAX_IDENTIFIER_LENGTH)

    def test_one_character_over_is_refused(self) -> None:
        with pytest.raises(InvalidModelIdentifier, match=str(MAX_IDENTIFIER_LENGTH)):
            validate_identifier("m" * (MAX_IDENTIFIER_LENGTH + 1))

    def test_a_roster_at_the_limit_is_accepted(self) -> None:
        assert (
            len(parse_roster(",".join(f"m{i}" for i in range(MAX_ROSTER_SIZE)))) == MAX_ROSTER_SIZE
        )

    def test_one_entry_over_is_refused(self) -> None:
        with pytest.raises(InvalidModelIdentifier, match=str(MAX_ROSTER_SIZE)):
            parse_roster(",".join(f"m{i}" for i in range(MAX_ROSTER_SIZE + 1)))

    def test_the_cardinality_check_runs_before_the_per_entry_check(self) -> None:
        """An oversized list of *invalid* entries should report the size, not
        walk 10,000 of them producing the first character complaint."""
        with pytest.raises(InvalidModelIdentifier, match="entries"):
            parse_roster(",".join("x'" for _ in range(MAX_ROSTER_SIZE + 1)))

    def test_an_empty_entry_inside_a_roster_is_refused(self) -> None:
        """`a,,b` is a typo, and silently dropping it would hand the run a
        roster the operator did not write."""
        with pytest.raises(InvalidModelIdentifier, match="empty"):
            parse_roster("code,,gemini/flash")


class TestTheShellFacingCommand:
    def test_a_valid_roster_prints_its_canonical_form_and_succeeds(self, capsys) -> None:
        assert main(["--roster", "code, gemini/flash"]) == 0
        assert capsys.readouterr().out.strip() == "code,gemini/flash"

    def test_a_refused_roster_exits_non_zero_and_says_why_on_stderr(self, capsys) -> None:
        """The wrapper puts stderr in its own error message, so a refusal has
        to explain itself there rather than on stdout — which the wrapper
        captures as the value."""
        assert main(["--roster", "x'; id"]) == 1

        captured = capsys.readouterr()
        assert captured.out.strip() == ""
        assert "refusing model roster" in captured.err

    def test_the_canonical_form_is_what_gets_emitted_not_the_input(self, capsys) -> None:
        """The wrapper uses this output as the roster from here on, so emitting
        the validated reconstruction rather than the original is what stops a
        stray space travelling onwards."""
        main(["--roster", " code , gemini/flash "])

        assert capsys.readouterr().out.strip() == "code,gemini/flash"
