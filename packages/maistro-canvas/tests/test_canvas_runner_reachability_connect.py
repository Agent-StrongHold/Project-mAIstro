"""CONNECT proof: build_canvas_runtime statically roots canvas.runner (#93)."""

from __future__ import annotations

import inspect

import maistro_canvas.canvas.composition as composition
from maistro_canvas.canvas.runner import CanvasJobRunner


def test_build_canvas_runtime_statically_imports_canvas_job_runner() -> None:
    """composition names CanvasJobRunner directly so reachability sees the edge."""
    source = inspect.getsource(composition)
    assert "from maistro_canvas.canvas.runner import CanvasJobRunner" in source
    assert "importlib.import_module" not in source
    assert composition.CanvasJobRunner is CanvasJobRunner
