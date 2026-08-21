"""Tests for the safe, capped, local self-improvement loop.

These exercise the ratchet logic with *stub* apply-patch callables (no LLM, no
gateway), so they're fast and deterministic: a promotion happens iff the cycle
both changed something and the test command passed, and each promotion advances
the baseline the next cycle builds on.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import maistro_rsi.local_loop as local_loop
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop
from maistro_rsi.protocols import MicroVmSandbox


def _git(cwd: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} rc={proc.returncode}: {proc.stderr.strip()}")


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "rsi@test.local")
    _git(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _make_apply(writer) -> object:
    """Wrap a sync ``writer(workspace: Path)`` as an async ApplyPatchFn."""

    async def apply(sandbox: MicroVmSandbox, workspace: str, model: str | None = None) -> None:
        writer(Path(workspace))

    return apply


def test_green_change_promotes_and_ratchets(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")

    # Each cycle appends a line — always a real change, always "healthy".
    def bump(ws: Path) -> None:
        f = ws / "value.txt"
        f.write_text(f.read_text() + "x\n", encoding="utf-8")

    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=3,
    )
    result = LocalRsiLoop(config, apply_patch=_make_apply(bump)).run()

    assert result.promotions == 3
    assert all(c.promoted for c in result.cycles)
    # Ratchet: the baseline accumulated one commit per promoted cycle.
    baseline = Path(config.work_root) / "baseline"
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=str(baseline), capture_output=True, text=True, check=True
    )
    # init + 3 RSI commits
    assert len(log.stdout.strip().splitlines()) == 4


def test_no_change_is_not_promoted(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=2,
    )
    result = LocalRsiLoop(config, apply_patch=_make_apply(lambda ws: None)).run()

    assert result.promotions == 0
    assert all(not c.changed and not c.promoted for c in result.cycles)


def test_failing_tests_block_promotion(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")

    def bump(ws: Path) -> None:
        (ws / "value.txt").write_text("broken\n", encoding="utf-8")

    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 1",  # never healthy
        work_root=str(tmp_path / "work"),
        max_cycles=2,
    )
    result = LocalRsiLoop(config, apply_patch=_make_apply(bump)).run()

    assert result.promotions == 0
    assert all(c.changed and not c.tests_passed and not c.promoted for c in result.cycles)


def test_respects_cycle_cap(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=5,
    )
    result = LocalRsiLoop(config, apply_patch=_make_apply(lambda ws: None)).run()
    assert len(result.cycles) == 5


def test_source_repo_untouched(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()

    def bump(ws: Path) -> None:
        (ws / "value.txt").write_text("changed\n", encoding="utf-8")

    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=2,
    )
    LocalRsiLoop(config, apply_patch=_make_apply(bump)).run()

    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    branches = subprocess.run(
        ["git", "branch"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout
    assert head_after == head_before  # never committed to source
    assert "rsi" not in branches  # never branched the source


class _FakeResponsesCallable:
    """Stands in for ResponsesAPICallable: records the model it was built with
    and immediately ends the turn."""

    built_models: ClassVar[list] = []

    def __init__(
        self,
        *,
        model=None,
        temperature=None,
        reasoning_effort=None,
        timeout=None,
        prompt_cache=False,
    ):
        type(self).built_models.append(model)

    def __call__(self, messages, *, tools=None, max_tokens=None):
        return {"content": "done", "stop_reason": "end_turn"}


@pytest.mark.asyncio
async def test_apply_patch_cycle_model_used_when_factory_model_unset(tmp_path, monkeypatch):
    """ApplyPatchFn's third arg (the quota-burn scheduler's per-cycle pick)
    reaches the builders LLM wiring when no explicit factory model was given."""
    import maistro_bootstrap.builders.responses_callable as rc

    _FakeResponsesCallable.built_models = []
    monkeypatch.setattr(rc, "ResponsesAPICallable", _FakeResponsesCallable)

    apply_fn = local_loop.make_builders_apply_patch("do a thing")
    await apply_fn(None, str(tmp_path), "groq/kimi-k2")

    assert _FakeResponsesCallable.built_models == ["groq/kimi-k2"]


@pytest.mark.asyncio
async def test_apply_patch_factory_model_beats_cycle_model(tmp_path, monkeypatch):
    """An explicit factory model (e.g. the CLI's --model) is a hard override."""
    import maistro_bootstrap.builders.responses_callable as rc

    _FakeResponsesCallable.built_models = []
    monkeypatch.setattr(rc, "ResponsesAPICallable", _FakeResponsesCallable)

    apply_fn = local_loop.make_builders_apply_patch("do a thing", model="cli-override")
    await apply_fn(None, str(tmp_path), "groq/kimi-k2")

    assert _FakeResponsesCallable.built_models == ["cli-override"]


# ---------------------------------------------------------------------------
# Inner tool-budget exhaustion: resume with context, never echo the sentinel
# ---------------------------------------------------------------------------


def test_resume_transcript_only_on_max_turns_with_transcript() -> None:
    transcript = [{"role": "user", "content": "task"}]
    # The one continue case: budget stop with a transcript to resume from.
    resumed = local_loop._resume_transcript({"stop_reason": "max_turns", "messages": transcript})
    assert resumed == transcript
    assert resumed is not transcript  # a copy — caller may mutate freely
    # The agent chose to finish: done, whatever else the result carries.
    assert local_loop._resume_transcript({"stop_reason": "stop", "messages": transcript}) is None
    # Budget stop but no transcript handed back (injected fakes, older
    # runners): ending the cycle beats poisoning the context.
    assert local_loop._resume_transcript({"stop_reason": "max_turns"}) is None
    assert local_loop._resume_transcript({"stop_reason": "max_turns", "messages": []}) is None


def _seed_and_pairs(n_pairs: int, result_chars: int) -> list[dict]:
    """A transcript shaped exactly as TurnRunner builds it: seed system+objective,
    then one assistant(tool_use)/user(tool_result) pair per inner turn."""
    messages: list[dict] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "objective"},
    ]
    for i in range(n_pairs):
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {}}],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * result_chars}
                ],
            }
        )
    return messages


def test_trim_for_resume_leaves_small_transcripts_untouched() -> None:
    transcript = _seed_and_pairs(3, 1_000)
    assert local_loop._trim_for_resume(list(transcript)) == transcript


def test_trim_for_resume_drops_oldest_pairs_keeps_seed_and_newest() -> None:
    # Observed live: accumulated resumes built a 45k-token prompt against the
    # local tier's 32k window and the gateway rejected the cycle. Trimming must
    # bring the resume under budget by dropping the OLDEST exchanges.
    transcript = _seed_and_pairs(12, 20_000)
    trimmed = local_loop._trim_for_resume(list(transcript))

    assert sum(len(str(m.get("content", ""))) for m in trimmed) <= local_loop._RESUME_CHAR_BUDGET
    # Seed verbatim; pair boundary intact; the newest exchange (the tool result
    # the model is about to answer) survives.
    assert trimmed[:2] == transcript[:2]
    assert trimmed[2]["role"] == "assistant"
    assert trimmed[-1]["content"][0]["tool_use_id"] == "t11"


def test_trim_for_resume_elides_a_single_monster_tool_output() -> None:
    # Sandbox _OUTPUT_CAP allows a single 1 MB tool result; pair-dropping alone
    # can't save a transcript whose LAST pair is the problem.
    transcript = _seed_and_pairs(1, 400_000)
    trimmed = local_loop._trim_for_resume(list(transcript))

    block = trimmed[-1]["content"][0]
    assert len(block["content"]) <= local_loop._RESUME_ITEM_CAP + len(local_loop._ELIDED)
    assert block["content"].endswith(local_loop._ELIDED)
    # The original transcript was not mutated in place.
    assert len(transcript[-1]["content"][0]["content"]) == 400_000


def test_trim_for_resume_elides_an_oversized_tool_use_input_in_the_newest_pair() -> None:
    """Codex review (#258): a tool_use block's OWN input (write_file/edit_file's
    content/old_string/new_string) is where the bulk lives when the newest kept
    exchange is a big write — not the tool_result. If only tool_result content
    is capped, "always keep the newest pair" can hand back a transcript still
    over budget, reproducing the very ContextWindowExceededError this trims."""
    transcript = _seed_and_pairs(1, 100)
    big_write = "x" * 400_000
    transcript[2]["content"][0]["input"] = {
        "path": "big.py",
        "content": big_write,
        "old_string": "y" * 400_000,
    }

    trimmed = local_loop._trim_for_resume(list(transcript))

    assert sum(len(str(m.get("content", ""))) for m in trimmed) <= local_loop._RESUME_CHAR_BUDGET
    shrunk_input = trimmed[2]["content"][0]["input"]
    # Inputs get their OWN marker, phrased as a historical record: appending
    # "tool output elided" to the model's own write_file arguments invited it
    # to re-issue the write with the marker embedded in real file content.
    cap = local_loop._RESUME_ITEM_CAP + len(local_loop._ELIDED_INPUT)
    assert len(shrunk_input["content"]) <= cap
    assert shrunk_input["content"].endswith(local_loop._ELIDED_INPUT)
    assert len(shrunk_input["old_string"]) <= cap
    assert shrunk_input["path"] == "big.py"  # small values pass through untouched
    # The pair is still intact — trimmed, not dropped or split.
    assert trimmed[2]["content"][0]["id"] == transcript[2]["content"][0]["id"]
    assert trimmed[3]["content"][0]["tool_use_id"] == transcript[3]["content"][0]["tool_use_id"]
    # The original transcript was not mutated in place.
    assert len(transcript[2]["content"][0]["input"]["content"]) == 400_000


class _ToolHungryResponsesCallable:
    """Fake LLM whose model always wants another tool call: every execute_turn
    exhausts TurnRunner's inner budget, so the outer loop must keep resuming."""

    calls: ClassVar[list[list[dict]]] = []

    def __init__(self, **kwargs):
        pass

    def __call__(self, messages, *, tools=None, max_tokens=None):
        type(self).calls.append([dict(m) for m in messages])
        n = len(type(self).calls)
        return {
            "content": [{"type": "tool_use", "id": f"t{n}", "name": "no_such_tool", "input": {}}],
            "stop_reason": "tool_use",
        }


@pytest.mark.asyncio
async def test_exhausted_tool_budget_resumes_with_transcript_not_sentinel(tmp_path, monkeypatch):
    """The live failure this pins: TurnRunner's "(max turns reached)" sentinel
    was echoed back as the agent's own words, so the model believed it had
    announced running out of turns and quit — every cycle logged "agent made
    no change". The next turn must instead RESUME from the real transcript."""
    import maistro_bootstrap.builders.responses_callable as rc

    _ToolHungryResponsesCallable.calls = []
    monkeypatch.setattr(rc, "ResponsesAPICallable", _ToolHungryResponsesCallable)

    apply_fn = local_loop.make_builders_apply_patch("do a thing", max_agent_turns=2)
    await apply_fn(None, str(tmp_path), "some-model")

    from maistro_bootstrap.builders.agent_loop import AgentLoopConfig

    calls = _ToolHungryResponsesCallable.calls
    # Two outer turns, each spending the full inner budget — the run kept
    # working instead of quitting early.
    inner_budget = AgentLoopConfig().max_turns
    assert len(calls) == 2 * inner_budget

    # THE invariant: the internal sentinel never reaches the model as speech.
    for call in calls:
        for message in call:
            assert "(max turns reached)" not in str(message.get("content"))

    # Outer turn 2 resumed from the FULL transcript: seed (system + task) plus
    # one assistant/tool_result pair per inner turn — not a 4-message reset
    # around a sentinel.
    resume_call = calls[inner_budget]
    assert len(resume_call) == 2 + 2 * inner_budget
    assert resume_call[0]["role"] == "system"
    assert resume_call[-1]["role"] == "user"  # unanswered tool results
    assert resume_call[-1]["content"][0]["type"] == "tool_result"


# --- _trim_for_resume: the contract as properties, not examples --------------
#
# The #258 review's exact words: "A Hypothesis property over generated
# transcripts asserting the budget postcondition would have failed on finding
# #1 immediately." Here it is, plus the structural properties the index
# arithmetic version violated.


def _message_strategy():
    text_block = st.fixed_dictionaries({"type": st.just("text"), "text": st.text(max_size=2000)})
    tool_use = st.fixed_dictionaries(
        {
            "type": st.just("tool_use"),
            "id": st.uuids().map(str),
            "name": st.sampled_from(["bash", "write_file", "edit_file"]),
            "input": st.dictionaries(
                st.sampled_from(["content", "old_string", "new_string", "path"]),
                st.text(max_size=30_000),
                max_size=3,
            ),
        }
    )
    assistant = st.fixed_dictionaries(
        {"role": st.just("assistant"), "content": st.lists(tool_use | text_block, max_size=3)}
    )
    tool_result = st.fixed_dictionaries(
        {
            "role": st.just("user"),
            "content": st.lists(
                st.fixed_dictionaries(
                    {
                        "type": st.just("tool_result"),
                        "tool_use_id": st.uuids().map(str),
                        "content": st.text(max_size=60_000),
                    }
                ),
                max_size=2,
            ),
        }
    )
    return assistant | tool_result


@st.composite
def _transcripts(draw):
    seed = [
        {"role": "system", "content": draw(st.text(max_size=3000))},
        {"role": "user", "content": draw(st.text(max_size=3000))},
    ]
    # Sometimes a THIRD seed message — the case the old [2:4] slice deleted.
    if draw(st.booleans()):
        seed.append({"role": "user", "content": draw(st.text(max_size=2000))})
    body = draw(st.lists(_message_strategy(), max_size=12))
    return seed + body


class TestTrimForResumeProperties:
    @given(transcript=_transcripts())
    @settings(max_examples=60, deadline=None)
    def test_budget_postcondition_or_none(self, transcript):
        """The one that matters: output fits the budget, or is None — never a
        silently over-budget transcript handed to the gateway."""
        trimmed = local_loop._trim_for_resume(list(transcript))
        if trimmed is not None:
            assert local_loop._chars(trimmed) <= local_loop._RESUME_CHAR_BUDGET

    @given(transcript=_transcripts())
    @settings(max_examples=60, deadline=None)
    def test_seed_survives_verbatim(self, transcript):
        """Every leading non-assistant message is seed and must not be dropped
        or rewritten — regardless of whether the seed is 2 or 3 messages."""
        seed_len = 0
        while seed_len < len(transcript) and transcript[seed_len].get("role") != "assistant":
            seed_len += 1
        trimmed = local_loop._trim_for_resume(list(transcript))
        if trimmed is not None:
            assert trimmed[:seed_len] == transcript[:seed_len]

    @given(transcript=_transcripts())
    @settings(max_examples=60, deadline=None)
    def test_no_orphan_tool_results(self, transcript):
        """A tool_result whose assistant turn was dropped is a 400 from most
        providers — turns and their results move as one unit."""
        trimmed = local_loop._trim_for_resume(list(transcript))
        if trimmed is None:
            return
        seed_len = 0
        while seed_len < len(trimmed) and trimmed[seed_len].get("role") != "assistant":
            seed_len += 1
        seen_assistant = False
        for message in trimmed[seed_len:]:
            if message.get("role") == "assistant":
                seen_assistant = True
            else:
                assert seen_assistant, "tool_result appeared before any assistant turn"

    def test_impossible_budget_returns_none_not_over_budget(self):
        """The old `len(trimmed) > 4` exit returned an over-budget transcript
        silently; the contract is now None, the same as _resume_transcript's
        other unsafe case."""
        transcript = [
            {"role": "system", "content": "s" * 200_000},
            {"role": "user", "content": "objective"},
        ]
        assert local_loop._trim_for_resume(transcript) is None

    def test_text_only_assistant_turn_does_not_split_pairs(self):
        """Interleaved text-only turns shifted the old parity arithmetic so
        del [2:4] split a real pair."""
        transcript = _seed_and_pairs(6, 20_000)
        transcript.insert(4, {"role": "assistant", "content": "thinking out loud"})
        trimmed = local_loop._trim_for_resume(list(transcript))
        assert trimmed is not None
        for i, message in enumerate(trimmed):
            if message.get("role") != "assistant" and i > 1:
                blocks = message.get("content")
                if isinstance(blocks, list) and blocks and blocks[0].get("type") == "tool_result":
                    prev = trimmed[i - 1]
                    assert prev.get("role") == "assistant", "orphaned tool_result"
