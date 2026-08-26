"""Who is allowed to say a request arrived over TLS (#369).

`hive-conductor` and `maistro-server` each carried their own copy of this:

    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",")[0].strip().lower() == "https"

The first half is fact — the ASGI server knows what it accepted. The second is
a **claim by the client**, and nothing checked who was making it. Any caller
could send `X-Forwarded-Proto: https` to a plain-HTTP deployment and be told,
in the response, that the origin is HSTS-eligible for two years including
subdomains.

None of these tests pass against the pre-fix copies, which had no notion of a
trusted proxy at all.
"""

from __future__ import annotations

import pytest

from maistro.security.transport import (
    FORWARDED_PROTO_HEADER,
    InsecureTransportError,
    assert_session_transport_is_safe,
    is_trusted_proxy,
    parse_trusted_proxies,
    request_is_https,
)

PROXIES = parse_trusted_proxies("10.0.0.0/8,192.168.1.5")


class TestTheAsgiSchemeIsBelieved:
    """The server accepted the connection and knows what it was."""

    def test_https_is_https_with_no_proxy_configured(self) -> None:
        assert request_is_https(scheme="https", headers={}, client_host=None)

    def test_the_scheme_is_matched_case_insensitively(self) -> None:
        assert request_is_https(scheme="HTTPS", headers={}, client_host=None)

    def test_plain_http_is_not_https(self) -> None:
        assert not request_is_https(scheme="http", headers={}, client_host="10.1.2.3")


class TestAForwardedHeaderIsOnlyBelievedFromAProxy:
    """The defect, stated as a property: the header decides a security control,
    so it may not be accepted from whoever happens to send it."""

    def test_an_untrusted_caller_cannot_claim_https(self) -> None:
        assert not request_is_https(
            scheme="http",
            headers={FORWARDED_PROTO_HEADER: "https"},
            client_host="203.0.113.9",
            trusted_proxies=PROXIES,
        )

    def test_a_trusted_proxy_can(self) -> None:
        # The legitimate arrangement this exists to support: TLS terminated at
        # a reverse proxy in front of a plain-HTTP upstream.
        assert request_is_https(
            scheme="http",
            headers={FORWARDED_PROTO_HEADER: "https"},
            client_host="10.1.2.3",
            trusted_proxies=PROXIES,
        )

    def test_naming_no_proxy_trusts_nobody(self) -> None:
        """The default, and the safe direction to get wrong: a deployment that
        forgets to configure its proxy loses HSTS rather than gaining a header
        anyone can forge."""
        assert not request_is_https(
            scheme="http",
            headers={FORWARDED_PROTO_HEADER: "https"},
            client_host="10.1.2.3",
        )

    def test_a_trusted_proxy_reporting_http_is_believed_too(self) -> None:
        """Trust runs both ways. A proxy that says the browser used plain HTTP
        is the authority on that."""
        assert not request_is_https(
            scheme="http",
            headers={FORWARDED_PROTO_HEADER: "http"},
            client_host="10.1.2.3",
            trusted_proxies=PROXIES,
        )

    def test_the_leftmost_hop_is_the_one_that_counts(self) -> None:
        """`X-Forwarded-Proto` accumulates left to right, so the first entry is
        the scheme the browser-facing proxy saw. A later `https` from an inner
        hop says nothing about the browser's connection."""
        assert not request_is_https(
            scheme="http",
            headers={FORWARDED_PROTO_HEADER: "http, https"},
            client_host="10.1.2.3",
            trusted_proxies=PROXIES,
        )

    def test_whitespace_and_case_in_the_header_are_tolerated(self) -> None:
        assert request_is_https(
            scheme="http",
            headers={FORWARDED_PROTO_HEADER: "  HTTPS , http"},
            client_host="10.1.2.3",
            trusted_proxies=PROXIES,
        )

    def test_a_missing_header_from_a_trusted_proxy_is_not_https(self) -> None:
        assert not request_is_https(
            scheme="http", headers={}, client_host="10.1.2.3", trusted_proxies=PROXIES
        )


class TestWhichPeersCount:
    @pytest.mark.parametrize("host", ["10.0.0.1", "10.255.255.254", "192.168.1.5"])
    def test_an_address_inside_a_named_block_is_trusted(self, host: str) -> None:
        assert is_trusted_proxy(host, PROXIES)

    @pytest.mark.parametrize("host", ["11.0.0.1", "192.168.1.6", "127.0.0.1"])
    def test_an_address_outside_every_block_is_not(self, host: str) -> None:
        assert not is_trusted_proxy(host, PROXIES)

    def test_no_peer_address_is_not_trusted(self) -> None:
        """Real rather than theoretical: a request over a Unix socket has no
        peer address. The honest answer is "no", not "probably fine"."""
        assert not is_trusted_proxy(None, PROXIES)
        assert not is_trusted_proxy("", PROXIES)

    def test_an_unparseable_peer_is_not_trusted(self) -> None:
        assert not is_trusted_proxy("not-an-address", PROXIES)

    def test_ipv6_works(self) -> None:
        proxies = parse_trusted_proxies("fd00::/8")
        assert is_trusted_proxy("fd00::1", proxies)
        assert not is_trusted_proxy("2001:db8::1", proxies)


class TestParsingTheProxyList:
    def test_a_bare_address_is_a_single_host(self) -> None:
        """`10.0.0.7` is what an operator writes; `10.0.0.7/32` is what they
        mean."""
        assert is_trusted_proxy("10.0.0.7", parse_trusted_proxies("10.0.0.7"))
        assert not is_trusted_proxy("10.0.0.8", parse_trusted_proxies("10.0.0.7"))

    def test_whitespace_around_entries_is_ignored(self) -> None:
        assert len(parse_trusted_proxies(" 10.0.0.0/8 , 172.16.0.0/12 ")) == 2

    def test_an_empty_setting_trusts_nothing(self) -> None:
        assert parse_trusted_proxies("") == ()
        assert parse_trusted_proxies(None) == ()

    def test_a_typo_costs_that_entry_and_not_the_process(self) -> None:
        """One bad entry in a list of five proxies should lose that proxy's
        trust, not refuse to start. Failing closed per-entry is already the
        safe direction."""
        proxies = parse_trusted_proxies("10.0.0.0/8, nonsense, 172.16.0.0/12")

        assert len(proxies) == 2
        assert is_trusted_proxy("10.1.1.1", proxies)

    def test_a_host_bit_set_inside_a_cidr_is_accepted(self) -> None:
        """`10.1.2.3/8` is a common way to write it and strict parsing would
        reject it, which reads to an operator as "my proxy list is broken"."""
        assert is_trusted_proxy("10.9.9.9", parse_trusted_proxies("10.1.2.3/8"))

    def test_a_list_can_be_passed_instead_of_a_string(self) -> None:
        assert len(parse_trusted_proxies(["10.0.0.0/8", "172.16.0.0/12"])) == 2


class TestStartupRefusesPlaintextSessions:
    """The AC's "production startup rejects insecure transport or
    Secure-disabled sessions unless an explicit local-development mode is
    active"."""

    def test_a_secure_cookie_starts(self) -> None:
        assert_session_transport_is_safe(cookie_secure=True, allow_insecure_transport=False)

    def test_a_plaintext_session_refuses_to_start(self) -> None:
        with pytest.raises(InsecureTransportError):
            assert_session_transport_is_safe(cookie_secure=False, allow_insecure_transport=False)

    def test_the_local_development_escape_allows_it(self) -> None:
        assert_session_transport_is_safe(cookie_secure=False, allow_insecure_transport=True)

    def test_the_escape_is_a_separate_flag_from_the_control(self) -> None:
        """Turning off a security control and declaring a development run are
        different statements. Collapsing them into one setting is how the first
        becomes invisible inside the second — so the escape cannot be reached
        by any value of `cookie_secure` alone."""
        with pytest.raises(InsecureTransportError):
            assert_session_transport_is_safe(cookie_secure=False, allow_insecure_transport=False)

    def test_the_message_names_the_setting_and_the_way_out(self) -> None:
        """An operator hitting this at 3am needs the variable name, not a
        principle."""
        with pytest.raises(InsecureTransportError) as caught:
            assert_session_transport_is_safe(cookie_secure=False, allow_insecure_transport=False)
        message = str(caught.value)

        assert "SESSION_COOKIE_SECURE" in message
        assert "ALLOW_INSECURE_TRANSPORT" in message

    def test_the_message_says_what_the_risk_actually_is(self) -> None:
        with pytest.raises(InsecureTransportError) as caught:
            assert_session_transport_is_safe(cookie_secure=False, allow_insecure_transport=False)

        assert "plaintext" in str(caught.value)

    def test_the_profile_is_named_when_given(self) -> None:
        """Two services call this; the log has to say which one refused."""
        with pytest.raises(InsecureTransportError) as caught:
            assert_session_transport_is_safe(
                cookie_secure=False, allow_insecure_transport=False, profile="hive-conductor"
            )

        assert "hive-conductor" in str(caught.value)
