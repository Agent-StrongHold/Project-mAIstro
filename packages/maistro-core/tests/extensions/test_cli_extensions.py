"""`maistro extensions` read commands over a seeded durable store (M9-B1).

The CLI is the operator's query surface for the acceptance criterion
"provenance is queryable from extension execution/history": these tests seed a
real SQLite database through the store, then run the typer commands against the
file and check the report names publisher, digest, manifest, catalog and trust
evidence — and that missing data exits non-zero instead of printing nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
from typer.testing import CliRunner

from extensions.extension_fixtures import (
    CATALOG_URL,
    install_bundle,
)
from maistro.cli._extensions import app
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore

runner = CliRunner()


def _seed(db_path: Path, *bundles: dict[str, Any]) -> None:
    """Write install records through the real store, then close the connection."""

    async def seed() -> None:
        conn = await aiosqlite.connect(db_path)
        try:
            store = SqliteExtensionInstallStore(conn)
            await store.ensure_schema()
            for bundle in bundles:
                await store.register_publisher(bundle["publisher"])
                await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
        finally:
            await conn.close()

    asyncio.run(seed())


def test_history_reports_publisher_digest_manifest_and_trust(tmp_path: Any) -> None:
    db_path = tmp_path / "installs.db"
    bundle = install_bundle()
    _seed(db_path, bundle)

    result = runner.invoke(app, ["history", str(db_path), "ext-tool"])

    assert result.exit_code == 0
    output = result.output
    assert bundle["identity"].semantic_version in output
    assert bundle["identity"].package_sha256[:12] in output
    assert bundle["publisher"].publisher_id in output
    assert "verified" in output


def test_history_for_an_unknown_extension_reports_empty(tmp_path: Any) -> None:
    db_path = tmp_path / "installs.db"
    _seed(db_path, install_bundle())

    result = runner.invoke(app, ["history", str(db_path), "no-such-extension"])

    assert result.exit_code == 0
    assert "No install records." in result.output


def test_show_prints_provenance_and_trust_evidence(tmp_path: Any) -> None:
    db_path = tmp_path / "installs.db"
    bundle = install_bundle()
    _seed(db_path, bundle)

    result = runner.invoke(app, ["show", str(db_path), "ext-tool", "1.0.0"])

    assert result.exit_code == 0
    output = result.output
    assert bundle["identity"].package_sha256 in output
    assert bundle["identity"].manifest_sha256 in output
    assert bundle["publisher"].display_name in output
    assert CATALOG_URL in output
    assert bundle["request"].provenance.catalog_snapshot_sha256 in output
    # Rendered through _short_timestamp: ISO 'T' becomes a space, seconds kept.
    assert bundle["request"].provenance.retrieved_at.isoformat()[:19].replace("T", " ") in output
    assert "verified=True" in output
    assert bundle["publisher"].signing_key_fingerprint[:12] in output


def test_show_exits_nonzero_for_an_unrecorded_version(tmp_path: Any) -> None:
    db_path = tmp_path / "installs.db"
    _seed(db_path, install_bundle())

    result = runner.invoke(app, ["show", str(db_path), "ext-tool", "9.9.9"])

    assert result.exit_code == 1
    assert "No install record" in result.output


def test_history_on_a_missing_database_fails_closed(tmp_path: Any) -> None:
    result = runner.invoke(app, ["history", str(tmp_path / "absent.db"), "ext-tool"])

    assert result.exit_code == 1


def test_show_prints_the_canonical_attribution_payload(tmp_path: Any) -> None:
    """M9-I1 (#976): `show` renders the evidence fragment telemetry carries.

    The version-tagged attribution payload shown here is the same payload that
    rides in Binding snapshots, activation log fields, and Event provenance —
    so an operator can join a stored effect to the exact installed identity.
    """

    db_path = tmp_path / "installs.db"
    bundle = install_bundle()
    _seed(db_path, bundle)

    result = runner.invoke(
        app,
        [
            "show",
            str(
                db_path,
            ),
            "ext-tool",
            "1.0.0",
        ],
    )
    assert result.exit_code == 0
    output = result.output
    assert "attribution:" in output
    assert "attribution payload:" in output
    # the payload line is the decodable, format-tagged evidence — not prose
    import json

    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("  attribution payload: "))
    payload_chunks = [lines[start].split("attribution payload: ", 1)[1]]
    for line in lines[start + 1 :]:
        if line.startswith("  "):  # the next printed field begins
            break
        payload_chunks.append(line)  # rich's wrap of the long JSON token
    payload = json.loads("".join(payload_chunks))
    assert payload["format"] == "extension-attribution:v1"
    assert payload["extension_id"] == "ext-tool"
    assert payload["version"] == "1.0.0"
    assert payload["package_sha256"] == bundle["identity"].package_sha256
    from maistro.extensions import attribution_from_payload

    assert attribution_from_payload(payload).version == "1.0.0"
