"""maistro-automaton: deterministic autonomous-actor machinery.

The tickable skeleton of a self-moving actor — reactor, drives, producers,
motivation arbitration, episode persistence port, cage verdicts — with no
identity, no platform imports, and no opinions about what the actor wants.
Hosts supply the wants (DriveSpecs), the world (facets + mood), the durability
(EpisodeSink), and the law (CageCheckpoints). Turing is one instantiation of
this machinery; the merge train is another; neither is the library.

See docs/specs/SPEC-282-automaton-actor-machinery.md.
"""

from maistro_automaton.arbiter import (
    MotivationArbiter,
    Producer,
    ThresholdGate,
    candidate,
)
from maistro_automaton.cage import CageCheckpoint, CageVerdict, first_block
from maistro_automaton.drives import (
    MoodContractError,
    compute_drive,
    compute_drives,
)
from maistro_automaton.memory import EpisodeSink
from maistro_automaton.reactor import IntervalTrigger, Reactor, TickReactor
from maistro_automaton.types import (
    Candidate,
    DriveSpec,
    DriveTerm,
    DriveTermKind,
    Episode,
)

__all__ = [
    "CageCheckpoint",
    "CageVerdict",
    "Candidate",
    "DriveSpec",
    "DriveTerm",
    "DriveTermKind",
    "Episode",
    "EpisodeSink",
    "IntervalTrigger",
    "MoodContractError",
    "MotivationArbiter",
    "Producer",
    "Reactor",
    "ThresholdGate",
    "TickReactor",
    "candidate",
    "compute_drive",
    "compute_drives",
    "first_block",
]

__version__ = "0.9.0"
