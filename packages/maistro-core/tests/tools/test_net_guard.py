"""Tests for maistro.tools.net_guard — SSRF outbound URL guard.

Adapted from stronghold's tests/tools/test_executor.py (TestHTTPFallbackSSRFPrefix,
TestHTTPFallbackDNS, TestResolveBlocksPrivate) to the standalone
`validate_outbound_url(url) -> None` / `_resolve_blocks_private(hostname) -> str | None`
signatures exposed by `maistro.tools.net_guard`.
"""

from __future__ import annotations

import socket

import pytest

from maistro.tools.net_guard import (
    SSRFBlockedError,
    _resolve_blocks_private,
    validate_outbound_url,
)


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

    def test_unresolvable_hostname_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = 0

        def fake_getaddrinfo(*a: object, **k: object) -> list[object]:
            nonlocal attempts
            attempts += 1
            raise socket.gaierror("no such host")

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        # Unresolvable — will fail at connect time, not here.
        validate_outbound_url("https://missing.example.com/x")

        assert attempts == 1

    def test_url_without_hostname_does_not_raise(self) -> None:
        # No netloc/hostname to resolve — nothing to block on.
        validate_outbound_url("not-a-url")


class TestResolveBlocksPrivate:
    def test_returns_none_for_public(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("93.184.216.34")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("example.com") is None

    def test_returns_ip_for_private(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("10.0.0.1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("intranet") == "10.0.0.1"

    def test_returns_none_on_gaierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            raise socket.gaierror("no host")

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("nope") is None

    def test_skips_malformed_sockaddr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("not-an-ip", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("host") is None

    def test_catches_ipv6_link_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("fe80::1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("ll") == "fe80::1"

    def test_catches_reserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("240.0.0.1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("reserved") == "240.0.0.1"

    def test_catches_multicast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_gai(*a: object, **k: object) -> list[object]:
            return [_addrinfo_entry("224.0.0.1")]

        monkeypatch.setattr(socket, "getaddrinfo", fake_gai)
        assert _resolve_blocks_private("mcast") == "224.0.0.1"
