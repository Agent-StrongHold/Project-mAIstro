"""Backward-compatible import path for chat completion orchestration."""

from services.chat_completion import run_chat_completion

__all__ = ["run_chat_completion"]
