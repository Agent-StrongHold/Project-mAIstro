"""Tests for maistro.security.ssrf — SSRF outbound URL guard.

Adapted from stronghold's tests/tools/test_executor.py (TestHTTPFallbackSSRFPrefix,
TestHTTPFallbackDNS, TestResolveBlocksPrivate) to the standalone
`validate_outbound_url(url) -> None` / `_offending_address(addresses) -> str | None`
signatures exposed by `maistro.security.ssrf`.
"""

from __future__ import annotations

import socket

import pytest

from maistro.security.ssrf import (
    SSRFBlockedError,
    _offending_address,
    _resolve,
    avalidate_outbound_url,
    validate_outbound_url,
)


def _resolved(hostname: str) -> str | None:
    """The offending address `hostname` resolves to, or None if all are public."""
    return _offending_address(_resolve(hostname))


def _addrinfo_entry(ip: str) -> tuple[object, ...]:
    """Construct a getaddrinfo-style tuple for a given IP."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    if ":" in ip:
        return (family, socket.SOCK_STREAM, 0, "", (ip, 0, 0, 0))
    return (family, socket.SOCK_STREAM, 0, "", (ip, 0))


class TestPrefixBlocklist:
    def test_blocks_loopback(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://127.0.0.1:8080/x")

    def test_blocks_localhost(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://localhost/x")

    def test_blocks_metadata_ip(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_metadata_hostname(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://metadata.google.internal/x")

    def test_blocks_kubernetes_hostname(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://kubernetes.default.svc/x")

    def test_blocks_rfc1918_10_x(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://10.1.2.3/x")

    def test_blocks_rfc1918_172_16(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://172.16.0.1/x")

    def test_blocks_rfc1918_172_31(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://172.31.255.255/x")

    def test_blocks_rfc1918_192_168(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://192.168.1.1/x")

    def test_blocks_ipv6_loopback(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://[::1]/x")

    def test_blocks_ipv6_link_local(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://[fe80::1]/x")

    def test_blocks_zero_prefix(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("http://0.0.0.0/x")

    def test_blocks_https_variant_loopback(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("https://127.0.0.1/x")

    def test_blocks_file_scheme(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("file:///etc/passwd")

    def test_blocks_gopher_scheme(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("gopher://internal/x")

    def test_blocks_ftp_scheme(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("ftp://internal/x")

    def test_blocks_dict_scheme(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("dict://internal/x")

    def test_blocks_ldap_scheme(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("ldap://internal/x")

    def test_case_insensitive_match(self) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("HTTP://LOCALHOST/x")


class TestDNSRebinding:
    def test_allows_public_dns_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resolved = 0

        def fake_getaddrinfo(*a: object, **k: object) -> list[object]:
            nonlocal resolved
            resolved += 1
            return [_addrinfo_entry("93.184.216.34")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        # Should not raise.
        validate_outbound_url("https://public.example.com/x")

        assert resolved == 1

    def test_blocks_dns_rebinding_to_private_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_getaddrinfo(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("10.0.0.5")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(SSRFBlockedError, match=r"10\.0\.0\.5"):
            validate_outbound_url("https://evil.example.com/x")

    def test_an_unresolvable_hostname_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inverted deliberately — see `TestResolveBlocksPrivate` for the reasoning.

        The lookup still happens exactly once: refusing must not cost a retry
        storm against a resolver that is already struggling.
        """
        attempts = 0

        def fake_getaddrinfo(*a: object, **k: object) -> list[object]:
            nonlocal attempts
            attempts += 1
            raise socket.gaierror("no such host")

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(SSRFBlockedError, match="could not be resolved"):
            validate_outbound_url("https://missing.example.com/x")

        assert attempts == 1

    def test_a_url_without_a_hostname_is_refused(self) -> None:
        """Also inverted. "No host to resolve" was read as "nothing to block
        on", which let anything that failed to parse as a URL through the guard
        untouched — including every scheme the shape check now names."""
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url("not-a-url")


class TestResolveBlocksPrivate:
    def test_returns_none_for_public(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("93.184.216.34")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("example.com") is None

    def test_returns_ip_for_private(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("10.0.0.1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("intranet") == "10.0.0.1"

    def test_an_unresolvable_host_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """This assertion is inverted from what it used to say, on purpose.

        The old guard returned "not blocked" on `gaierror`, reasoning that the
        connection would fail anyway — and the old test asserted exactly that.
        But the resolution stage is the only one that inspects addresses, so a
        transient SERVFAIL turned it off and left the prefix list alone against
        anything it does not literally match. A name that cannot be resolved
        cannot be shown to be external, and the guard's job is to refuse in
        precisely that case (#154).
        """

        def fake_gai(*a: object, **k: object) -> list[object]:
            raise socket.gaierror("no host")

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        with pytest.raises(SSRFBlockedError, match="could not be resolved"):
            validate_outbound_url("http://nope.example/x")

    def test_a_host_that_resolves_to_nothing_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty answer is the same claim as no answer: nothing was shown."""

        def fake_gai(*a: object, **k: object) -> list[object]:
            return []

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        with pytest.raises(SSRFBlockedError, match="no addresses"):
            validate_outbound_url("http://empty.example/x")

    def test_skips_malformed_sockaddr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("not-an-ip", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("host") is None

    def test_catches_ipv6_link_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("fe80::1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("ll") == "fe80::1"

    def test_catches_reserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("240.0.0.1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("reserved") == "240.0.0.1"

    def test_catches_multicast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("224.0.0.1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("mcast") == "224.0.0.1"

    def test_catches_the_unspecified_address(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`0.0.0.0` is not `is_reserved`, and on many stacks connecting to it
        reaches localhost — so it needs naming rather than leaving to the other
        predicates."""

        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("0.0.0.0")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolved("unspec") == "0.0.0.0"


class TestShapeIsAWhitelist:
    """A scheme nobody listed is a scheme nobody reasoned about."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://evil/",
            "dict://evil/",
            "ldap://evil/",
            "data:text/html,<script>",
            "not-a-url",
            "",
        ],
    )
    def test_refuses_anything_that_is_not_http(self, url: str) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url(url)

    def test_refuses_an_http_url_with_no_host(self) -> None:
        with pytest.raises(SSRFBlockedError, match="no host"):
            validate_outbound_url("http:///just-a-path")


class TestObfuscatedAddresses:
    """Every spelling of an internal address arrives at the resolution stage as
    the address it denotes, which is why that stage rather than the prefix list
    carries the guarantee."""

    @pytest.mark.parametrize(
        ("url", "what"),
        [
            ("http://2852039166/", "decimal 169.254.169.254"),
            ("http://0x7f000001/", "hex 127.0.0.1"),
            ("http://127.1/", "short-form loopback"),
            ("http://[::ffff:169.254.169.254]/", "IPv4-mapped IPv6 metadata"),
            ("http://[::]/", "IPv6 unspecified"),
            ("http://0.0.0.0/", "IPv4 unspecified"),
        ],
    )
    def test_blocked(self, url: str, what: str) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_outbound_url(url)


class TestAsyncFormAgrees:
    """`browse()` is async, and `getaddrinfo` blocks. The async form exists so a
    slow resolver stalls one coroutine rather than the whole loop — it must not
    also mean a second set of rules."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/",
            "http://127.0.0.1/",
            "file:///etc/passwd",
            "http://[::ffff:169.254.169.254]/",
        ],
    )
    async def test_blocks_what_the_sync_form_blocks(self, url: str) -> None:
        with pytest.raises(SSRFBlockedError):
            await avalidate_outbound_url(url)

    @pytest.mark.asyncio
    async def test_allows_a_public_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("93.184.216.34")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        await avalidate_outbound_url("http://example.com/x")
