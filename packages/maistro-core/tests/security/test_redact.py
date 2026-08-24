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
        assert redact(None) == ""

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
