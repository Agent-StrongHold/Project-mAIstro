#!/usr/bin/env python3
"""Vendor the official BFCL v4 AST checker and Python-AST corpus, reproducibly.

Same rationale and mechanics as ``scripts/vendor_ifeval.py`` (read its docstring
for the full argument): the corpus is the exam and the checker is the grader, so
both belong in git — on the ``SENSITIVE_PATH_PATTERNS`` surface, byte-stable
across cycles, and usable from a network-denied scoring container. The transform
is a script so review shrinks to "is this transform correct?", and ``--check``
verifies the committed tree offline in CI.

Two differences from the IFEval vendoring, both improvements:

1. **Source is a versioned PyPI wheel, not a moving git branch.** BFCL ships as
   the ``bfcl-eval`` package; we pin one exact release artifact
   (``bfcl_eval-2026.3.23-py3-none-any.whl``) by its own sha256 — which matches
   PyPI's published digest — plus a sha256 for every member we extract. Upstream
   cannot drift under us because a released wheel never changes.

2. **One semantic substitution, not just import-path rewrites.** Upstream's
   ``ast_checker.py`` imports ``MODEL_CONFIG_MAPPING`` — a registry of every
   model on the BFCL leaderboard — from a module that transitively imports every
   vendor SDK (openai, anthropic, cohere, vllm, ...). The checker consults it on
   exactly one line, ``convert_func_name``, to decide whether a given *model* is
   granted the ``.``→``_`` function-name accommodation (OpenAI-style APIs
   forbid dots in function names, so those models are allowed to answer
   ``a_b_c`` where the ground truth says ``a.b.c``). Our adapter's responses are
   parsed by our own code, which performs no such renaming, so the honest
   configuration for our "model" is **no accommodation** — the response must
   name the function exactly. ``_model_config_shim.py`` (authored here, clearly
   marked NOT upstream) answers ``underscore_to_dot = False`` for every model
   name. This is strictly *harsher* than what any leaderboard model gets, never
   more lenient, and every grading verdict path is otherwise untouched.

The vendored subset is the **Python AST track**: ``simple_python``,
``multiple``, ``parallel``, ``parallel_multiple`` — 1,000 instances with official
ground truth, all gradeable by deterministic AST comparison with no model
execution. The java/js type converters are vendored too because the checker
imports them at module level, but the java/js *corpora* are not: grading them
honestly needs tree-sitter parsing of model output, which is a heavier
dependency for a corpus a Python-centric agent loop doesn't need.

Usage
-----
    python3 scripts/vendor_bfcl.py            # fetch wheel + write the vendored tree
    python3 scripts/vendor_bfcl.py --check    # verify the committed tree (no network)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR_DIR = (
    REPO
    / "packages"
    / "maistro-evolve"
    / "src"
    / "maistro_evolve"
    / "benchmarks"
    / "third_party"
    / "bfcl"
)

WHEEL_URL = (
    "https://files.pythonhosted.org/packages/ba/41/"
    "ed458527c770c50225b60bae3b0c3444b26804ee455fa2d8f187018d2cb2/"
    "bfcl_eval-2026.3.23-py3-none-any.whl"
)
WHEEL_SHA256 = "3bb6dfa5f0c68ad403c9ec50b00db2bb3b4cc9b38ab1ff33f48fe30d853d3a0a"
UPSTREAM_VERSION = "2026.3.23"

# (member path inside the wheel, vendored path, pinned sha256 of the member)
ARTIFACTS: list[tuple[str, str, str]] = [
    (
        "bfcl_eval/eval_checker/ast_eval/ast_checker.py",
        "ast_checker.py",
        "2aae7a68461a8f76c0be3894c8901b66b56967a1989d3ab066051e3fb97f1538",
    ),
    (
        "bfcl_eval/eval_checker/ast_eval/type_convertor/java_type_converter.py",
        "type_convertor/java_type_converter.py",
        "2fd4f4b0443b3dd974a1723bb4e45c086d7b352631062da7807ad1ad40706604",
    ),
    (
        "bfcl_eval/eval_checker/ast_eval/type_convertor/js_type_converter.py",
        "type_convertor/js_type_converter.py",
        "a114e9ff75c025cb52787ac33d6c2fbaa390905c6125a2b3c6afebab232bb5e4",
    ),
    (
        "bfcl_eval/constants/enums.py",
        "enums.py",
        "2182becfa2a1d071ee1db30db593b4758c6bf866aa12d2d4b8daf09175ea518a",
    ),
    (
        "bfcl_eval/constants/type_mappings.py",
        "type_mappings.py",
        "1702fb67afbe2c492608e58e2b7d02e46381f50166b47f3c952f76e34c7cd3bd",
    ),
    (
        "bfcl_eval/data/BFCL_v4_simple_python.json",
        "data/BFCL_v4_simple_python.json",
        "82dd63ba502eb2520c6b5d1d9a5c4b590e03ff261565175561f6228a367d1991",
    ),
    (
        "bfcl_eval/data/BFCL_v4_multiple.json",
        "data/BFCL_v4_multiple.json",
        "aef168155ebd74b7ac2401198b201343bc7d16d7a3d7e0d4e6d8ee82c6969b2a",
    ),
    (
        "bfcl_eval/data/BFCL_v4_parallel.json",
        "data/BFCL_v4_parallel.json",
        "19f51a82eff42e5d62541aa500115a056eb78f437c2ba1f10415fd7c8e5dda84",
    ),
    (
        "bfcl_eval/data/BFCL_v4_parallel_multiple.json",
        "data/BFCL_v4_parallel_multiple.json",
        "8863ea8433239f55c5f016154cf0830853c89f693c6ea270396a2fa121960579",
    ),
    (
        "bfcl_eval/data/possible_answer/BFCL_v4_simple_python.json",
        "data/possible_answer/BFCL_v4_simple_python.json",
        "90cd5bc653690ee8e459b5b3f3fc9458606f7f3fcbf795bb51b7dc581f8c86dc",
    ),
    (
        "bfcl_eval/data/possible_answer/BFCL_v4_multiple.json",
        "data/possible_answer/BFCL_v4_multiple.json",
        "244e00ce9395df948bcafc7bee64e8f9c87ef70887587d83cae45b13699f3047",
    ),
    (
        "bfcl_eval/data/possible_answer/BFCL_v4_parallel.json",
        "data/possible_answer/BFCL_v4_parallel.json",
        "8a6aa19c1adddc6a5a2f7e40f9dbf30cc7e95815e7b830c90589ab318229e0f0",
    ),
    (
        "bfcl_eval/data/possible_answer/BFCL_v4_parallel_multiple.json",
        "data/possible_answer/BFCL_v4_parallel_multiple.json",
        "5ebf24f458c1f16300c05505d83d6f0a1b68b79be273a033febd0d4f840507e3",
    ),
]

# sha256 of each *rendered* vendored file — the bytes actually on disk, header
# and rewrites included. This is the pin that matters: verifying only that a
# file's header quotes the right upstream hash leaves the function bodies
# unchecked, so grading logic could be edited freely and still pass CI. That
# hole was demonstrated on the IFEval tree (one line of the strict verdict
# function replaced with `if True:` moved a score from 0.1 to 1.0 while --check
# reported OK), and this tree shipped with the same flaw.
#
# Regenerate by running the script and copying the "Rendered pins" block.
RENDERED_SHA256: dict[str, str] = {
    "ast_checker.py": "7a227778b8b201b464105d342935af6d77216d074e1f76977d8e2040801e4c17",
    "type_convertor/java_type_converter.py": "7077f32e80358b5fa91364a2ec49ddd65d53bb05e164aeaa517af6a3c7e99ef4",
    "type_convertor/js_type_converter.py": "385450eb8e3942bdab65c23323dba65af172c15448808d65c9e3497c0b34a643",
    "enums.py": "6381ebe7bb116e7c0c0e442854c43a9b25851190c28a0655442bb3dc250e5019",
    "type_mappings.py": "0aabe8465de6d7d3ff487a4b5223ba78330626fcc1ce48e62e63d6cdace174ae",
    "data/BFCL_v4_simple_python.json": (
        "82dd63ba502eb2520c6b5d1d9a5c4b590e03ff261565175561f6228a367d1991"
    ),
    "data/BFCL_v4_multiple.json": (
        "aef168155ebd74b7ac2401198b201343bc7d16d7a3d7e0d4e6d8ee82c6969b2a"
    ),
    "data/BFCL_v4_parallel.json": (
        "19f51a82eff42e5d62541aa500115a056eb78f437c2ba1f10415fd7c8e5dda84"
    ),
    "data/BFCL_v4_parallel_multiple.json": (
        "8863ea8433239f55c5f016154cf0830853c89f693c6ea270396a2fa121960579"
    ),
    "data/possible_answer/BFCL_v4_simple_python.json": (
        "90cd5bc653690ee8e459b5b3f3fc9458606f7f3fcbf795bb51b7dc581f8c86dc"
    ),
    "data/possible_answer/BFCL_v4_multiple.json": (
        "244e00ce9395df948bcafc7bee64e8f9c87ef70887587d83cae45b13699f3047"
    ),
    "data/possible_answer/BFCL_v4_parallel.json": (
        "8a6aa19c1adddc6a5a2f7e40f9dbf30cc7e95815e7b830c90589ab318229e0f0"
    ),
    "data/possible_answer/BFCL_v4_parallel_multiple.json": (
        "5ebf24f458c1f16300c05505d83d6f0a1b68b79be273a033febd0d4f840507e3"
    ),
}

# The complete set of modifications applied to upstream source. Every entry is a
# claim `--check` verifies (no un-rewritten form may survive) and a divergence a
# reviewer must evaluate. The model_config line is the one SEMANTIC substitution;
# see the module docstring for why it is strictly harsher than upstream.
_REWRITES: list[tuple[str, str]] = [
    (
        "from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING",
        "from ._model_config_shim import MODEL_CONFIG_MAPPING",
    ),
    ("from bfcl_eval.constants.enums import ", "from .enums import "),
    ("from bfcl_eval.constants.type_mappings import ", "from .type_mappings import "),
    (
        "from bfcl_eval.eval_checker.ast_eval.type_convertor.java_type_converter import (",
        "from .type_convertor.java_type_converter import (",
    ),
    (
        "from bfcl_eval.eval_checker.ast_eval.type_convertor.js_type_converter import (",
        "from .type_convertor.js_type_converter import (",
    ),
]

# Applied only under type_convertor/ (their relative depth differs).
_CONVERTOR_REWRITES: list[tuple[str, str]] = [
    ("from bfcl_eval.constants.type_mappings import ", "from ..type_mappings import "),
]

_PY_HEADER = '''"""Vendored from bfcl-eval {version} (Berkeley Function Calling Leaderboard) — DO NOT EDIT.

Regenerate with ``python3 scripts/vendor_bfcl.py``; verify with ``--check``.
Upstream wheel: {url}
Upstream member sha256: {sha}
Apache License 2.0 — see the NOTICE file in this directory.

The only changes from upstream are the rewrites documented in
scripts/vendor_bfcl.py (``_REWRITES``); the ``_model_config_shim`` substitution
is the sole semantic one and is strictly harsher than upstream (no function-name
accommodation for any model). Hand-editing this file will fail
``vendor_bfcl.py --check`` in CI — the grader must not drift from the published
grader without that being visible.
"""

'''

_SHIM = '''"""NOT upstream code — the one authored substitution in this vendored tree.

Upstream's ``ast_checker`` imports ``MODEL_CONFIG_MAPPING`` (the registry of
every model on the BFCL leaderboard) from a module that transitively imports
every vendor SDK. The checker consults it on exactly one line — whether a model
is granted the ``.``→``_`` function-name accommodation that OpenAI-style APIs
need because they forbid dots in function names.

This shim answers ``underscore_to_dot = False`` for every model name: no
accommodation, the response must name the function exactly as the ground truth
does. That is strictly HARSHER than what any leaderboard model receives — it can
only turn upstream-valid answers invalid, never the reverse — so a score
produced under it never overstates against the official checker.

Verified byte-for-byte by ``scripts/vendor_bfcl.py --check`` like everything
else here; edits fail CI.
"""


class _NoAccommodation:
    underscore_to_dot = False


class _AllModels(dict):  # noqa: RUF049 - upstream indexes by arbitrary model name
    def __missing__(self, key: str) -> _NoAccommodation:
        return _NoAccommodation()


MODEL_CONFIG_MAPPING = _AllModels()
'''

_NOTICE = f"""\
Vendored third-party code and data: BFCL (Berkeley Function Calling Leaderboard)
================================================================================

Source
------
`bfcl-eval` {UPSTREAM_VERSION}, the official evaluation package of the Berkeley Function
Calling Leaderboard (Gorilla project, UC Berkeley):
  https://pypi.org/project/bfcl-eval/{UPSTREAM_VERSION}/
  https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard

Accompanying the Gorilla / BFCL work:
  "Gorilla: Large Language Model Connected with Massive APIs"
  Shishir G. Patil, Tianjun Zhang, Xin Wang, Joseph E. Gonzalez.

License
-------
Apache License, Version 2.0 (per the package's declared license).
Full text: http://www.apache.org/licenses/LICENSE-2.0

Contents
--------
  ast_checker.py             the official AST-comparison grader
  type_convertor/            java/js type converters (imported by the checker;
                             the java/js corpora are deliberately NOT vendored)
  enums.py                   Language enum
  type_mappings.py           java/js type conversion tables
  _model_config_shim.py      OURS, not upstream — see its docstring. Replaces a
                             model-registry import that would drag in every
                             vendor SDK; strictly harsher than upstream.
  data/                      the Python AST track: simple_python (400),
                             multiple (200), parallel (200),
                             parallel_multiple (200) — 1,000 instances — plus
                             the official possible_answer ground truth for each.

Provenance is pinned by the wheel's sha256 (matching PyPI's published digest)
and a sha256 per extracted member, recorded in scripts/vendor_bfcl.py.
Modifications are limited to the rewrites documented in that script and
enforced by its --check mode.

Runtime dependencies
--------------------
None beyond the standard library. The vendor-SDK-laden model registry is the
one import shimmed away (see _model_config_shim.py); tree-sitter is only needed
for grading java/js corpora, which are not vendored.
"""


def _rewrite(text: str, vendored_path: str) -> str:
    rewrites = _CONVERTOR_REWRITES if vendored_path.startswith("type_convertor/") else _REWRITES
    for old, new in rewrites:
        text = text.replace(old, new)
    return text


def _render(member: str, vendored_path: str, raw: bytes, sha: str) -> bytes:
    """Derive the vendored bytes from the wheel-member bytes. Pure function."""
    if not member.endswith(".py"):
        return raw  # data files are byte-identical
    header = _PY_HEADER.format(version=UPSTREAM_VERSION, url=WHEEL_URL, sha=sha)
    return (header + _rewrite(raw.decode("utf-8"), vendored_path)).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify the committed tree")
    args = ap.parse_args()

    if args.check:
        return _check()

    with urllib.request.urlopen(WHEEL_URL, timeout=120) as resp:
        wheel = resp.read()
    actual = hashlib.sha256(wheel).hexdigest()
    if actual != WHEEL_SHA256:
        print(
            f"wheel does not match its pin\n  pinned:  {WHEEL_SHA256}\n  fetched: {actual}\n"
            "A released wheel never changes; a mismatch means the download was "
            "tampered with or corrupted. Refusing to vendor.",
            file=sys.stderr,
        )
        return 1

    failures: list[str] = []
    rendered_pins: list[str] = []
    with zipfile.ZipFile(io.BytesIO(wheel)) as zf:
        for member, vendored_path, expected_sha in ARTIFACTS:
            raw = zf.read(member)
            member_sha = hashlib.sha256(raw).hexdigest()
            if member_sha != expected_sha:
                failures.append(
                    f"{member}: member bytes changed inside a pinned wheel (?!)\n"
                    f"  pinned: {expected_sha}\n  actual: {member_sha}"
                )
                continue
            out = VENDOR_DIR / vendored_path
            out.parent.mkdir(parents=True, exist_ok=True)
            rendered = _render(member, vendored_path, raw, member_sha)
            out.write_bytes(rendered)
            rendered_pins.append(
                f'    "{vendored_path}": "{hashlib.sha256(rendered).hexdigest()}",'
            )
            print(f"  wrote {out.relative_to(REPO)}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    (VENDOR_DIR / "_model_config_shim.py").write_text(_SHIM, encoding="utf-8")
    (VENDOR_DIR / "NOTICE").write_text(_NOTICE, encoding="utf-8")
    (VENDOR_DIR / "__init__.py").write_text(
        '"""Vendored BFCL AST checker — see NOTICE. Regenerate: scripts/vendor_bfcl.py."""\n',
        encoding="utf-8",
    )
    (VENDOR_DIR / "type_convertor" / "__init__.py").write_text("", encoding="utf-8")
    print(f"  wrote {(VENDOR_DIR / 'NOTICE').relative_to(REPO)} (+ shim, __init__)")
    print("\nRendered pins (RENDERED_SHA256):\n" + "\n".join(rendered_pins))
    return 0


def _check_artifact(vendored_path: str, sha: str) -> list[str]:
    """Problems found with one vendored artifact; empty list means intact.

    The rendered-bytes digest is the actual guarantee; the header/import checks
    below only refine the diagnosis. See ``RENDERED_SHA256`` for why checking
    the header alone was not enough.
    """
    path = VENDOR_DIR / vendored_path
    if not path.is_file():
        return [f"{vendored_path}: missing — run scripts/vendor_bfcl.py"]

    expected_rendered = RENDERED_SHA256.get(vendored_path)
    if expected_rendered is None:
        return [f"{vendored_path}: no rendered-bytes pin — refusing to vouch for it"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual == expected_rendered:
        return []

    problems = [
        f"{vendored_path}: content does not match its pinned rendered digest\n"
        f"  pinned: {expected_rendered}\n  actual: {actual}\n"
        "  The vendored checker/corpus was edited. Restore with "
        "`python3 scripts/vendor_bfcl.py`."
    ]
    if vendored_path.endswith(".py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if f"Upstream member sha256: {sha}" not in text:
            problems.append(f"  · {vendored_path}: provenance header also missing/mismatched")
        rewrites = _CONVERTOR_REWRITES if vendored_path.startswith("type_convertor/") else _REWRITES
        problems.extend(
            f"  · {vendored_path}: un-rewritten upstream import {old!r}"
            for old, _new in rewrites
            if old in text
        )
    return problems


def _check() -> int:
    """Verify the committed tree matches its pins. No network (see vendor_ifeval)."""
    problems: list[str] = []
    for _member, vendored_path, sha in ARTIFACTS:
        problems.extend(_check_artifact(vendored_path, sha))

    # The shim is ours, but it is grading-adjacent, so it is pinned exactly too:
    # a "small tweak" to it is a change to what counts as a correct answer.
    shim = VENDOR_DIR / "_model_config_shim.py"
    if not shim.is_file():
        problems.append("_model_config_shim.py: missing")
    elif shim.read_text(encoding="utf-8") != _SHIM:
        problems.append(
            "_model_config_shim.py: differs from the authored shim in scripts/vendor_bfcl.py"
        )
    for required in ("NOTICE", "__init__.py", "type_convertor/__init__.py"):
        if not (VENDOR_DIR / required).is_file():
            problems.append(f"{required}: missing")

    if problems:
        print("vendored BFCL tree does not match its pins:", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        return 1
    print(f"vendored BFCL tree OK ({len(ARTIFACTS)} artifacts + shim)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
