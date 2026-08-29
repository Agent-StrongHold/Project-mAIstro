"""Where a canonical template came from, when it was projected from a legacy one.

SPEC-081226-bb3a **AC-10** asks that every reusable legacy definition preserve
source provenance when it is projected into its canonical template
representation, and it asks it as a Scenario Outline over two kinds: ``agent``
and ``graph/workflow``. The agent half has recorded provenance since #525/#526.
The graph/workflow half did not: `template_adapter.snapshot_to_template` copied
a legacy DAG snapshot into a `GraphTemplate` and recorded nothing about the
snapshot it came from, so a projected template was indistinguishable from one
authored canonically.

That asymmetry is the reason this module exists rather than a third copy of the
same dict literal. `SOURCE_IMPORT_PROVENANCE` was already declared twice, in
`maistro.agents.recipes` and `maistro.agents.importers.base`, with the same
value and no shared definition -- two copies agree by luck, and three would be
a matter of time. It lives in `maistro.graph` because that is the direction the
imports already run: `agents.importers.base` imports `NodeTemplate` from
`maistro.graph.definitions`, not the reverse.

**This is provenance about the source, not about the template.** A template's
own `content_hash` answers "what is in this template"; `source_hash` answers
"what was it made from". A projection that loses the second cannot later prove
which legacy definition a Run's behaviour actually traces back to, which is the
audit question a migration exists to keep answerable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Metadata key under which a projected template records its origin.
SOURCE_IMPORT_PROVENANCE = "source_import_provenance"


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Stable digest of a legacy snapshot.

    ``sort_keys`` and the tight separators make the digest independent of dict
    ordering and of json's default spacing, so the same legacy definition
    hashes identically across processes and Python versions. ``default=str``
    keeps a snapshot carrying a datetime or an enum hashable rather than
    raising -- the importer half already relied on that, and a provenance
    helper that refuses some sources is a helper the caller routes around.
    """
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def import_provenance(
    snapshot: dict[str, Any],
    *,
    source_format: str,
    source_definition: str,
    source_name: str,
    source_version: str | int | None = None,
) -> dict[str, Any]:
    """The provenance record a projected template carries in its metadata.

    ``source_version`` is omitted rather than recorded as ``None`` when the
    legacy format has no version of its own: an absent key says "this format
    does not version its definitions", where a null one says "it does, and we
    lost it".
    """
    provenance: dict[str, Any] = {
        "source_format": source_format,
        "source_definition": source_definition,
        "source_name": source_name,
        "source_hash": snapshot_hash(snapshot),
    }
    if source_version is not None:
        provenance["source_version"] = source_version
    return provenance


__all__ = ["SOURCE_IMPORT_PROVENANCE", "import_provenance", "snapshot_hash"]
