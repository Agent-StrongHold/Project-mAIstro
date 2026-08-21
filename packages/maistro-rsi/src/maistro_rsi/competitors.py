"""A competitor is one fixer configuration in a tournament (SPEC-070126-9d37).

It is the projection of an evolve ``NodeGenome`` the RSI loop needs to run an
attempt: which model and (optionally) which sampling temperature. The full
genome (prompt, strategy, topology) is the evolve-driven form; ``--competitors``
is the direct CLI form for a fixed roster.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Competitor:
    """One fixer config: a model alias, sampling knobs, and an optional system
    prompt (the evolvable strategy layer rendered from a genome).

    ``reasoning_effort`` (reasoning-model effort level) and ``temperature``
    (non-reasoning sampling) are mutually exclusive at the LLM callable — see
    ``maistro_bootstrap.builders.responses_callable.LiteLLMCallable`` — a
    competitor may carry either, both (reasoning_effort wins), or neither.

    ``label`` and ``prompt`` are excluded from equality so two competitors with the
    same model/temperature/reasoning_effort compare equal regardless of label or
    prompt text.
    """

    model: str
    temperature: float | None = None
    reasoning_effort: str | None = None
    prompt: str | None = field(default=None, compare=False)
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = (
                self.model if self.temperature is None else f"{self.model}@{self.temperature}"
            )


def parse_competitors(spec: str) -> list[Competitor]:
    """Parse a ``model@temp,model,...`` roster string into competitors.

    A bare ``model`` means no explicit temperature (provider default). Whitespace
    around entries and the ``@`` is tolerated; an empty/blank string yields ``[]``.
    """
    out: list[Competitor] = []
    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            continue
        if "@" in part:
            model, _, temp = part.partition("@")
            out.append(Competitor(model=model.strip(), temperature=float(temp.strip())))
        else:
            out.append(Competitor(model=part))
    return out
