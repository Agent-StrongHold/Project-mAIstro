"""M8-A2 research gate — Invocation effect/idempotency stateful testing (#882).

Epic #880, initiative #879. The experiment's deliverable contract is
prototype + findings + disposition; this gate pins all three to paths CI
already runs, so the research note cannot silently lose its disposition, its
candidate-invariant record, or the prototype that produced the evidence.

Trust boundary (the epic's contract, enforced by construction): this module
reads repository markdown and source text only. It imports nothing from
``maistro``, records no metrics machinery, and authorizes nothing — the
executable evidence itself lives in ``formal/models/`` and runs under the
formal-conformance workflow, not here.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTE = REPO_ROOT / "docs/research/882-invocation-effect-idempotency-stateful-testing.md"
PROTOTYPE = REPO_ROOT / "formal/models/test_invocation_effect_idempotency.py"

CANDIDATE_INVARIANTS = (
    "never dispatch twice",
    "block automatic repetition",
    "only proven-not-applied FAILED",
    "stable across physical Attempts",
    "terminal timestamps",
    "duplicate provider execution",
)
DISPOSITIONS = ("GRADUATE", "INCUBATE", "REJECT", "WATCH")


def test_research_note_records_contract_and_disposition() -> None:
    # Probes are matched against whitespace-collapsed text so line wrapping
    # in the markdown cannot hide a recorded phrase.
    text = " ".join(NOTE.read_text().split())
    assert "## Disposition" in text, "note lost its disposition section"
    emitted = [d for d in DISPOSITIONS if f"**{d}**" in text]
    assert len(emitted) == 1, f"exactly one disposition required, found {emitted}"
    for invariant in CANDIDATE_INVARIANTS:
        assert invariant in text, f"note no longer records candidate invariant: {invariant}"
    # The yield claim is comparative, not absolute: it must cite the mutant
    # battery and the conformance baseline it was measured against.
    assert "708" in text, "note must cite the conformance baseline the yield was measured against"


def test_prototype_exists_and_is_a_stateful_model() -> None:
    text = PROTOTYPE.read_text()
    assert "RuleBasedStateMachine" in text, "prototype must be a stateful machine"
    assert "@invariant()" in text, "prototype must assert step invariants"
    assert "InvocationExecutionService" in text, "prototype must drive the real lifecycle service"
    for outcome in ("not_applied", "generic", "cancelled"):
        assert outcome in text, f"prototype must generate the {outcome} provider outcome"
    assert "race_duplicate_logical_effect" in text, (
        "prototype must race duplicate concurrent logical effects"
    )


def test_invariants_registered_in_formal_evidence_ledger() -> None:
    ledger = (REPO_ROOT / "formal/INVARIANTS.md").read_text()
    assert "I31 `test_invocation_effect_idempotency.py`" in ledger, (
        "model must be registered as counted evidence I31"
    )
    assert "M5: ordinary effects widened to Run scope" in ledger, (
        "the unique-yield mutants must be demonstrated in the ledger"
    )
