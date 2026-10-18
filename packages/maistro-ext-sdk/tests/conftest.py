"""Shared fixtures for the ext-SDK suite."""

from __future__ import annotations

from pathlib import Path

import pytest

#: The SDK package root (packages/maistro-ext-sdk), resolved from this file.
SDK_ROOT = Path(__file__).resolve().parents[1]

#: The shipped out-of-tree example (packages/maistro-ext-sdk/examples/...).
EXAMPLE_DIR = SDK_ROOT / "examples" / "minimal-extension"


def valid_manifest_dict() -> dict:
    """A minimal manifest that must validate — the base every mutation starts from.

    A function, not a fixture constant: every test mutates its own copy, so
    one test's tampering can never leak into another's.
    """
    return {
        "id": "acme.weather",
        "publisher": "acme",
        "version": "1.0.0",
        "title": "ACME Weather tool",
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": ["network.outbound"],
        "effects": ["external-side-effect"],
        "network": {"allow": ["api.weather.example"], "allowed_ports": [443]},
        "entrypoint": {"module": "acme_weather.plugin", "object": "PLUGIN"},
    }


@pytest.fixture
def manifest_dict() -> dict:
    return valid_manifest_dict()


@pytest.fixture
def example_dir() -> Path:
    """The shipped example extension directory (out-of-tree by construction:
    it lives under examples/, outside the importable maistro_ext_sdk tree)."""
    return EXAMPLE_DIR
