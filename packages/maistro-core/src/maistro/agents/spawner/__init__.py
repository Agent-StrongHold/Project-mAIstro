"""Spawner package — agent execution funnel (ADR-009)."""

from .spawner import LLMCaller, Spawner
from .variant_selector import VariantSelector, VariantStats

__all__ = ["LLMCaller", "Spawner", "VariantSelector", "VariantStats"]
