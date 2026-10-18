"""Design Studio - AI-assisted creative-production environment.

Design Studio consumes the persistent Workspace Agent and Goal reconciliation APIs
from #804 rather than instantiating a Design-Studio-private root Agent/reconciler.

The Design Studio projects Design Studio-specific semantics onto the canonical
Goal hierarchy:

- Goal revision + Persona + Workspace memory + Design System + CreativeBrief
                ↓
          Design Studio
             ↙          ↓          ↘
         Canvas       Builders    Deck/media/tools
             ↘          ↓          ↙
                 versioned artifacts
                          ↓
            user/Agent evaluate, edit, lock, redirect

Key responsibilities:
- CreativeBrief: versioned creative projection of one exact canonical Goal revision
- Persona: persistent flavor/taste/purpose (never authorization)
- Workspace memory: scoped context (consumed via #776)
- Design System: applicable visual/brand constraints (consumed via maistro-design)
- Tool selection/composition: Canvas, Deck Builder, Builders, media/providers
- Mixed-control execution: direct, collaborative, delegated modes
- Control state management: inspect, pause, edit/lock, redirect, resume
"""

from .brief import CreativeBrief
from .core import DesignStudio, DesignStudioConfig
from .execution import ControlManager, ControlState, MixedControlExecutor
from .projects import DesignProject
from .tools import StudioToolSelector
from .workspace import WorkspaceContext

__all__ = [
    "ControlManager",
    "ControlState",
    "CreativeBrief",
    "DesignProject",
    "DesignStudio",
    "DesignStudioConfig",
    "MixedControlExecutor",
    "StudioToolSelector",
    "WorkspaceContext",
]
