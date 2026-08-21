from __future__ import annotations

from typing import Any

from ..types import PipelineGenome


def build_system_prompt(genome: PipelineGenome, role: str | None = None) -> str:
    if genome.topology.nodes:
        for node in genome.topology.nodes:
            if role is None or node.role == role:
                return node.system_prompt
        return genome.topology.nodes[0].system_prompt
    return "You are a helpful AI assistant."


def build_model_config(genome: PipelineGenome, role: str | None = None) -> dict[str, Any]:
    if genome.topology.nodes:
        for node in genome.topology.nodes:
            if role is None or node.role == role:
                return {
                    "model": node.model,
                    "temperature": node.temperature,
                    "max_tokens": node.max_tokens,
                }
        node = genome.topology.nodes[0]
        return {
            "model": node.model,
            "temperature": node.temperature,
            "max_tokens": node.max_tokens,
        }
    return {"model": "default", "temperature": 0.3, "max_tokens": 4096}


def build_messages(
    system_prompt: str,
    user_message: str,
    tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    if tools:
        tool_descriptions = []
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            params = tool.get("parameters", {})
            param_str = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else ""
            tool_descriptions.append(f"- {name}({param_str}): {desc}")
        tools_block = "\nAvailable tools:\n" + "\n".join(tool_descriptions)
        messages[0]["content"] += tools_block
    messages.append({"role": "user", "content": user_message})
    return messages


def extract_tool_call(response: str) -> dict[str, Any] | None:
    import json
    import re

    patterns = [
        r"```(?:json)?\s*(\{[^{}]*\})\s*```",
        r"(\{[^{}]*\})",
    ]
    for pat in patterns:
        match = re.search(pat, response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and (
                    "name" in data or "function" in data or "action" in data
                ):
                    return data
            except (json.JSONDecodeError, ValueError):
                continue

    action_match = re.search(r"(?:call|invoke|use)\s+(\w+)\s*\(([^)]*)\)", response, re.IGNORECASE)
    if action_match:
        name = action_match.group(1)
        args_str = action_match.group(2).strip()
        args = {}
        if args_str:
            for pair in args_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    args[k.strip()] = v.strip().strip("\"'")
        return {"name": name, "parameters": args}

    return None
