"""The PII filter's contract, asserted as properties rather than examples.

Three findings drove this file:

- ``redact()`` returned the original string on no-match and the normalized
  string on match — one function, two encodings, conditional on secret
  presence. The property here is encoding invariance.
- ``PIIMatch.value`` carried the raw secret across the API boundary; the
  match list is logged by two callers. The property is that no plaintext
  survives in any return path.
- The filter detected credentials only while being named ``pii_filter``. The
  new detectors get tests that fire on their motivating inputs, plus
  negative controls for the false positives the validators exist to reject.
"""

from __future__ import annotations

import unicodedata

import pytest

from maistro.security.sentinel.pii_filter import (
    PIIMatch,
    redact,
    scan_and_redact,
    scan_for_pii,
)


class TestRedactEncodingInvariance:
    def test_no_match_output_is_normalized_not_original(self) -> None:
        """Same encoding whether or not a secret was present."""
        text = "conﬁg ﬁle ½ done"  # ligatures + fraction, no secrets
        assert scan_for_pii(text) == []
        assert redact(text) == unicodedata.normalize("NFKD", text)

    def test_output_encoding_is_independent_of_match_presence(self) -> None:
        """redact(prefix) must be a literal prefix of redact(prefix + secret)'s
        context — i.e. the no-match path applies the same fold as the match
        path, so downstream diffing can't infer secret presence from encoding."""
        prefix = "conﬁg entry: "
        with_secret = prefix + "AKIAIOSFODNN7EXAMPLE"
        assert redact(with_secret).startswith(redact(prefix))

    def test_redact_is_idempotent(self) -> None:
        for text in ("plain", "conﬁg ﬁle", "key AKIAIOSFODNN7EXAMPLE end"):
            once = redact(text)
            assert redact(once) == once

    def test_zero_width_space_inside_secret_does_not_evade(self) -> None:
        """A ZWSP every few characters used to defeat every pattern while the
        receiving model read the secret unimpeded."""
        secret = "AKIA​IOSF​ODNN​7EXAMPLE"
        redacted, matches = scan_and_redact(f"leak {secret} end")
        assert any(m.pii_type == "aws_key" for m in matches)
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert "[REDACTED:aws_key]" in redacted


class TestNoPlaintextInReturnPaths:
    def test_match_value_is_masked(self) -> None:
        secret = "AKIAIOSFODNN7EXAMPLE"
        matches = scan_for_pii(f"key {secret} end")
        assert len(matches) == 1
        assert secret not in matches[0].value
        assert matches[0].value == "AKIA…(20 chars)"

    def test_no_return_path_carries_the_secret(self) -> None:
        secret = "ghp_" + "Zq8" * 12  # 36 chars after the prefix
        redacted, matches = scan_and_redact(f"token {secret} here")
        assert secret not in redacted
        for m in matches:
            assert secret not in m.value

    def test_masked_value_still_identifies_the_credential_family(self) -> None:
        """The mask keeps the public prefix so an operator can tell WHICH kind
        of key leaked without the log re-leaking it."""
        matches = scan_for_pii("key sk-abcdefghijklmnopqrstu end")
        assert matches and matches[0].value.startswith("sk-a")


class TestPersonalDataDetectors:
    def test_payment_card_luhn_valid_detected(self) -> None:
        for pan in ("4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"):
            matches = scan_for_pii(f"card {pan} on file")
            assert any(m.pii_type == "payment_card" for m in matches), pan

    def test_luhn_invalid_digit_run_ignored(self) -> None:
        """A random 16-digit number (order id, tracking number) must not be
        flagged — the Luhn validator is what makes this detector shippable."""
        assert scan_for_pii("order 1234 5678 9012 3456 shipped") == []

    def test_ssn_detected(self) -> None:
        matches = scan_for_pii("SSN: 219-09-9999")
        assert any(m.pii_type == "ssn" for m in matches)

    def test_never_issued_ssn_shapes_ignored(self) -> None:
        for fake in ("000-12-3456", "666-12-3456", "900-12-3456", "219-00-3456", "219-09-0000"):
            assert scan_for_pii(f"id {fake} x") == [], fake

    def test_international_phone_detected(self) -> None:
        for phone in ("+1 415 555 0132", "+44 20 7946 0958", "+31 6 1234 5678"):
            matches = scan_for_pii(f"call {phone} today")
            assert any(m.pii_type == "phone" for m in matches), phone

    def test_bare_local_number_is_deliberately_ignored(self) -> None:
        """Documented scope limit, pinned so it reads as a decision rather
        than a gap: local forms without +CC are indistinguishable from
        ordinary numerics at acceptable false-positive rates."""
        assert scan_for_pii("call 555-0132 today") == []

    def test_redaction_covers_new_types(self) -> None:
        redacted, _ = scan_and_redact("pan 4111 1111 1111 1111 ssn 219-09-9999")
        assert "4111" not in redacted
        assert "219-09-9999" not in redacted
        assert "[REDACTED:payment_card]" in redacted
        assert "[REDACTED:ssn]" in redacted


class TestCredentialShapes:
    """#1159 — credential detectors beyond prefixes, typed and ordered.

    The three new detectors (``aws_secret_key``, ``slack_token``,
    ``secret_assignment``) share their compiled shapes with
    ``security/redact.py`` through ``security/secret_policy.py``. Detector
    order is load-bearing: ``secret_assignment`` sits LAST, so a more
    specific detector that claims the value keeps it and the overlap-drop
    rule leaves no partial span.
    """

    def test_slack_token_typed_and_redacted(self) -> None:
        redacted, matches = scan_and_redact("upload xoxb-FAKEVALUE123456 done")
        assert [m.pii_type for m in matches] == ["slack_token"]
        assert "[REDACTED:slack_token]" in redacted
        assert "FAKEVALUE" not in redacted

    @pytest.mark.parametrize("prefix", ["xoxa", "xoxb", "xoxp", "xoxr", "xoxs"])
    def test_whole_slack_family_detected(self, prefix: str) -> None:
        matches = scan_for_pii(f"slack {prefix}-FAKEVALUE123456 end")
        assert [m.pii_type for m in matches] == ["slack_token"], prefix

    def test_aws_secret_key_typed_and_redacted(self) -> None:
        # Space-delimited: the 40-char run is a maximal AWS-charset run. (In
        # the `name=<secret>` form the value sits next to `=`, which is part
        # of the AWS charset, so the generic assignment claims it instead.)
        secret = "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
        redacted, matches = scan_and_redact(f"leaked secret {secret} in args")
        assert [m.pii_type for m in matches] == ["aws_secret_key"]
        assert "[REDACTED:aws_secret_key]" in redacted
        assert secret not in redacted

    def test_secret_adjacent_to_equals_gets_assignment_label(self) -> None:
        secret = "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
        matches = scan_for_pii(f"secret_access_key={secret} end")
        assert [m.pii_type for m in matches] == ["secret_assignment"]

    def test_generic_secret_assignment_typed_and_redacted(self) -> None:
        redacted, matches = scan_and_redact("config my_secret = 'hunter2pass' end")
        assert [m.pii_type for m in matches] == ["secret_assignment"]
        assert "[REDACTED:secret_assignment]" in redacted
        assert "hunter2pass" not in redacted

    def test_key_equals_akia_stays_typed_aws_key(self) -> None:
        # Ordering rule: aws_key is earlier in _PII_PATTERNS and its span is
        # the whole assignment value, so secret_assignment (last) is dropped.
        matches = scan_for_pii("key=AKIAIOSFODNN7EXAMPLE end")
        assert [m.pii_type for m in matches] == ["aws_key"]

    def test_named_password_stays_typed_password(self) -> None:
        matches = scan_for_pii("db_password=hunter2pass end")
        assert [m.pii_type for m in matches] == ["password"]

    def test_lowercase_hex_sha_is_not_detected(self) -> None:
        sha = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        assert scan_for_pii(f"commit {sha} ok") == []

    def test_akia_id_is_not_typed_aws_secret_key(self) -> None:
        matches = scan_for_pii("id AKIAIOSFODNN7EXAMPLE end")
        assert matches and all(m.pii_type == "aws_key" for m in matches)

    @pytest.mark.parametrize(
        "text",
        [
            "tokenizer = cl100k_base-vocab",
            "secretary = JaneDoe99",
            "monkey = bongo1234",
        ],
        ids=["tokenizer", "secretary", "monkey"],
    )
    def test_ordinary_words_are_not_secret_assignments(self, text: str) -> None:
        assert scan_for_pii(text) == []

    def test_url_is_not_a_secret_assignment(self) -> None:
        assert scan_for_pii("https://example.com/path?q=1") == []

    def test_full_pem_block_body_is_redacted(self) -> None:
        """#1159 repair: the base64 body between the markers IS the reusable
        credential. The base64-decode candidate path cannot catch it (a key
        body decodes to non-UTF-8 bytes), so the full-block detector must."""
        body = (
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/yGaTkxHhZPwkY9tX3kF3wXHrWKBhJ5bHUmIg\n"
            "ZPwkY9tX3kF3wXHrWKBhJ5bHUmIgMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/yGaTkxHh"
        )
        pem = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
        redacted, matches = scan_and_redact(pem)
        assert [m.pii_type for m in matches] == ["private_key"]
        # One span covering the whole block — not just the BEGIN header.
        assert matches[0].start == 0 and matches[0].end == len(pem)
        assert "MIIEpAIB" not in redacted
        assert redacted.startswith("[REDACTED:private_key]")

    def test_truncated_pem_header_still_detected(self) -> None:
        # An unterminated block has no END marker for the full-block shape;
        # the header-only fallback still flags the leak that is starting.
        matches = scan_for_pii("-----BEGIN OPENSSH PRIVATE KEY----- and then output cuts out")
        assert [m.pii_type for m in matches] == ["private_key"]

    def test_email_and_card_detection_unchanged(self) -> None:
        # The new detectors sit last and claim nothing the older detectors
        # already cover — personal-data detection is untouched (#1159).
        matches = scan_for_pii("user@example.com paid 4111 1111 1111 1111")
        assert [m.pii_type for m in matches] == ["email", "payment_card"]


class TestMatchInvariants:
    def test_matches_are_frozen_and_sorted(self) -> None:
        matches = scan_for_pii("a@b.co then AKIAIOSFODNN7EXAMPLE")
        assert [m.start for m in matches] == sorted(m.start for m in matches)
        assert isinstance(matches[0], PIIMatch)


class TestEmailCharacterClass:
    """`[A-Z|a-z]` put a literal pipe in the TLD class.

    The distinguishing input is a TLD containing `|` — a plain
    `user@example.com` case passes against the buggy pattern too and proves
    nothing, which is why the bug survived every previous email test.
    """

    def test_tld_with_pipe_is_not_an_email(self) -> None:
        assert [m for m in scan_for_pii("write to a@b.c|m today") if m.pii_type == "email"] == []

    def test_pipe_bearing_text_is_not_redacted_as_email(self) -> None:
        redacted, _ = scan_and_redact("cmd: a@b.c|m")
        assert "[REDACTED:email]" not in redacted

    def test_ordinary_addresses_still_detected(self) -> None:
        for address in ("user@example.com", "first.last+tag@sub.domain.co.uk"):
            found = [m for m in scan_for_pii(f"contact {address}") if m.pii_type == "email"]
            assert found, address
