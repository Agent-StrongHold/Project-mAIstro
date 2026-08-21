"""Input sanitization: strip zero-width chars, normalize unicode."""

from __future__ import annotations

import re


def sanitize(text: str) -> str:
    text = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ANSI/VT terminal control sequences. Covers CSI (ESC [ ... final-byte), OSC
# (ESC ] ... terminated by BEL or ST), and other two-char ESC sequences. OSC in
# particular is dangerous in LLM/tool output: OSC 52 writes the system
# clipboard, and OSC 8 embeds hyperlinks \u2014 both let untrusted text manipulate
# the operator's terminal outside the visible content.
_TERMINAL_ESCAPE_RE = re.compile(
    r"""
      \x1b\[ [0-?]* [ -/]* [@-~]          # CSI: ESC [ ... final byte
    | \x1b\] .*? (?: \x07 | \x1b\\ )      # OSC: ESC ] ... BEL or ST
    | \x1b [@-Z\\-_]                       # other 2-char ESC sequences
    | [\x00-\x08\x0b\x0c\x0e-\x1f\x7f]     # bare control chars (keep \t \n \r)
    """,
    re.VERBOSE | re.DOTALL,
)


def strip_terminal_escapes(text: str) -> str:
    """Remove ANSI/OSC/VT escape sequences and bare control characters.

    Apply to any content of untrusted provenance (LLM responses, tool output,
    external content) BEFORE printing it to a terminal, so the text cannot drive
    the terminal (clipboard writes, cursor games, title spoofing, hyperlinks).
    Tab, newline and carriage return are preserved.
    """
    return _TERMINAL_ESCAPE_RE.sub("", text)
