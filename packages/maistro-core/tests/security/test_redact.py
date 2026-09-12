"""Tests for secret redaction in logs, prompts, and error messages."""

from __future__ import annotations

import string
import time

import pytest

from maistro.security.redact import (
    _ENTROPY_BITS_PER_CHAR_THRESHOLD,
    _MIN_SECRET_LENGTH,
    _looks_like_secret,
    _shannon_entropy,
    redact,
)


def _jwt(header: str, payload: str, signature: str) -> str:
    """Assemble a JWT-shaped fixture from its three segments.

    These are synthetic test vectors, not credentials, but a contiguous
    ``header.payload.signature`` literal trips secret scanners on every fresh
    clone -- and a repo with no history has no scanned range to fall back on.
    Joining the segments here keeps the fixtures readable while leaving no
    single source line that looks like a token.
    """
    return f"{header}.{payload}.{signature}"


class TestRedactNoneAndEmpty:
    @pytest.mark.ac("ADR-064/AC-41")
    def test_none_returns_empty_string(self):
        """None is outside the declared domain (`text: str`); redaction fails closed."""
        assert redact(None) == ""  # type: ignore[arg-type]  deliberate: pins the fail-closed contract

    @pytest.mark.ac("ADR-064/AC-40")
    def test_empty_string_returns_empty(self):
        assert redact("") == ""

    def test_whitespace_only_unchanged(self):
        assert redact("   \n\t  ") == "   \n\t  "


class TestRedactAPIKeys:
    @pytest.mark.ac("ADR-064/AC-1")
    def test_sk_prefix(self):
        key = "sk-" + "TESTFAKEVALUE12345"
        result = redact(f"use key {key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    @pytest.mark.ac("ADR-064/AC-6")
    def test_sk_ant_prefix(self):
        key = "sk-" + "ant-TESTFAKEVALUE12345"
        result = redact(f"key is {key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    @pytest.mark.ac("ADR-064/AC-7")
    def test_sk_live_prefix(self):
        key = "sk_" + "live_TESTFAKEVALUE12345"
        result = redact(f"key={key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    def test_sk_test_prefix(self):
        key = "sk_" + "test_TESTFAKEVALUE12345"
        result = redact(f"key={key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    @pytest.mark.ac("ADR-064/AC-2")
    def test_ghp_prefix(self):
        key = "ghp_TESTFAKEVALUE12345"
        result = redact(f"key is {key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    @pytest.mark.ac("ADR-064/AC-3")
    def test_aiza_prefix(self):
        key = "AIzaTESTFAKEVALUE1234567890"
        result = redact(f"google key {key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    @pytest.mark.ac("ADR-064/AC-4")
    def test_xoxb_prefix(self):
        key = "xoxb-TESTFAKEVALUE12345"
        result = redact(f"slack bot {key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result

    @pytest.mark.ac("ADR-064/AC-5")
    def test_pplx_prefix(self):
        key = "pplx-TESTFAKEVALUE12345"
        result = redact(f"perplexity {key}")
        assert "[REDACTED_API_KEY]" in result
        assert "TESTFAKEVALUE" not in result


class TestRedactAWSKeys:
    @pytest.mark.ac("ADR-064/AC-8")
    def test_aws_key(self):
        prefix = "AKIA"
        key = prefix + "FAKE1234567890AB"
        result = redact(f"aws_access_key_id={key}")
        assert "[REDACTED_AWS_KEY]" in result
        assert "FAKE1234567890AB" not in result

    @pytest.mark.ac("ADR-064/AC-8")
    def test_aws_key_in_context(self):
        prefix = "AKIA"
        key = prefix + "FAKE1234567890AB"
        result = redact(f"credentials: access_key={key} region=us-east-1")
        assert "[REDACTED_AWS_KEY]" in result
        assert "us-east-1" in result


class TestRedactSlackTokenFamily:
    """#1159 — the whole xox* family, one shared shape.

    Only xoxb/xoxp were covered before; xoxa (app), xoxr (refresh) and xoxs
    (session) went through verbatim. The compiled shape now lives in
    `secret_policy.SLACK_TOKEN_PATTERN` so the log path and the Sentinel PII
    filter cannot drift. Literals are concatenated like the rest of this file:
    a contiguous token-shaped string is a real gitleaks hit even when invented.
    """

    @pytest.mark.parametrize("prefix", ["xoxa", "xoxb", "xoxp", "xoxr", "xoxs"])
    def test_slack_prefix(self, prefix):
        token = prefix + "-FAKEVALUE123456"
        result = redact(f"slack {token} end")
        assert "[REDACTED_API_KEY]" in result, prefix
        assert "FAKEVALUE" not in result, prefix

    def test_longer_word_containing_xox_is_not_a_token(self):
        # The left boundary keeps a word that merely contains `xox` from
        # matching — only a token at the start of its own token dies.
        text = "woxoxb-FAKEVALUE123456 xoxbox-FAKEVALUE123456"
        assert redact(text) == text

    def test_short_tail_is_not_a_token(self):
        text = "xoxb-123"
        assert redact(text) == text

    def test_slack_token_inside_json_value_gets_json_label(self):
        # Precedence, not survival: the JSON-field span contains the token, so
        # the JSON label wins the merge and the token is gone either way.
        token = "xoxb-" + "FAKEVALUE123456"
        result = redact('{"slack_token": "' + token + '"}')
        assert "[REDACTED_JSON_SECRET]" in result
        assert "FAKEVALUE" not in result


class TestRedactAWSSecretAccessKey:
    """#1159 — the 40-character secret paired with an AKIA access key ID.

    The shape is validated, not merely matched: a raw 40-char charset run
    would swallow the dominant look-alikes (git SHAs) and still miss nothing
    that matters. The AKIA ID itself stays on the identifier-redaction path
    ([REDACTED_AWS_KEY]) — it is an identifier, not a reusable credential.
    """

    @staticmethod
    def _canonical_secret() -> str:
        # The classic AWS documentation example, concatenated so no source
        # line carries the whole 40-char run.
        return "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"

    @staticmethod
    def _hex_run(length: int, case: str) -> str:
        digits = "0123456789abcdef" if case == "lower" else "0123456789ABCDEF"
        return (digits * ((length // 16) + 1))[:length]

    def test_canonical_secret_redacted_with_its_own_label(self):
        secret = self._canonical_secret()
        assert len(secret) == 40
        result = redact(f"aws secret {secret} end")
        assert "[REDACTED_AWS_SECRET_KEY]" in result
        assert secret not in result

    def test_secret_redacted_alongside_its_akia_id(self):
        secret = self._canonical_secret()
        result = redact(f"id AKIAFAKE1234567890AB and secret {secret}")
        assert "[REDACTED_AWS_KEY]" in result
        assert "[REDACTED_AWS_SECRET_KEY]" in result
        assert secret not in result

    def test_value_adjacent_to_equals_gets_assignment_label(self):
        # The AWS shape requires a maximal charset run, and `=` is part of the
        # AWS charset — so the `name=<secret>` form is claimed by the generic
        # assignment instead. The label differs; the secret does not survive.
        secret = self._canonical_secret()
        result = redact(f"secret_access_key={secret} end")
        assert "[REDACTED_SECRET_ASSIGNMENT]" in result
        assert "[REDACTED_AWS_SECRET_KEY]" not in result
        assert secret not in result
        assert "secret_access_key" in result

    def test_lowercase_hex_sha_is_not_an_aws_secret(self):
        # A 40-char single-case hex run is a git commit SHA, not base64-ish
        # key material — the validator's mixed-case requirement exists for it.
        sha = self._hex_run(40, "lower")
        assert redact(f"commit {sha} ok") == f"commit {sha} ok"

    def test_uppercase_hex_run_is_not_an_aws_secret(self):
        run = self._hex_run(40, "upper")
        assert redact(f"ref {run} ok") == f"ref {run} ok"

    @pytest.mark.parametrize("length", [39, 41])
    def test_length_is_exactly_40(self, length):
        run = self._hex_run(length, "lower")
        assert redact(f"run {run} end") == f"run {run} end"

    def test_akia_id_is_not_labeled_aws_secret(self):
        # 20 characters can never be the 40-char secret; the ID keeps its
        # identifier redaction instead.
        result = redact("id AKIAIOSFODNN7EXAMPLE end")
        assert "[REDACTED_AWS_KEY]" in result
        assert "[REDACTED_AWS_SECRET_KEY]" not in result

    def test_no_digits_means_not_an_aws_secret(self):
        run = "wJ" * 20  # 40 chars, mixed case, no digit
        assert redact(f"run {run} end") == f"run {run} end"


class TestRedactSecretAssignments:
    """#1159 — generic secret assignments: `name = value` in every quoting,
    spacing, and case variant. Only the *value* span is redacted; the field
    name stays readable so the audit trail keeps the fact and type of the
    action without the credential. A more specific detector that fired inside
    the value keeps its label (the assignment span is skipped on overlap).
    """

    @pytest.mark.parametrize(
        ("assignment", "name"),
        [
            ("my_secret = 'hunter2pass'", "my_secret"),
            ("my_secret='hunter2pass'", "my_secret"),
            ('db_password: "hunter2pass"', "db_password"),
            ('db_password:"hunter2pass"', "db_password"),
            ("client_key=barevalue9", "client_key"),
            ("apiKey = value1234567", "apiKey"),
            ('token="abcdef12345"', "token"),
            ("DB_PASSWORD: hunter2pass2", "DB_PASSWORD"),
            ("MySecret = hunter2pass1", "MySecret"),
        ],
        ids=[
            "sq-spaced",
            "sq-tight",
            "dq-colon",
            "dq-tight",
            "bare",
            "camel",
            "dq-token",
            "upper-colon",
            "camel-no-separator",
        ],
    )
    def test_value_redacted_name_preserved(self, assignment, name):
        result = redact(f"config {assignment} end")
        assert "[REDACTED_SECRET_ASSIGNMENT]" in result, assignment
        assert "hunter2pass" not in result and "barevalue" not in result, assignment
        assert name in result, assignment

    def test_prefixed_name_still_classified(self):
        # The bare value must not swallow a following assignment: an outer
        # regex-valid name (`credentials: `) cannot consume the inner name as
        # its value and leave the real credential behind.
        result = redact('credentials: signing_key = "hunter2pass" end')
        assert "[REDACTED_SECRET_ASSIGNMENT]" in result
        assert "hunter2pass" not in result
        assert "signing_key" in result

    def test_base64_padded_bare_value_fully_redacted(self):
        result = redact("client_key=c2VjcmV0dmFsdWU=")
        assert "[REDACTED_SECRET_ASSIGNMENT]" in result
        assert "c2VjcmV0dmFsdWU" not in result

    @pytest.mark.parametrize(
        "text",
        [
            "tokenizer = cl100k_base-vocab",
            "secretary = JaneDoe99",
            "monkey = bongo1234",
            "author = aside99",
        ],
        ids=["tokenizer", "secretary", "monkey", "author"],
    )
    def test_ordinary_words_are_not_assignment_names(self, text):
        assert redact(text) == text

    @pytest.mark.parametrize(
        "text",
        [
            "https://example.com/path?q=1",
            "see https://example.com/docs for details",
        ],
        ids=["url-with-query", "url-in-prose"],
    )
    def test_urls_are_not_assignments(self, text):
        result = redact(text)
        assert "[REDACTED_SECRET_ASSIGNMENT]" not in result

    def test_url_credentials_keep_url_label(self):
        result = redact("https://fakeuser:fakepass@example.com/path")
        assert "[REDACTED_URL_CREDENTIALS]" in result
        assert "[REDACTED_SECRET_ASSIGNMENT]" not in result

    def test_short_values_are_left_alone(self):
        text = "my_secret = abc"
        assert redact(text) == text

    def test_specific_label_inside_value_wins(self):
        # The value span a more specific detector already claimed (AKIA)
        # keeps its label; what stays visible around it is filler.
        result = redact("my_secret = 'AKIAIOSFODNN7EXAMPLE and more'")
        assert "[REDACTED_AWS_KEY]" in result
        assert "[REDACTED_SECRET_ASSIGNMENT]" not in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "my_secret" in result

    def test_chained_access_key_keeps_aws_label(self):
        # `credentials: access_key=<AKIA>` — the assignment whose value the
        # AKIA pattern claims is skipped wholesale, so the ID keeps the
        # ADR-064/AC-8 label and the inner field name stays readable.
        result = redact("credentials: access_key=AKIAFAKE1234567890AB region=us-east-1")
        assert "[REDACTED_AWS_KEY]" in result
        assert "[REDACTED_SECRET_ASSIGNMENT]" not in result
        assert "AKIAFAKE1234567890AB" not in result
        assert "us-east-1" in result
        assert "access_key=" in result

    def test_high_entropy_value_still_redacted(self):
        value = "Ab3xK9mP2qR7sT5uV1wX4yZ6aB8cD0eF"  # 32 chars, mixed
        result = redact("client_key=" + value)
        assert value not in result
        assert "[REDACTED_" in result

    def test_assignment_redacted_even_with_an_unrelated_later_span(self):
        """#1159 repair regression: the assignment-skip test used a broken
        interval predicate, so any other redactable span AFTER the value (a
        Slack token, a JWT) suppressed the assignment redaction and the raw
        credential survived the line."""
        slack = "xoxb-123456789012-abcdefabcdef"
        result = redact(f"my_secret = 'hunter2pass' token {slack} end")
        assert "hunter2pass" not in result
        assert "[REDACTED_SECRET_ASSIGNMENT]" in result
        assert slack not in result
        # Same leak, bare-value form, span BEFORE and AFTER the assignment.
        result = redact(f"tok {slack} then client_key=barevalue9 end")
        assert "barevalue" not in result

    def test_redaction_is_idempotent_across_passes(self):
        """Multi-boundary pipelines redact at more than one seam, so a second
        pass must be a fixed point — not relabel earlier placeholders."""
        aws = "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
        text = f"config my_secret = 'hunter2pass' key={aws} tok xoxb-123456789012-abcdefabcdef"
        once = redact(text)
        assert redact(once) == once
        # And the first pass actually removed everything (the idempotence
        # regression used to hold only because pass one had already leaked).
        assert "hunter2pass" not in once and aws not in once

    def test_second_pass_keeps_the_specific_label(self):
        """The reserved [REDACTED... label namespace is never re-claimed as an
        assignment value, so labels are stable across passes — including the
        assignment's own label and the AWS one (whose relabeling was the
        visible symptom of the non-idempotence regression)."""
        for labeled in (
            "key=[REDACTED_AWS_SECRET_KEY]",
            "my_secret = '[REDACTED_SECRET_ASSIGNMENT]'",
            'db_password: "[REDACTED_JSON_SECRET]"',
        ):
            assert redact(labeled) == labeled, labeled
        # End to end: an AWS value the AWS detector can claim (space-separated)
        # keeps its specific label on the first pass and everything holds on
        # the second. (`key=<40-char run>` deliberately lands on the
        # assignment label — see test_value_adjacent_to_equals_gets_assignment_label.)
        aws = "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
        once = redact(f"leaked secret {aws} in args")
        assert "[REDACTED_AWS_SECRET_KEY]" in once
        assert redact(once) == once


class TestRedactJSONBareKeyName:
    """#1159 — bare `key` joined the JSON field-name alternation.

    The term stays segment-anchored: it must be the whole name or sit at a
    `_`/`-`/`.` boundary, so `keynote` and `monkey` cannot match.
    """

    def test_bare_key_field_redacted(self):
        result = redact('{"key": "opensesame1"}')
        assert "[REDACTED_JSON_SECRET]" in result
        assert "opensesame1" not in result

    @pytest.mark.parametrize(
        "field",
        ["ssh_key", "signing_key", "access-key", "key_id", "my.key"],
        ids=["ssh", "signing", "dashed", "suffixed", "dotted"],
    )
    def test_key_segment_fields_redacted(self, field):
        result = redact('{"' + field + '": "hunter2pass"}')
        assert "[REDACTED_JSON_SECRET]" in result, field
        assert "hunter2pass" not in result, field

    def test_keynote_is_not_a_key_field(self):
        text = '{"keynote": "intro1"}'
        assert redact(text) == text


class TestRedactENV:
    @pytest.mark.ac("ADR-064/AC-9")
    def test_secret_key(self):
        result = redact("SECRET_KEY=FAKE_VALUE_123")
        assert "[REDACTED_ENV]" in result
        assert "FAKE_VALUE" not in result

    @pytest.mark.ac("ADR-064/AC-10")
    def test_api_key(self):
        result = redact("API_KEY=FAKE_API_VALUE")
        assert "[REDACTED_ENV]" in result
        assert "FAKE_API_VALUE" not in result

    def test_password(self):
        result = redact("PASSWORD=FAKE_PASS_123")
        assert "[REDACTED_ENV]" in result
        assert "FAKE_PASS" not in result

    @pytest.mark.ac("ADR-064/AC-9")
    def test_case_insensitive(self):
        result = redact("secret_key=FAKE_VALUE")
        assert "[REDACTED_ENV]" in result
        assert "FAKE_VALUE" not in result

    def test_mixed_case_password(self):
        result = redact("Password=FAKE_VALUE")
        assert "[REDACTED_ENV]" in result
        assert "FAKE_VALUE" not in result

    def test_spaces_around_equals(self):
        result = redact("SECRET_KEY = FAKE_VALUE_123")
        assert "[REDACTED_ENV]" in result
        assert "FAKE_VALUE" not in result

    @pytest.mark.ac("ADR-064/AC-11")
    @pytest.mark.ac("ADR-064/AC-29")
    def test_multiline_env(self):
        text = "DEBUG=true\nSECRET_KEY=FAKE_VALUE\nPORT=3000"
        result = redact(text)
        assert "[REDACTED_ENV]" in result
        assert "DEBUG=true" in result
        assert "PORT=3000" in result
        assert "FAKE_VALUE" not in result


class TestRedactAuthHeaders:
    @pytest.mark.ac("ADR-064/AC-15")
    def test_bearer(self):
        result = redact("Authorization: Bearer FAKE_TOKEN_12345")
        assert "[REDACTED_AUTH_HEADER]" in result
        assert "FAKE_TOKEN" not in result

    @pytest.mark.ac("ADR-064/AC-16")
    def test_basic(self):
        result = redact("Authorization: Basic FAKECREDS123")
        assert "[REDACTED_AUTH_HEADER]" in result
        assert "FAKECREDS" not in result

    def test_token(self):
        result = redact("Authorization: Token FAKE_TOKEN_12345")
        assert "[REDACTED_AUTH_HEADER]" in result
        assert "FAKE_TOKEN" not in result

    def test_case_insensitive_bearer(self):
        result = redact("auth: bearer FAKE_TOKEN_12345")
        assert "[REDACTED_AUTH_HEADER]" in result


class TestRedactPrivateKeys:
    @pytest.mark.ac("ADR-064/AC-17")
    def test_rsa_private_key(self):
        key_block = (
            "-----BEGIN RSA PRIVATE" + " KEY-----\n"
            "FAKEKEYDATA1234567890==\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = redact(key_block)
        assert "[REDACTED_PRIVATE_KEY]" in result
        assert "FAKEKEYDATA" not in result

    def test_ec_private_key(self):
        key_block = (
            "-----BEGIN EC PRIVATE" + " KEY-----\nFAKEECKEYDATA==\n-----END EC PRIVATE KEY-----"
        )
        result = redact(key_block)
        assert "[REDACTED_PRIVATE_KEY]" in result
        assert "FAKEECKEYDATA" not in result

    def test_generic_private_key(self):
        key_block = "-----BEGIN PRIVATE" + " KEY-----\nFAKEGENERICKEY==\n-----END PRIVATE KEY-----"
        result = redact(key_block)
        assert "[REDACTED_PRIVATE_KEY]" in result
        assert "FAKEGENERICKEY" not in result

    @pytest.mark.ac("ADR-064/AC-18")
    def test_openssh_private_key(self):
        # No dedicated pattern needed: `OPENSSH ` fits the existing
        # `[A-Z ]{0,32}` label prefix and the body is base64-and-whitespace.
        # Concatenated so no source line carries a full BEGIN marker — a
        # contiguous key block is a real gitleaks hit even when invented.
        key_block = (
            "-----BEGIN OPENSSH "
            + "PRIVATE KEY-----\nbase64data\n"
            + "-----END OPENSSH "
            + "PRIVATE KEY-----"
        )
        result = redact(key_block)
        assert "[REDACTED_PRIVATE_KEY]" in result
        assert "base64data" not in result

    @pytest.mark.ac("ADR-064/AC-30")
    def test_private_key_in_context(self):
        key_block = (
            "config:\n"
            "  key: |\n"
            "    -----BEGIN RSA PRIVATE" + " KEY-----\n"
            "    FAKEKEYDATA==\n"
            "    -----END RSA PRIVATE KEY-----\n"
            "  host: example.com"
        )
        result = redact(key_block)
        assert "[REDACTED_PRIVATE_KEY]" in result
        assert "example.com" in result


class TestRedactDBConnections:
    @pytest.mark.ac("ADR-064/AC-19")
    def test_postgres(self):
        result = redact("postgres://fakeuser:fakepass@fakedb.example.com:5432/mydb")
        assert "[REDACTED_DB_CONNECTION]" in result
        assert "fakepass" not in result

    @pytest.mark.ac("ADR-064/AC-20")
    def test_mysql(self):
        result = redact("mysql://fakeuser:fakepass@fakedb.example.com:3306/mydb")
        assert "[REDACTED_DB_CONNECTION]" in result
        assert "fakepass" not in result

    @pytest.mark.ac("ADR-064/AC-21")
    def test_mongodb(self):
        result = redact("mongodb://fakeuser:fakepass@fakedb.example.com:27017/mydb")
        assert "[REDACTED_DB_CONNECTION]" in result
        assert "fakepass" not in result


class TestRedactJWTs:
    @pytest.mark.ac("ADR-064/AC-22")
    def test_jwt_long_enough(self):
        # Real JWT shape: 3 base64url segments separated by dots
        token = _jwt(
            "eyJhbGciOiJIUzI1NiJ9",
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        )
        result = redact(f"token={token}")
        assert "[REDACTED_JWT]" in result
        assert token not in result

    def test_jwt_too_short(self):
        # Single segment without dots — not a JWT
        token = "eyJ" + "A" * 46
        result = redact(f"token={token}")
        assert "[REDACTED_JWT]" not in result

    def test_jwt_in_auth_header(self):
        token = _jwt(
            "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9",
            "eyJzdWIiOiJ1c2VyMTIzIn0",
            "signatureAAAAAAAAAAAAAAAAAAAAAAAAA",
        )
        result = redact(f"Authorization: Bearer {token}")
        assert token not in result

    @pytest.mark.ac("ADR-064/AC-22")
    def test_jwt_with_dashes_and_underscores(self):
        token = _jwt("eyJhbGciOiJIUzI1NiJ9", "eyJuYW1lIjoiSm9obiJ9", "A_a-1B_b-2C_c-3D_d-4E_e-5F")
        result = redact(f"jwt: {token}")
        assert token not in result


class TestRedactURLUserinfo:
    @pytest.mark.ac("ADR-064/AC-24")
    def test_https_url_with_creds(self):
        result = redact("https://fakeuser:fakepass@example.com/path")
        assert "[REDACTED_URL_CREDENTIALS]" in result
        assert "fakepass" not in result

    def test_ftp_url_with_creds(self):
        result = redact("ftp://fakeuser:fakepass@ftp.example.com")
        assert "[REDACTED_URL_CREDENTIALS]" in result
        assert "fakepass" not in result

    @pytest.mark.ac("ADR-064/AC-25")
    def test_username_only_userinfo(self):
        result = redact("https://admin@api.example.com/v1/endpoint")
        assert "[REDACTED_URL_CREDENTIALS]" in result
        assert "admin@" not in result

    @pytest.mark.ac("ADR-064/AC-39")
    def test_url_without_creds_unchanged(self):
        url = "https://example.com/path/to/resource"
        assert redact(url) == url


class TestRedactQueryParams:
    @pytest.mark.ac("ADR-064/AC-26")
    def test_api_key_param(self):
        result = redact("https://example.com/api?api_key=FAKE_VALUE_123")
        assert "[REDACTED_QUERY_PARAM]" in result
        assert "FAKE_VALUE" not in result

    def test_secret_param(self):
        result = redact("https://example.com/callback?secret=FAKE_SECRET")
        assert "[REDACTED_QUERY_PARAM]" in result
        assert "FAKE_SECRET" not in result

    @pytest.mark.ac("ADR-064/AC-27")
    def test_token_param(self):
        result = redact("https://example.com/auth?token=FAKE_TOKEN&redirect=ok")
        assert "[REDACTED_QUERY_PARAM]" in result
        assert "FAKE_TOKEN" not in result
        assert "redirect=ok" in result

    def test_key_param(self):
        result = redact("https://example.com?key=FAKE_KEY_VALUE")
        assert "[REDACTED_QUERY_PARAM]" in result
        assert "FAKE_KEY_VALUE" not in result

    @pytest.mark.ac("ADR-064/AC-28")
    @pytest.mark.ac("ADR-064/AC-39")
    def test_non_secret_param_unchanged(self):
        url = "https://example.com?page=2&sort=name"
        assert redact(url) == url


class TestRedactJSONFields:
    """ADR-064 section 3 — a JSON field whose name marks the value sensitive.

    The whole `"name": "value"` pair is consumed (the engine substitutes
    fixed strings, no backreferences); AC-12..14 require the label present
    and the value gone, not the key preserved.
    """

    @pytest.mark.ac("ADR-064/AC-12")
    def test_json_password_field(self):
        result = redact('{"username": "admin", "password": "s3cret!", "role": "user"}')
        assert "[REDACTED_JSON_SECRET]" in result
        assert "s3cret!" not in result
        assert '"username": "admin"' in result

    @pytest.mark.ac("ADR-064/AC-13")
    def test_json_api_key_field(self):
        key = "sk-" + "proj-" + "1234567890abcdef"
        result = redact('{"api_key": "' + key + '", "model": "gpt-4"}')
        assert "[REDACTED_JSON_SECRET]" in result
        assert "sk-" + "proj-" not in result
        assert '"model": "gpt-4"' in result

    @pytest.mark.ac("ADR-064/AC-14")
    def test_json_non_sensitive_fields_preserved(self):
        text = '{"name": "agent-1", "status": "running"}'
        assert redact(text) == text

    def test_bare_key_and_auth_are_not_sensitive_names(self):
        # "monkey" and "author" would false-positive if bare `key`/`auth`
        # were in the alternation — pin that they are not.
        text = '{"monkey": "bongo", "author": "Jane Doe"}'
        assert redact(text) == text

    def test_term_must_be_a_whole_name_segment(self):
        # "tokenizer" contains `token` and "secretary" contains `secret`, but
        # neither NAMES a credential: a substring hit would corrupt ordinary
        # diagnostic JSON wholesale (PR #479 review).
        text = '{"tokenizer": "cl100k_base", "secretary": "Jane Doe"}'
        assert redact(text) == text

    def test_separated_compound_names_still_match(self):
        for field in ("auth_token", "user.password", "api-key", "client_secret"):
            result = redact('{"' + field + '": "hunter2value"}')
            assert "[REDACTED_JSON_SECRET]" in result, field
            assert "hunter2value" not in result, field

    def test_escaped_quote_does_not_end_the_value_early(self):
        # An escaped quote inside the value must be consumed atomically;
        # ending the match there would leak the credential's tail at every
        # logging boundary (PR #479 review, P1).
        result = redact('{"password": "abc\\"SECRETTAIL"}')
        assert "[REDACTED_JSON_SECRET]" in result
        assert "SECRETTAIL" not in result


class TestRedactTelegramSentry:
    @pytest.mark.ac("ADR-064/AC-42")
    def test_telegram_bot_token(self):
        token = "123456789" + ":" + "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
        result = redact("bot token is " + token)
        assert "[REDACTED_TELEGRAM_TOKEN]" in result
        assert "AAHdqTcvCH1" not in result

    @pytest.mark.ac("ADR-064/AC-43")
    def test_sentry_dsn(self):
        dsn = "https://" + "abc123def456" + "@o123456.ingest.sentry.io/789012"
        result = redact("SENTRY_DSN set to " + dsn)
        assert "[REDACTED_SENTRY_DSN]" in result
        assert "abc123def456" not in result

    def test_sentry_dsn_with_region(self):
        dsn = "https://" + "deadbeef0123" + "@o42.ingest.us.sentry.io/1"
        result = redact(dsn)
        assert "[REDACTED_SENTRY_DSN]" in result
        assert "deadbeef0123" not in result

    def test_timestamp_colon_pair_not_a_telegram_token(self):
        # A digit run followed by a colon is common in logs; without the
        # `AA` discriminator this would be a false positive.
        text = "1692500000:reconnect attempt 3"
        assert redact(text) == text


class TestRedactMultipleSecrets:
    @pytest.mark.ac("ADR-064/AC-44")
    def test_multiple_secrets_in_one_text(self):
        text = (
            f"db=postgres://fu:fp@host/db key={'sk-' + 'FAKE12345678'} auth=Bearer FAKE_TOKEN_VALUE"
        )
        result = redact(text)
        assert "[REDACTED_DB_CONNECTION]" in result
        assert "[REDACTED_API_KEY]" in result
        assert "[REDACTED_AUTH_HEADER]" in result

    @pytest.mark.ac("ADR-064/AC-29")
    def test_multiline_with_mixed_secrets(self):
        sk_key = "sk-" + "FAKEVALUE12345"
        text = f"connecting to db...\npostgres://fu:fp@host/db\nusing key {sk_key}\nall good"
        result = redact(text)
        assert result.count("[REDACTED_") >= 2
        assert "all good" in result


class TestRedactNoFalsePositives:
    @pytest.mark.ac("ADR-064/AC-37")
    def test_plain_text_unchanged(self):
        text = "Hello world, this is a normal message."
        assert redact(text) == text

    @pytest.mark.ac("ADR-064/AC-38")
    def test_code_snippet_unchanged(self):
        code = "def hello(name: str) -> str:\n    return f'Hello {name}'"
        assert redact(code) == code

    def test_random_eyj_not_redacted(self):
        text = "the word eyjafjallajokull is a volcano"
        assert redact(text) == text


class TestRedactCompiledAtImportTime:
    def test_patterns_are_compiled(self):
        import re

        from maistro.security.redact import _PATTERNS

        for pattern, _ in _PATTERNS:
            assert isinstance(pattern, re.Pattern)


class TestNestedPatternSafety:
    """ADR-064 section 4 — a secret wrapped in another syntax must still die.

    Each of these embeds one already-supported secret shape inside JSON or a
    URL. No JSON-aware pattern exists; the claim is that the inner pattern
    fires regardless of what surrounds it, with no partial leakage.

    Secret-shaped literals are assembled by concatenation, matching the rest of
    this file. A contiguous `sk-proj-<40 chars>` in the source is a real
    gitleaks hit even though the value is invented — the scanner reads the
    diff, not our intent — so the split keeps the runtime string identical
    while leaving nothing secret-shaped on any single line.

    Note when mutation-testing these: emptying `_PATTERNS` does not make them
    pass vacuously *and* does not make them all fail, because
    `_HIGH_ENTROPY_RE` is a second, independent redaction path. The named
    pattern is what fires in normal operation (the marker is
    `[REDACTED_API_KEY]`, not `[REDACTED_HIGH_ENTROPY]`); the entropy
    heuristic is defence in depth behind it.
    """

    @pytest.mark.ac("ADR-064/AC-31")
    def test_api_key_inside_json_value_no_partial_leakage(self):
        key = "sk-" + "proj-" + "FAKEabc123def456ghi789jkl012mno345pqr678"
        result = redact('{"token": "' + key + '"}')
        assert key not in result
        assert "abc123" not in result
        assert "[REDACTED" in result

    @pytest.mark.ac("ADR-064/AC-32")
    def test_url_with_credentials_inside_json_field(self):
        dsn = "postgres://fakeadmin:" + "FAKEs3cret" + "@db.example.com/app"
        result = redact('{"connection_string": "' + dsn + '"}')
        assert "FAKEs3cret" not in result
        assert "fakeadmin:" not in result

    @pytest.mark.ac("ADR-064/AC-33")
    def test_query_param_value_with_api_key_prefix(self):
        key = "sk-" + "proj-" + "FAKE1234567890abcdef"
        result = redact("https://api.example.com?api_key=" + key)
        assert key not in result
        assert "1234567890" not in result

    @pytest.mark.ac("ADR-064/AC-23")
    @pytest.mark.ac("ADR-064/AC-34")
    def test_jwt_in_auth_header_fully_consumed_with_marker(self):
        token = "eyJ" + "hbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.FAKEsig123"
        result = redact("Authorization: Bearer " + token)
        assert "hbGciOiJSUzI1NiJ9" not in result
        assert "FAKEsig123" not in result
        assert "[REDACTED_AUTH_HEADER]" in result


class TestRedactScaling:
    """ADR-064/AC-36 — redaction must not rescan quadratically.

    `redact()` runs on the logging hot path (`security/log_redaction.py`), so a
    superlinear pattern is reachable from any untrusted string that reaches a
    log line. Three patterns were quadratic: a 32 KB run of word characters
    cost 5.4 s, 4.2 s of it inside the URL-userinfo regex alone. No adversary
    is required — a base64 blob or a long traceback frame has the same shape.

    Asserted as a *ratio* of two timings on the same machine, not a wall-clock
    ceiling: a slow or contended runner scales both terms and cancels, so this
    does not flake in CI the way an absolute bound does. Each timing is the
    minimum of several runs — the sample least contaminated by scheduling
    noise. Linear is ~4x for 4x input; quadratic is ~16x; 8.0 sits midway on a
    log scale.
    """

    @staticmethod
    def _best(text: str, repeats: int = 5) -> float:
        best = float("inf")
        for _ in range(repeats):
            start = time.perf_counter()
            redact(text)
            best = min(best, time.perf_counter() - start)
        return best

    @pytest.mark.ac("ADR-064/AC-36")
    @pytest.mark.parametrize(
        ("label", "build"),
        [
            ("word run", lambda n: "a" * n),
            ("underscore run", lambda n: "_" * n),
            ("scheme without at", lambda n: "w://x:" + "a" * n),
            ("query key repeat", lambda n: "?" + "key" * (n // 3)),
            ("query apikey repeat", lambda n: "?" + "api_key" * (n // 7)),
            ("begin blocks without end", lambda n: "-----BEGIN RSA PRIVATE KEY-----\n" * (n // 32)),
            # Left-edge shapes for the three patterns added after the fix:
            # a digit run ending in a colon (telegram), a hex run (sentry
            # DSN key), and repeated sensitive field names with no closing
            # value quote (JSON field).
            ("digit run with colon", lambda n: "1" * n + ":AA"),
            ("hex run", lambda n: "a1" * (n // 2)),
            ("json field spam", lambda n: '"token": "' * (n // 10)),
            ("json escaped value never closing", lambda n: '"password": "' + '\\"' * (n // 2)),
        ],
    )
    def test_cost_grows_linearly_with_input(self, label, build):
        ratio = self._best(build(16_000)) / self._best(build(4_000))
        assert ratio < 8.0, f"{label}: 4x input cost {ratio:.1f}x time (linear=4, quadratic=16)"

    @pytest.mark.ac("ADR-064/AC-35")
    @pytest.mark.parametrize(
        "text",
        [
            "user signed in from 10.0.0.1 after retrying twice " * 20,
            '{"level":"info","msg":"handled","dur_ms":12,"path":"/v1/chat"}' * 16,
            "a" * 1024,
            "payload=" + "TGl2ZSBsb25nIGFuZCBwcm9zcGVy" * 36,
        ],
        ids=["prose", "json", "word run", "base64"],
    )
    def test_one_kb_line_stays_well_under_the_budget(self, text):
        """A 10 ms ceiling, ten times ADR-064's 1 ms budget.

        Deliberately loose: the tight bound is machine-specific and would flake,
        while an order-of-magnitude alarm still catches the 2.3 ms regression a
        1 KB unbroken word run caused before the anchors went in.
        """
        assert self._best(text[:1024]) < 0.010


class TestLooksLikeSecretLengthGuard:
    """Both outcomes of the `_MIN_SECRET_LENGTH` guard (#157).

    Naming the two thresholds so `check-security-inventory.py` can verify
    SECURITY.md's claims left this predicate reachable only through `redact`,
    which never drove the short-input arc. A named constant that no test
    exercises is a documented number nothing holds to its meaning.
    """

    @staticmethod
    def _high_entropy_run(length: int) -> str:
        """Build a mixed-charset, high-entropy run without writing one down.

        Assembled rather than literal for the reason given on `_jwt` above: a
        contiguous 32-character key-shaped string trips secret scanners on a
        fresh clone, and the fixture is not a credential.
        """
        alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
        # Stride by a co-prime of the alphabet length so the sample cycles
        # through all three character classes instead of repeating a run.
        return "".join(alphabet[(i * 7) % len(alphabet)] for i in range(length))

    def test_a_run_shorter_than_the_minimum_is_not_a_secret(self):
        short = self._high_entropy_run(_MIN_SECRET_LENGTH - 1)
        assert len(short) < _MIN_SECRET_LENGTH
        assert _looks_like_secret(short) is False

    def test_a_long_mixed_high_entropy_run_is_a_secret(self):
        long = self._high_entropy_run(_MIN_SECRET_LENGTH * 2)
        assert _shannon_entropy(long) > _ENTROPY_BITS_PER_CHAR_THRESHOLD
        assert _looks_like_secret(long) is True

    def test_the_minimum_length_is_inclusive(self):
        """Exactly `_MIN_SECRET_LENGTH` is long enough — the guard is `<`."""
        exact = self._high_entropy_run(_MIN_SECRET_LENGTH)
        assert _looks_like_secret(exact) is True

    def test_length_alone_does_not_make_a_secret(self):
        """A long single-class run clears the guard and fails on entropy."""
        assert _looks_like_secret("a" * (_MIN_SECRET_LENGTH * 2)) is False
