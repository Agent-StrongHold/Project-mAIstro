"""Final-stage COPY must be mode-normalized before the non-root runtime user (#2546).

Defect (#2546): Docker `COPY` preserves the host files' permission modes. A
build context checked out under a restrictive umask (e.g. 077) carries
mode-600 files into the image, so every final-stage host-context COPY lands
root-owned `-rw-------` and the non-root runtime user cannot read any of it —
`maistro_server.entrypoint` then dies in `run_migrations` with "No
'script_location' key found in configuration" because `Config()` sees no keys
in an unreadable `alembic.ini`.

The fix under test is the single normalization step the images run while
still root, before dropping privileges:

    RUN chmod -R a+rX <tree>

`a+rX` (capital X) grants read everywhere and the execute bit only where one
already exists — directories stay traversable and executables stay
executable — and never touches ownership or write bits.

Evidence this contract matches reachable production behavior, on the real
builder (2026-11-28, this repo's engine Docker family): a context whose
`alembic.ini` was mode 600 produced an image where uid 65532 got
`cat: /app/alembic.ini: Permission denied` (exit 1); the identical context
plus `RUN chmod -R a+rX /app` before `USER` produced `-rw-r--r--` and a
clean read (exit 0). Building the full images under `umask 077` stays out of
CI on cost; this module holds the contract closed statically the same way
`test_root_image_interpreter_lines.py` does.

Covered stages (the ones that COPY from the host context and then drop to a
non-root user): the engine image (`Dockerfile`), the Conductor image
(`packages/hive-conductor/Dockerfile`) and the sbx seed template
(`deploy/sbx/template/Dockerfile`). `Dockerfile.research` needs no
normalization: its final stage chowns the copied tree to the runtime user
itself (`chown -R app:app /app`), so the user can always read it.
`Dockerfile.rsi-runner`'s final stage copies only from a builder stage
(container-internal modes, not host modes) and is pinned to stay that way.

Bind-mounted files (e.g. `./init-db.sql` into the Postgres first-boot init)
cannot be fixed inside any Dockerfile — their host modes pass straight
through the mount. That half of #2546 is documented at the mount sites in
`docker-compose.yml`, `deploy/docker-compose.prod.yml` and the README
Quick-start umask note; this module pins the image-side contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Dockerfile -> the tree the normalization step must cover (every
#: host-context COPY destination of the final stage must live inside it).
NORMALIZED_STAGES: list[tuple[str, str]] = [
    ("Dockerfile", "/app"),
    ("packages/hive-conductor/Dockerfile", "/app"),
    ("deploy/sbx/template/Dockerfile", "/opt"),
]

#: Final stage copies from build stages only — no host context, no host modes
#: to normalize. Pinned so a future host COPY cannot silently reintroduce
#: the #2546 failure class here.
STAGE_COPY_ONLY_DOCKERFILE = "Dockerfile.rsi-runner"

_NORMALIZATION = re.compile(r"^RUN\s+chmod\s+-R\s+a\+rX\s+(\S+)\s*$")


def _logical_lines(text: str) -> list[str]:
    """Fold Dockerfile backslash continuations into logical lines.

    Comment lines are never continuations (Docker treats a `#` line as a
    whole comment even when it ends in a backslash), so they reset the
    fold instead of joining the next instruction.
    """
    logical: list[str] = []
    pending: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if pending:
            pending.append(stripped)
            if stripped.endswith("\\"):
                continue
            logical.append(" ".join(part.rstrip("\\").strip() for part in pending))
            pending = []
            continue
        if stripped.startswith("#"):
            logical.append(stripped)
            continue
        if stripped.endswith("\\"):
            pending.append(stripped)
            continue
        logical.append(stripped)
    if pending:  # unterminated continuation: a broken Dockerfile, fail loudly
        raise AssertionError(f"unterminated line continuation: {pending}")
    return [line for line in logical if line]


def _final_stage(lines: list[str]) -> list[str]:
    """The logical lines of the last `FROM` stage (the shipped one)."""
    starts = [i for i, line in enumerate(lines) if re.match(r"^FROM\s", line)]
    assert starts, "no FROM stage found"
    return lines[starts[-1] + 1 :]


def _stage_workdir(stage: list[str]) -> str | None:
    for line in stage:
        match = re.match(r"^WORKDIR\s+(\S+)\s*$", line)
        if match:
            return match.group(1)
    return None


def _tokens(line: str) -> list[str]:
    """Shell-word split that also strips a JSON-array form's brackets."""
    if line.startswith("["):
        return [tok.strip('"') for tok in line.strip("[]").split(",")]
    return line.split()


def _host_copies(stage: list[str], workdir: str | None) -> list[tuple[int, str]]:
    """(index, absolute destination) of final-stage host-context COPYs.

    `COPY --from=<stage-or-image>` carries build-stage or external-image
    modes, not host modes, so those are excluded.
    """
    copies: list[tuple[int, str]] = []
    for index, line in enumerate(stage):
        if not re.match(r"^COPY\s", line):
            continue
        tokens = _tokens(line.split(maxsplit=1)[1])
        if any(flag.startswith("--from=") for flag in tokens if flag.startswith("--")):
            continue
        args = [tok for tok in tokens if not tok.startswith("--")]
        assert len(args) >= 2, f"unparseable COPY: {line}"
        dest = args[-1]
        assert not dest.startswith("["), f"JSON-form COPY not handled: {line}"
        if not dest.startswith("/"):
            assert workdir is not None, f"relative COPY dest with no WORKDIR: {line}"
            dest = workdir.rstrip("/") + "/" + dest
        copies.append((index, dest.rstrip("/") or "/"))
    return copies


def _normalized_tree(stage: list[str]) -> tuple[str, int]:
    """The `RUN chmod -R a+rX <tree>` line of the stage and its index."""
    found = [
        (match.group(1).rstrip("/") or "/", i)
        for i, line in enumerate(stage)
        for match in [_NORMALIZATION.match(line)]
        if match
    ]
    assert len(found) == 1, (
        f"expected exactly one 'RUN chmod -R a+rX <tree>' normalization step "
        f"in the final stage (#2546), found {len(found)}: {found}"
    )
    return found[0]


def _assert_stage_normalized(dockerfile: str, expected_tree: str) -> str:
    """The #2546 contract for one Dockerfile's shipped stage.

    Every host-context COPY destination must sit inside the normalized tree,
    the normalization must run after the last of those COPYs (so it covers
    everything the image ships), and — where the stage drops to a non-root
    user — it must run before that drop (chmod needs root; once dropped, the
    user could not repair a 600 root-owned file even if it wanted to).
    Returns the normalized tree.
    """
    stage = _final_stage(_logical_lines((REPO_ROOT / dockerfile).read_text()))
    copies = _host_copies(stage, _stage_workdir(stage))
    dests = [dest for _, dest in copies]
    assert dests, f"{dockerfile}: final stage copies nothing from the host context"

    tree, index = _normalized_tree(stage)
    assert tree == expected_tree.rstrip("/"), (
        f"{dockerfile}: normalization covers {tree!r}, expected {expected_tree!r}"
    )
    outside = [dest for dest in dests if dest != tree and not dest.startswith(tree + "/")]
    assert not outside, (
        f"{dockerfile}: host-context COPY destinations outside the normalized "
        f"tree {tree!r}: {outside}"
    )

    last_copy = max(index for index, _ in copies)
    assert index > last_copy, (
        f"{dockerfile}: normalization (line {index}) must follow the last "
        f"host-context COPY (line {last_copy}) to cover everything shipped"
    )

    for i, line in enumerate(stage):
        match = re.match(r"^USER\s+(\S+)\s*$", line)
        if not match or match.group(1) in ("root", "0"):
            continue
        assert i > index, (
            f"{dockerfile}: non-root USER {match.group(1)!r} (line {i}) must "
            f"come after the normalization step (line {index})"
        )
    return tree


@pytest.mark.parametrize(("dockerfile", "tree"), NORMALIZED_STAGES)
def test_final_stage_normalizes_host_modes_before_nonroot_user(dockerfile: str, tree: str) -> None:
    _assert_stage_normalized(dockerfile, tree)


@pytest.mark.parametrize(("dockerfile", "tree"), NORMALIZED_STAGES)
def test_contract_fails_without_the_normalization_step(dockerfile: str, tree: str) -> None:
    """Fail-before control: strip the normalization step, the contract must fail.

    Proves the assertions above bite on the regression they name instead of
    passing for a wrong reason (e.g. a destination fixture that happens to
    match). Mutates the parsed logical lines only — the repo file is never
    touched.
    """
    lines = _logical_lines((REPO_ROOT / dockerfile).read_text())
    kept = [line for line in lines if not _NORMALIZATION.match(line)]
    assert len(kept) < len(lines), f"{dockerfile}: normalization step not found to strip"
    stage = _final_stage(kept)
    with pytest.raises(AssertionError):
        _normalized_tree(stage)


def test_rsi_runner_final_stage_takes_no_host_context() -> None:
    stage = _final_stage(_logical_lines((REPO_ROOT / STAGE_COPY_ONLY_DOCKERFILE).read_text()))
    host_copies = _host_copies(stage, _stage_workdir(stage))
    assert not host_copies, (
        f"{STAGE_COPY_ONLY_DOCKERFILE}: final stage started COPYing from the "
        f"host context ({[dest for _, dest in host_copies]}); its files would "
        f"carry host modes, so add a 'RUN chmod -R a+rX' normalization step "
        f"before its runtime user (#2546) and move the file into "
        f"NORMALIZED_STAGES"
    )
