# ruff: noqa: RUF001, RUF002 — ambiguous-unicode literals are this file's subject

"""Shared scan-time text folding for the security scanners.

Warden and the Sentinel PII filter both match regex patterns against text an
attacker controls. The attacker's cheapest move is not to beat the pattern but
to make the scanner and the model see different strings: one zero-width space
inside "ignore" defeats a word-boundary regex while the model reads the word
unimpeded. Every scanner therefore folds its input through this module first,
so a bypass fixed for one boundary is fixed for all of them.

Four folds, applied in order where applicable:

1. NFKD — compatibility decomposition (fullwidth forms, ligatures, composed
   accents) so ``ｉｇｎｏｒｅ`` and ``ﬁ`` match their ASCII spellings.
2. Invisible stripping — format characters (Unicode category Cf: zero-width
   spaces/joiners, directional marks, BOM, soft hyphen) plus U+034F COMBINING
   GRAPHEME JOINER, which is Mn but equally invisible. These carry no visible
   content, so removal is lossless for scanning purposes.
3. Homoglyph folding — a curated map of Cyrillic and Greek letters that render
   identically to the Latin letters security patterns are written in. Warden
   applies this directly to its detection string. The PII filter keeps its
   returned/redacted canonical text at step 2 and scans a separate same-length
   homoglyph-folded detection view, so legitimate non-Latin prose is not
   rewritten while confusable secrets are still detected.
4. Bounded leetspeak folding — only ASCII word-like tokens containing both a
   letter and an approved digit/symbol are folded. The deliberately small map
   (0/o, 1/i, 3/e, 4/a, 5/s, 7/t, @/a, $/s) avoids rewriting ordinary numbers
   while making common instruction overrides share one canonical view.
"""

from __future__ import annotations

import re
import unicodedata

# Invisible characters that are not category Cf but still interrupt a token
# without rendering. U+034F exists specifically to break character sequences.
_EXTRA_INVISIBLES = frozenset({"͏"})

# Letters whose glyphs are indistinguishable from Latin in common fonts, from
# the Cyrillic and Greek blocks. Curated, not generated: each entry is a pair a
# human confirmed renders identically, so a reviewer can audit the list. NFKD
# does not decompose any of these.
_HOMOGLYPHS = str.maketrans(
    {
        # Cyrillic lowercase / uppercase
        "а": "a",
        "А": "A",
        "е": "e",
        "Е": "E",
        "о": "o",
        "О": "O",
        "р": "p",
        "Р": "P",
        "с": "c",
        "С": "C",
        "х": "x",
        "Х": "X",
        "і": "i",
        "І": "I",
        "ѕ": "s",
        "Ѕ": "S",
        "у": "y",
        "У": "Y",
        "ј": "j",
        "Ј": "J",
        "ԛ": "q",
        "ԝ": "w",
        "В": "B",
        "Н": "H",
        "К": "K",
        "М": "M",
        "Т": "T",
        # Greek
        "ο": "o",
        "Ο": "O",
        "ν": "v",
        "Ν": "N",
        "Α": "A",
        "Β": "B",
        "Ε": "E",
        "Ζ": "Z",
        "Η": "H",
        "Ι": "I",
        "Κ": "K",
        "Μ": "M",
        "Ρ": "P",
        "Τ": "T",
        "Υ": "Y",
        "Χ": "X",
    }
)


def strip_invisibles(text: str) -> str:
    """Remove format characters (Cf) and known invisible joiners."""
    return "".join(
        ch for ch in text if unicodedata.category(ch) != "Cf" and ch not in _EXTRA_INVISIBLES
    )


def fold_homoglyphs(text: str) -> str:
    """Fold visually-identical Cyrillic/Greek letters onto their Latin twins."""
    return text.translate(_HOMOGLYPHS)


_LEETSPEAK = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
    }
)
_LEET_TOKEN_RE = re.compile(r"[A-Za-z0-9@$]+")


def fold_bounded_leetspeak(text: str) -> str:
    """Fold common leetspeak only inside mixed letter/leet tokens.

    A token made solely of digits is left unchanged. This keeps dates, IDs,
    and measurements from becoming detection text while handling forms such as
    ``1gnore 4ll prev1ous 1nstruct1ons``.
    """

    def replace(match: re.Match[str]) -> str:
        token = match.group()
        if not any(ch.isalpha() for ch in token) or not any(ch in "013457@$" for ch in token):
            return token
        return token.translate(_LEETSPEAK)

    return _LEET_TOKEN_RE.sub(replace, text)


def normalize_for_detection(text: str) -> str:
    """Canonical Warden fold: Unicode, invisibles, homoglyphs, then leetspeak.

    The leetspeak step is intentionally bounded to mixed ASCII tokens; callers
    that need the user's original text must retain ``text`` separately.
    """
    canonical = fold_homoglyphs(strip_invisibles(unicodedata.normalize("NFKD", text)))
    return fold_bounded_leetspeak(canonical)


def normalize_for_redaction(text: str) -> str:
    """Canonical redaction text: NFKD plus invisible stripping.

    Redaction returns this string to the caller, so it must stay readable as
    the user's own text; global homoglyph folding would rewrite legitimate
    non-Latin prose. Callers that need confusable detection may scan a separate
    same-length ``fold_homoglyphs`` view while keeping offsets anchored here.
    """
    return strip_invisibles(unicodedata.normalize("NFKD", text))
