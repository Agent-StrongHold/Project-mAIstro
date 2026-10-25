#!/usr/bin/env python3
"""Vendor the official IFEval dataset and verifier into the repo, reproducibly.

Why vendor rather than fetch at runtime
---------------------------------------
The IFEval corpus is *the exam* the RSI loop is scored against, and the verifier
is the *grader*. Both belong in git, for three reasons:

1. **Containment.** Anything under ``maistro_evolve/benchmarks/`` is on
   ``SENSITIVE_PATH_PATTERNS``, so a candidate diff that edits its own exam or
   grader is escalated to adversarial review. A runtime download is outside that
   surface entirely — the loop could repoint a URL and nothing would notice.
2. **Reproducibility.** A score is only comparable across cycles if the exam is
   byte-identical across cycles. ``master`` moves; a committed file does not.
3. **The scoring container is network-denied** (or should be). Fetching at score
   time contradicts that directly.

Why a script rather than a hand-copied tree
-------------------------------------------
Vendoring by hand produces ~1,900 lines a reviewer has to trust. This script
makes the transform mechanical and checkable: ``--check`` re-derives the vendored
tree from the pinned bytes and fails if what is committed differs. So the review
question shrinks from "did Claude transcribe 1,900 lines of Google code
faithfully?" to "is this 40-line transform correct?".

The only modification to upstream source is the import rewrite listed in
``_REWRITES`` — ``from instruction_following_eval import X`` becomes
``from . import X``, because the vendored copy is a package-relative subpackage.
Nothing else is touched. ``--check`` is what enforces that claim.

Provenance is pinned by **sha256 of the exact bytes**, not by git commit: the
GitHub commits API is not reachable from the build environment, and a content
hash is a stronger identifier anyway. If upstream changes, the fetch fails
closed with a diff of expected vs. actual — it does not silently vendor new
bytes.

Usage
-----
    python3 scripts/vendor_ifeval.py            # fetch + write the vendored tree
    python3 scripts/vendor_ifeval.py --check    # verify the committed tree (no network)
    python3 scripts/vendor_ifeval.py --update-hashes   # re-pin after a deliberate bump
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
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
    / "ifeval"
)

_BASE = (
    "https://raw.githubusercontent.com/google-research/google-research/"
    "master/instruction_following_eval"
)

# (upstream path, vendored path, pinned sha256 of the upstream bytes)
ARTIFACTS: list[tuple[str, str, str]] = [
    (
        "instructions.py",
        "instructions.py",
        "60e086f5342a03ce8e18b64bbcccf86308f523c08aa826707a562150a52f3edf",
    ),
    (
        "instructions_registry.py",
        "instructions_registry.py",
        "ec92d72c264f6d906978613085db262356174300370a3fffe6fefd5969ce9cfc",
    ),
    (
        "instructions_util.py",
        "instructions_util.py",
        "a73797261eee5bf447e279d82a2b700b1bdd3cb1193412dbab1270a85832bc6b",
    ),
    (
        "evaluation_lib.py",
        "evaluation_lib.py",
        "35decc06000718487f44d7deafa6d3f48a8ec0886281edf40162c0265b7d248c",
    ),
    (
        "data/input_data.jsonl",
        "data/input_data.jsonl",
        "67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49",
    ),
]

# sha256 of each *rendered* vendored file — the bytes actually on disk, header
# and rewrites included. Data files are byte-identical to upstream so their
# entry equals the upstream pin; source files differ by the provenance header.
#
# This is the pin that matters, and its absence was a real hole: the first
# version of `--check` verified only that a file's header quoted the right
# upstream hash and that no un-rewritten import survived. Neither touches the
# function bodies, so editing the grader's logic passed CI. Demonstrated, not
# theorised: replacing one line of `test_instruction_following_strict` with
# `if True:` moved a lazy model's IFEval score from 0.1 to 1.0 while
# `vendor_ifeval.py --check` still printed "vendored IFEval tree OK".
#
# Regenerate with `--update-hashes` after a deliberate upstream bump.
RENDERED_SHA256: dict[str, str] = {
    "instructions.py": "038b0d9b7b2c74341d477113de63513d1f2090abe6e437e444a88df7b8af11e1",
    "instructions_registry.py": "f1d7a33a7f5aceae06a693b022ab81a8c9a320c0b41ec5bf0375e6970214bb9a",
    "instructions_util.py": "975f7de82f9002374a2a592e057ea8e29bdc7e995211abe3196095237521acca",
    "evaluation_lib.py": "7a1c3806f42a702e936381d8056b6515f80b2ab4a6d330d25f4d1a55d5182361",
    "data/input_data.jsonl": "67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49",
}

# The complete set of modifications applied to upstream source. Keep this list
# minimal and mechanical — every entry is a claim `--check` has to be able to
# verify, and every entry is a divergence a reviewer has to evaluate.
_REWRITES: list[tuple[str, str]] = [
    ("from instruction_following_eval import ", "from . import "),
]

_PY_HEADER = '''"""Vendored from google-research/instruction_following_eval — DO NOT EDIT.

Regenerate with ``python3 scripts/vendor_ifeval.py``; verify with ``--check``.
Upstream: {url}
Upstream sha256: {sha}
Apache License 2.0 — see the NOTICE file in this directory.

The only change from upstream is the import rewrite documented in
scripts/vendor_ifeval.py (``_REWRITES``). Hand-editing this file will fail
``vendor_ifeval.py --check`` in CI, which is the point: the grader must not
drift from the published grader without that being visible.
"""

'''

_NOTICE = """\
Vendored third-party code and data: IFEval
=========================================

Source
------
Google Research, `instruction_following_eval`
  https://github.com/google-research/google-research/tree/master/instruction_following_eval

Accompanying the paper:
  "Instruction-Following Evaluation for Large Language Models"
  Jeffrey Zhou, Tianjian Lu, Swaroop Mishra, Siddhartha Brahma, Sujoy Basu,
  Yi Luan, Denny Zhou, Le Hou. arXiv:2311.07911.

License
-------
Apache License, Version 2.0. Copyright The Google Research Authors.
Full text: http://www.apache.org/licenses/LICENSE-2.0
Each vendored .py file retains its original Apache 2.0 header.

This repository (maistro-engine) is also Apache 2.0, so no license
compatibility work is required. Attribution is preserved above and in the
per-file headers.

Contents
--------
  instructions.py           the 25 instruction verifiers
  instructions_registry.py  instruction_id -> verifier class mapping
  instructions_util.py       word/sentence tokenization helpers
  evaluation_lib.py         strict and loose verdict functions
  data/input_data.jsonl     the official 541-prompt corpus

Provenance is pinned by sha256 of the exact upstream bytes, recorded in
scripts/vendor_ifeval.py. Modifications are limited to the import rewrite
documented in that script and enforced by its --check mode.

Runtime dependencies
--------------------
The vendored verifier requires absl-py, immutabledict, nltk and langdetect,
declared as the `ifeval` extra of maistro-evolve. nltk additionally needs the
`punkt` tokenizer data, which must be pre-fetched (the scoring container is
network-denied by design):

    python3 -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab')"

Why these are not shimmed away: the nltk word tokenizer is trivially
replaceable (RegexpTokenizer(r"\\w+") == re.findall(r"\\w+")), but the punkt
*sentence* tokenizer and langdetect are not — substituting them would change
verdicts on `length_constraints:number_sentences` (52 prompts) and
`language:response_language` (31 prompts). A grader that is only approximately
the official grader must not be labelled `real`, so the real dependencies are
required instead.
"""


def _fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{_BASE}/{path}", timeout=60) as resp:
        data: bytes = resp.read()
    return data


def _rewrite(text: str) -> str:
    for old, new in _REWRITES:
        text = text.replace(old, new)
    return text


def _render(upstream_path: str, raw: bytes, sha: str) -> bytes:
    """Derive the vendored bytes from the upstream bytes. Pure function."""
    if not upstream_path.endswith(".py"):
        return raw  # data files are byte-identical
    text = raw.decode("utf-8")
    header = _PY_HEADER.format(url=f"{_BASE}/{upstream_path}", sha=sha)
    # The header goes after upstream's Apache block so the license stays first.
    lines = text.split("\n")
    cut = 0
    for i, line in enumerate(lines):
        if line.startswith("#"):
            cut = i + 1
        elif line.strip() == "":
            continue
        else:
            break
    license_block = "\n".join(lines[:cut]) + "\n\n"
    body = "\n".join(lines[cut:]).lstrip("\n")
    return (license_block + header + _rewrite(body)).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify the committed tree")
    ap.add_argument("--update-hashes", action="store_true", help="re-pin after a bump")
    args = ap.parse_args()

    if args.check:
        return _check()

    failures: list[str] = []
    pins: list[str] = []
    rendered_pins: list[str] = []
    for upstream_path, vendored_path, expected_sha in ARTIFACTS:
        raw = _fetch(upstream_path)
        actual = hashlib.sha256(raw).hexdigest()
        pins.append(f"    {upstream_path}: {actual}")
        if args.update_hashes:
            print(f"  {upstream_path}\n    pinned:  {expected_sha}\n    fetched: {actual}")
        elif actual != expected_sha:
            failures.append(
                f"{upstream_path}: upstream bytes changed\n"
                f"  pinned:  {expected_sha}\n  fetched: {actual}\n"
                "  Upstream moved. Review the diff, then re-pin with --update-hashes."
            )
            continue
        out = VENDOR_DIR / vendored_path
        out.parent.mkdir(parents=True, exist_ok=True)
        rendered = _render(upstream_path, raw, actual)
        out.write_bytes(rendered)
        rendered_sha = hashlib.sha256(rendered).hexdigest()
        rendered_pins.append(f'    "{vendored_path}": "{rendered_sha}",')
        # Catches header-template drift: if the template changes, every rendered
        # digest moves and RENDERED_SHA256 must be re-pinned in the same commit,
        # or CI would fail on a tree this script itself just produced.
        if not args.update_hashes and RENDERED_SHA256.get(vendored_path) != rendered_sha:
            failures.append(
                f"{vendored_path}: rendered output does not match RENDERED_SHA256\n"
                f"  pinned:   {RENDERED_SHA256.get(vendored_path)}\n"
                f"  produced: {rendered_sha}\n"
                "  The render template changed. Re-pin with --update-hashes."
            )
        print(f"  wrote {out.relative_to(REPO)}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    (VENDOR_DIR / "NOTICE").write_text(_NOTICE, encoding="utf-8")
    (VENDOR_DIR / "__init__.py").write_text(
        '"""Vendored IFEval verifier — see NOTICE. Regenerate: scripts/vendor_ifeval.py."""\n',
        encoding="utf-8",
    )
    print(f"  wrote {(VENDOR_DIR / 'NOTICE').relative_to(REPO)}")
    if args.update_hashes:
        print("\nUpstream pins (ARTIFACTS):\n" + "\n".join(pins))
        print("\nRendered pins (RENDERED_SHA256):\n" + "\n".join(rendered_pins))
    return 0


def _check_artifact(vendored_path: str, sha: str) -> list[str]:
    """Problems found with one vendored artifact; empty list means it is intact.

    The rendered-bytes digest is the actual guarantee. The header/import checks
    below it are kept only because they turn "digest mismatch" into a specific
    diagnosis when the cause is a stale regeneration rather than an edit.
    """
    path = VENDOR_DIR / vendored_path
    if not path.is_file():
        return [f"{vendored_path}: missing — run scripts/vendor_ifeval.py"]

    expected_rendered = RENDERED_SHA256.get(vendored_path)
    if expected_rendered is None:
        return [f"{vendored_path}: no rendered-bytes pin — refusing to vouch for it"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual == expected_rendered:
        return []

    problems = [
        f"{vendored_path}: content does not match its pinned rendered digest\n"
        f"  pinned: {expected_rendered}\n  actual: {actual}\n"
        "  The vendored grader/corpus was edited. Restore with "
        "`python3 scripts/vendor_ifeval.py`, or re-pin with --update-hashes "
        "if this is a deliberate upstream bump."
    ]
    if vendored_path.endswith(".py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if f"Upstream sha256: {sha}" not in text:
            problems.append(f"  · {vendored_path}: provenance header also missing/mismatched")
        problems.extend(
            f"  · {vendored_path}: un-rewritten upstream import {old!r}"
            for old, _new in _REWRITES
            if old in text
        )
    return problems


def _check() -> int:
    """Verify the committed tree is byte-identical to what the pins derive to.

    No network: CI may be offline and upstream may have moved, so this compares
    the files on disk against ``RENDERED_SHA256`` — the digest of the exact
    bytes this script produces from the pinned upstream bytes. Any edit to the
    grader, the corpus, or the provenance header fails.
    """
    pinned = {v: sha for _u, v, sha in ARTIFACTS}
    problems: list[str] = []
    for vendored_path, sha in pinned.items():
        problems.extend(_check_artifact(vendored_path, sha))
    for required in ("NOTICE", "__init__.py"):
        if not (VENDOR_DIR / required).is_file():
            problems.append(f"{required}: missing")

    if problems:
        print("vendored IFEval tree does not match its pins:", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        return 1
    print(f"vendored IFEval tree OK ({len(pinned)} artifacts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
