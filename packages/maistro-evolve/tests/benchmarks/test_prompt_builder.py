from __future__ import annotations

from maistro_evolve.benchmarks.prompt_builder import (
    build_messages,
    build_model_config,
    build_system_prompt,
    extract_tool_call,
)

from .conftest import make_empty_genome, make_genome


class TestBuildSystemPrompt:
    def test_returns_node_prompt(self):
        g = make_genome(system_prompt="custom prompt")
        assert build_system_prompt(g) == "custom prompt"

    def test_matches_role(self):
        g = make_genome()
        assert build_system_prompt(g, role="queen") == "You are a helpful AI assistant."

    def test_role_not_found_falls_back_to_first_node(self):
        g = make_genome(system_prompt="first node prompt")
        assert build_system_prompt(g, role="nonexistent") == "first node prompt"

    def test_empty_topology_falls_back_to_default(self):
        g = make_empty_genome()
        assert build_system_prompt(g) == "You are a helpful AI assistant."


class TestBuildModelConfig:
    def test_returns_node_config(self):
        g = make_genome(model="claude-3", temperature=0.7, max_tokens=1024)
        cfg = build_model_config(g)
        assert cfg == {"model": "claude-3", "temperature": 0.7, "max_tokens": 1024}

    def test_matches_role(self):
        g = make_genome(model="claude-3")
        cfg = build_model_config(g, role="queen")
        assert cfg["model"] == "claude-3"

    def test_role_not_found_falls_back_to_first_node(self):
        g = make_genome(model="fallback-model")
        cfg = build_model_config(g, role="nonexistent")
        assert cfg["model"] == "fallback-model"

    def test_empty_topology_falls_back_to_default(self):
        g = make_empty_genome()
        cfg = build_model_config(g)
        assert cfg == {"model": "default", "temperature": 0.3, "max_tokens": 4096}


class TestBuildMessages:
    def test_basic_messages(self):
        messages = build_messages("system text", "user text")
        assert messages == [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "user text"},
        ]

    def test_with_tools_appends_tool_descriptions(self):
        tools = [
            {
                "name": "get_weather",
                "description": "fetch weather",
                "parameters": {"loc": "string"},
            },
            {"name": "no_desc_tool"},
        ]
        messages = build_messages("sys", "usr", tools=tools)
        assert "Available tools:" in messages[0]["content"]
        assert "get_weather(loc: string): fetch weather" in messages[0]["content"]
        assert "no_desc_tool(): " in messages[0]["content"]
        assert messages[1] == {"role": "user", "content": "usr"}

    def test_with_empty_tools_list_no_tools_block(self):
        messages = build_messages("sys", "usr", tools=[])
        assert messages[0]["content"] == "sys"


class TestExtractToolCall:
    def test_extracts_from_json_code_block(self):
        # the extraction regex `\{[^{}]*\}` can't match nested braces — use a flat payload
        response = '```json\n{"name": "get_weather", "loc": "NYC"}\n```'
        result = extract_tool_call(response)
        assert result == {"name": "get_weather", "loc": "NYC"}

    def test_extracts_bare_json_with_function_key(self):
        response = 'Sure: {"function": "lookup", "args": "none"}'
        result = extract_tool_call(response)
        assert result == {"function": "lookup", "args": "none"}

    def test_nested_json_payload_is_not_extracted(self):
        # documents the real limitation: nested braces defeat the non-nesting regex
        response = '{"name": "get_weather", "parameters": {"loc": "NYC"}}'
        assert extract_tool_call(response) is None

    def test_extracts_bare_json_with_action_key(self):
        response = '{"action": "open_file"}'
        result = extract_tool_call(response)
        assert result == {"action": "open_file"}

    def test_json_without_recognized_keys_falls_through(self):
        response = "no tool call here at all"
        assert extract_tool_call(response) is None

    def test_extracts_from_call_syntax(self):
        response = "I will call get_weather(location=NYC, unit=celsius)"
        result = extract_tool_call(response)
        assert result == {
            "name": "get_weather",
            "parameters": {"location": "NYC", "unit": "celsius"},
        }

    def test_call_syntax_no_args(self):
        response = "invoke refresh()"
        result = extract_tool_call(response)
        assert result == {"name": "refresh", "parameters": {}}

    def test_invalid_json_in_block_falls_through_to_call_syntax(self):
        response = "```json\n{not valid json}\n```\nuse get_data(id=42)"
        result = extract_tool_call(response)
        assert result == {"name": "get_data", "parameters": {"id": "42"}}

    def test_no_match_returns_none(self):
        assert extract_tool_call("just plain text, nothing useful") is None
