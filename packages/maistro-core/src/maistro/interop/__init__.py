"""Shared cross-product interoperability contract (#458).

``INTEROP_ONTOLOGY_V1`` is the importable registry for the published ontology
in ``quality/shared-interop-ontology-v1.json``; the two representations are
required to serialize identically. The validators are the reviewed public API
for products projecting canonical shared concepts.
"""

from maistro.interop.contract import (
    INTEROP_ONTOLOGY_V1,
    ConceptSpec,
    InteropContractError,
    InteropOntology,
    RelationshipSpec,
    require_compatible,
    validate_projection,
    validate_reference_set,
)

__all__ = [
    "INTEROP_ONTOLOGY_V1",
    "ConceptSpec",
    "InteropContractError",
    "InteropOntology",
    "RelationshipSpec",
    "require_compatible",
    "validate_projection",
    "validate_reference_set",
]
