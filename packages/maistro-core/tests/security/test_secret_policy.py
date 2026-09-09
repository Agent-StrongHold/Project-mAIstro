"""The canonical secret classification policy (#1159).

``maistro.security.secret_policy`` answers the two questions every redaction
consumer asks — is this field NAME credential material, and does this free
text span look like a credential — so approval evidence, the Sentinel PII
filter, and the log redactor cannot drift apart. These tests pin the policy
itself (not just its consumers): the segment classifier's sensitive and
identifier-escape tables, the AWS secret validator's look-alike exclusions,
and the assignment shape's name/value split.
"""

from __future__ import annotations

import pytest

from maistro.security.secret_policy import (
    SECRET_ASSIGNMENT_PATTERN,
    is_secret_key_name,
    iter_secret_assignment_value_spans,
    looks_like_aws_secret_access_key,
)


class TestIsSecretKeyName:
    @pytest.mark.parametrize(
        "name",
        [
            "private_key",
            "ssh_key",
            "signing_key",
            "key",  # bare
            "api_key",
            "apiKey",  # camelCase has no separator to split on
            "access_key",
            "token",
            "auth_token",
            "secret",
            "client_secret",
            "password",
            "passwd",
            "pwd",
            "credential",
            "credentials",
            "authorization",
            "apikey",  # compound, no separator
            "pat",  # GitHub personal access token, bare
            "PAT",  # case-insensitive
            "key2",  # trailing digits name the same family
            "db_password",
            "secret_id",  # strong family beats the id suffix: a live credential
            "password_id",  # same
        ],
    )
    def test_sensitive_names(self, name: str) -> None:
        assert is_secret_key_name(name) is True, name

    @pytest.mark.parametrize(
        "name",
        [
            "aws_access_key_id",  # identifier, not the paired secret
            "key_arn",
            "token_id",
            "key_identifier",
            "access_key_arn",
            "tokenizer",
            "secretary",
            "monkey",
            "author",  # would hit a substring `auth`
            "path",
            "keynote",
            "region",
            "model",
            "",
            "   ",
        ],
    )
    def test_names_that_survive(self, name: str) -> None:
        assert is_secret_key_name(name) is False, repr(name)


class TestLooksLikeAwsSecretAccessKey:
    @staticmethod
    def _canonical() -> str:
        # The classic AWS documentation example, concatenated so no source
        # line carries the whole 40-char run.
        return "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"

    def test_canonical_secret_validates(self) -> None:
        assert looks_like_aws_secret_access_key(self._canonical()) is True

    @pytest.mark.parametrize(
        "candidate",
        [
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # git SHA: single-case hex
            "A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6E7F8A9B0",  # single-case hex, upper
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKE",  # 39 chars
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEYY",  # 41 chars
            "AKIAIOSFODNN7EXAMPLE",  # 20-char access key ID
            "wJ" * 20,  # mixed case, no digit
            "w1" * 20,  # no lower case after strip? has lower... digits+lower only
        ],
    )
    def test_look_alikes_rejected(self, candidate: str) -> None:
        assert looks_like_aws_secret_access_key(candidate) is False, candidate

    def test_digitless_mixed_case_rejected(self) -> None:
        assert looks_like_aws_secret_access_key("wJ" * 20) is False


class TestSecretAssignmentSpans:
    def test_quoted_value_span_excludes_the_quotes(self) -> None:
        text = "my_secret = 'hunter2pass'"
        spans = list(iter_secret_assignment_value_spans(text))
        # The quote characters stay in the output; the value inside them dies.
        assert spans == [(13, 24)]
        assert text[spans[0][0] : spans[0][1]] == "hunter2pass"

    def test_bare_value_span(self) -> None:
        text = "client_key=barevalue9"
        spans = list(iter_secret_assignment_value_spans(text))
        assert spans == [(11, 21)]
        assert text[spans[0][0] : spans[0][1]] == "barevalue9"

    def test_double_quoted_value_span(self) -> None:
        text = 'db_password: "hunter2pass"'
        spans = list(iter_secret_assignment_value_spans(text))
        assert spans == [(14, 25)]
        assert text[spans[0][0] : spans[0][1]] == "hunter2pass"

    @pytest.mark.parametrize(
        "text",
        [
            "tokenizer = cl100k_base-vocab",
            "secretary = JaneDoe99",
            "https://example.com/path",
            "my_secret = short",  # value below the 8-char floor
            "aws_access_key_id=AKIAIOSFODNN7EXAMPLE",  # identifier name survives
        ],
    )
    def test_non_assignments_yield_no_spans(self, text: str) -> None:
        assert list(iter_secret_assignment_value_spans(text)) == [], text

    @pytest.mark.parametrize(
        "text",
        [
            "x: key=value12345",  # outer word is regex-valid but names nothing
            "error: db_password=hunter2pass",  # log-prefix before the assignment
            'config: signing_key = "hunter2pass"',  # spaced inner assignment
        ],
    )
    def test_innermost_assignment_is_the_one_matched(self, text: str) -> None:
        # The bare value must not be able to swallow a following assignment;
        # otherwise the outer (non-credential) name consumes the match and the
        # real value is never reached.
        spans = list(iter_secret_assignment_value_spans(text))
        assert len(spans) == 1, text
        start, end = spans[0]
        assert text[start:end] in ("value12345", "hunter2pass"), text

    def test_pattern_needs_no_boundary_before_name(self) -> None:
        # The compiled pattern anchors the name to the start of its own token;
        # matching `key=value` after a colon still works.
        match = SECRET_ASSIGNMENT_PATTERN.search("x: key=value12345")
        assert match is not None
        assert match.group("name") == "key"
