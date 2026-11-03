---
inventory-delta:
  tests/: +3
---
# #290 repair: the image-pins gate understands Dockerfile heredocs

The #290 shipped-image Dockerfile gained a BuildKit heredoc smoke test
(`RUN python - <<'PY' ... PY`, exercising the production cron dialect against
the image's own timezone database). The image-pins gate (#349) parsed that
body as Dockerfile grammar: `FROM_RE` is case-insensitive, so the Python lines
`from datetime import UTC, datetime` and
`from maistro.scheduling.cron import parse_cron` matched as
`FROM datetime` / `FROM maistro.scheduling.cron` — two phantom "mutable image
references" that failed `Quality / Image pins` on every run of the tree.

## The fix (no test identity reused; +3)

`scripts/check-image-pins.py` now tracks BuildKit heredoc bodies:
an instruction line containing `<<[-]?['"]?DELIM['"]?` opens a body that is
skipped wholesale until a (for `<<-`, tab-tolerant) line equal to `DELIM`.
Skipping is semantically correct, not a gate loosening: Docker never parses
Dockerfile grammar inside a heredoc body, so a `FROM` line there is command
data with no image-reference effect, while every real `FROM`/`COPY --from`
before and after the body is judged exactly as before.

Three tests pin the parser's contract in `tests/test_check_image_pins.py`:

- `test_heredoc_body_is_command_data_not_dockerfile_grammar` — the exact #290
  shape passes with zero violations (regression named in the docstring);
- `test_unpinned_from_after_a_heredoc_is_still_caught` — the degenerate path:
  the gate stays closed behind a body (an unpinned `FROM` after it still
  fails with the same message as before heredocs existed);
- `test_dashed_heredoc_terminates_on_tab_indented_delimiter` — `<<-SH` with a
  tab-indented delimiter closes the body instead of swallowing the rest of
  the Dockerfile.

## Evidence

- `uv run python scripts/check-image-pins.py` — exit 0, "9 pinned base/tool
  image(s) across 10 Dockerfile(s), all registered in image-pins.json"
  (before the fix: 2 violations naming Dockerfile lines 271–272).
- `uv run pytest tests/test_check_image_pins.py -q` — 41 passed (38 prior +
  3 new).
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
