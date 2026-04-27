"""Tool registry – single-source-of-truth for tool definitions and executors.

Usage::

    from app.services.tool_registry import registry, tool

    @tool(
        description="Find and display figures from a run's outputs.",
        parameters={
            "run_name": {"type": "string", "description": "Name of the run folder."},
            "figure_name": {"type": "string", "description": "Keyword to match."},
        },
        required=["run_name", "figure_name"],
    )
    def show_figure(repo_root: Path, run_name: str, figure_name: str):
        ...
        return text, attachments
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

ToolFn = Callable[..., tuple[str, list[dict]]]


@dataclass(frozen=True)
class ToolSpec:
    """Immutable specification for a single tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str]
    executor: ToolFn


class ToolRegistry:
    """Central registry that holds every available tool."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ── registration ──────────────────────────────────────────────────────

    def register(
        self,
        *,
        description: str,
        parameters: dict[str, Any] | None = None,
        required: list[str] | None = None,
    ) -> Callable[[ToolFn], ToolFn]:
        """Decorator that registers a tool executor together with its schema."""

        def decorator(fn: ToolFn) -> ToolFn:
            name = fn.__name__
            if name in self._tools:
                raise ValueError(f"Tool '{name}' is already registered.")
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                parameters=parameters or {},
                required=required or [],
                executor=fn,
            )
            return fn

        return decorator

    # ── queries ───────────────────────────────────────────────────────────

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def __len__(self) -> int:
        return len(self._tools)

    # ── export formats ────────────────────────────────────────────────────

    def to_anthropic(self) -> list[dict]:
        """Anthropic / canonical tool definitions."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": t.required,
                },
            }
            for t in self._tools.values()
        ]

    def to_openai(self) -> list[dict]:
        """OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": t.parameters,
                        "required": t.required,
                    },
                },
            }
            for t in self._tools.values()
        ]

    def to_gemini(self):
        """Google Gemini FunctionDeclaration list (returns raw dicts; caller wraps in types.Tool)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": t.required,
                },
            }
            for t in self._tools.values()
        ]

    def to_mcp(self) -> list[dict]:
        """MCP tools/list format (JSON-Schema based, ready for future MCP server)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": {
                    "type": "object",
                    "properties": t.parameters,
                    "required": t.required,
                },
            }
            for t in self._tools.values()
        ]

    # ── execution ─────────────────────────────────────────────────────────

    def execute(self, repo_root: Path, tool_name: str, tool_input: dict) -> tuple[str, list[dict]]:
        """Execute a tool by name. Returns (text_result, attachments)."""
        spec = self._tools.get(tool_name)
        if not spec:
            return f"Unknown tool: {tool_name}", []
        try:
            return spec.executor(repo_root, **tool_input)
        except Exception as exc:
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return f"Tool error: {exc}", []


# Module-level singleton
registry = ToolRegistry()

# Convenience alias
tool = registry.register
