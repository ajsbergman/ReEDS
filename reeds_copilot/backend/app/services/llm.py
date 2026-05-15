"""Pluggable LLM service – Anthropic, OpenAI, and Google Gemini.

Each provider implements a thin adapter (5 methods) that converts between
the provider's native API format and a common internal representation.
The tool-use loop lives in the base class and is written exactly once.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are ReEDS-Copilot, an AI assistant for the Regional Energy Deployment System (ReEDS) \
model repository.

Guidelines:
- Help users understand ReEDS documentation, source code, inputs, outputs, and repository structure.
- Ground answers in retrieved local repository context when available.
- Cite file paths used as evidence (use relative paths from the repo root).
- If the answer is uncertain or the needed context is missing, say so clearly.
- Do not invent file names, variables, equations, or features.
- Prefer concise, technically useful answers.
- When a user asks about inputs or outputs, use selected file context if provided.
"""

# Extended prompt used when tools are available
TOOL_SYSTEM_PROMPT = SYSTEM_PROMPT + """\

You have tools available. Follow these rules:
- When a user asks to SEE, SHOW, or VIEW figures, plots, charts, or images: call show_figure to display actual image files. Do NOT substitute with CSV data tables.
- When a user asks about data or numbers: call read_csv_data to show real data from output files.
- When a user asks about runs or what's available: call list_runs or get_run_status.
- When a user asks about output files: call list_run_outputs.
- Prefer tool calls over answering from retrieved text context when the user is asking about a specific run's results.
- After receiving tool results, write a brief natural-language summary. Do NOT repeat individual file names — the images are already displayed to the user as attachments.
"""

# Default models per provider (used when no model override is given)
DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-1",
    "openai": "gpt-4o",
    "google": "gemini-2.5-flash",
    "nlr": "claude-sonnet-4-6",
}


class LLMProvider(abc.ABC):
    """Abstract base for LLM providers.

    Subclasses **must** implement :meth:`generate` (simple text generation).
    To support tool-use, also override the five ``_tool_*`` adapter methods
    and set ``supports_tools = True``.  The tool-use loop itself
    (:meth:`generate_with_tools`) is written once here and never duplicated.
    """

    supports_tools: bool = False

    @abc.abstractmethod
    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str: ...

    # ── Tool-use adapter interface (override in subclass) ─────────────────

    def _tool_format_definitions(self, definitions: list[dict]) -> Any:
        """Convert canonical (Anthropic-style) tool defs to provider format."""
        raise NotImplementedError

    def _tool_init_messages(
        self, user_prompt: str, context: str, system_prompt: str
    ) -> Any:
        """Build the initial message list the provider expects."""
        raise NotImplementedError

    async def _tool_call_api(
        self, messages: Any, tools: Any, *, force: bool
    ) -> Any:
        """Make one LLM API call. *force* means the model **must** call a tool."""
        raise NotImplementedError

    def _tool_extract(self, response: Any) -> tuple[list[ToolCall], str]:
        """Parse the provider response.

        Returns ``(tool_calls, text)``.  *tool_calls* may be empty if the
        model chose to answer with text only.
        """
        raise NotImplementedError

    def _tool_append_results(
        self, messages: Any, response: Any, results: list[ToolResult]
    ) -> None:
        """Mutate *messages* in-place: append the assistant turn and the
        tool-result turn in the format the provider expects.
        """
        raise NotImplementedError

    # ── Unified tool-use loop (never overridden) ──────────────────────────

    async def generate_with_tools(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
        tools: list[dict] | None = None,
        execute_tool_fn=None,
        max_rounds: int = 5,
    ) -> tuple[str, list[dict]]:
        """Run the tool-use loop.

        Returns ``(text_answer, accumulated_attachments)``.
        Falls back to :meth:`generate` when tools are unavailable.
        """
        if not self.supports_tools or not tools or not execute_tool_fn:
            answer = await self.generate(user_prompt, context, system_prompt)
            return answer, []

        messages = self._tool_init_messages(user_prompt, context, system_prompt)
        formatted_tools = self._tool_format_definitions(tools)
        all_attachments: list[dict] = []

        for _round in range(max_rounds):
            response = await self._tool_call_api(
                messages, formatted_tools, force=(_round == 0)
            )
            calls, text = self._tool_extract(response)

            if not calls:
                return text, all_attachments

            # Execute each tool call
            results: list[ToolResult] = []
            for call in calls:
                log.info("Tool call: %s(%s)", call.name, call.args)
                text_result, attachments = execute_tool_fn(call.name, call.args)
                all_attachments.extend(attachments)
                results.append(ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    content=text_result[:4000],
                ))

            self._tool_append_results(messages, response, results)

        return "I used several tools but couldn't complete the answer in time.", all_attachments


@dataclass
class ToolCall:
    """Provider-agnostic representation of a tool invocation."""
    name: str
    args: dict
    call_id: str = ""


@dataclass
class ToolResult:
    """Provider-agnostic representation of a tool execution result."""
    call_id: str
    name: str
    content: str


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    supports_tools = True

    def __init__(self, api_key: str, model: str = "claude-opus-4-1"):
        if not api_key:
            log.warning("No Anthropic API key provided – using mock responses.")
        self._api_key = api_key
        self._model = model

    def _get_client(self):
        import anthropic
        return anthropic.AsyncAnthropic(api_key=self._api_key)

    def _base_messages(self, user_prompt: str, context: str) -> list[dict]:
        messages = []
        if context:
            messages.append(
                {"role": "user", "content": f"<context>\n{context}\n</context>"}
            )
            messages.append(
                {"role": "assistant", "content": "Thank you, I have the context."}
            )
        messages.append({"role": "user", "content": user_prompt})
        return messages

    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not self._api_key:
            return _mock_response(user_prompt)

        client = self._get_client()
        messages = self._base_messages(user_prompt, context)

        response = await client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    # ── Tool adapter methods ──────────────────────────────────────────────

    def _tool_format_definitions(self, definitions: list[dict]) -> list[dict]:
        return definitions  # already in Anthropic format

    def _tool_init_messages(self, user_prompt, context, system_prompt):
        # We store (messages, system_prompt) so _tool_call_api can use both
        return (self._base_messages(user_prompt, context), system_prompt)

    async def _tool_call_api(self, messages_state, tools, *, force):
        if not self._api_key:
            raise RuntimeError("No API key")
        messages, system_prompt = messages_state
        client = self._get_client()
        tc = {"type": "any"} if force else {"type": "auto"}
        response = await client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools,
            tool_choice=tc,
        )
        return response

    def _tool_extract(self, response) -> tuple[list[ToolCall], str]:
        calls = []
        text_parts = []
        for block in response.content:
            if block.type == "tool_use":
                calls.append(ToolCall(
                    name=block.name, args=block.input, call_id=block.id
                ))
            elif block.type == "text":
                text_parts.append(block.text)
        return calls, "\n".join(text_parts)

    def _tool_append_results(self, messages_state, response, results):
        messages, _ = messages_state
        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": r.content,
            }
            for r in results
        ]
        messages.append({"role": "user", "content": tool_results})


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    supports_tools = True

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        if not api_key:
            log.warning("No OpenAI API key provided – using mock responses.")
        self._api_key = api_key
        self._model = model

    def _get_client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self._api_key)

    def _base_messages(self, user_prompt: str, context: str, system_prompt: str) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "user", "content": f"Context:\n{context}"})
            messages.append({"role": "assistant", "content": "Thank you, I have the context."})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not self._api_key:
            return _mock_response(user_prompt)

        client = self._get_client()
        messages = self._base_messages(user_prompt, context, system_prompt)

        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    # ── Tool adapter methods ──────────────────────────────────────────────

    def _tool_format_definitions(self, definitions: list[dict]) -> list[dict]:
        # Convert Anthropic format → OpenAI function-calling format
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in definitions
        ]

    def _tool_init_messages(self, user_prompt, context, system_prompt):
        return self._base_messages(user_prompt, context, system_prompt)

    async def _tool_call_api(self, messages, tools, *, force):
        if not self._api_key:
            raise RuntimeError("No API key")
        import json as _json
        client = self._get_client()
        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=4096,
            messages=messages,
            tools=tools,
        )
        if force:
            kwargs["tool_choice"] = "required"
        response = await client.chat.completions.create(**kwargs)
        return response

    def _tool_extract(self, response) -> tuple[list[ToolCall], str]:
        import json as _json
        msg = response.choices[0].message
        calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = _json.loads(tc.function.arguments) if tc.function.arguments else {}
                calls.append(ToolCall(
                    name=tc.function.name, args=args, call_id=tc.id
                ))
        return calls, msg.content or ""

    def _tool_append_results(self, messages, response, results):
        msg = response.choices[0].message
        # Append the assistant message (with tool_calls)
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)
        # Append each tool result
        for r in results:
            messages.append({
                "role": "tool",
                "tool_call_id": r.call_id,
                "content": r.content,
            })


# ── Google Gemini ─────────────────────────────────────────────────────────────

class GoogleProvider(LLMProvider):
    supports_tools = True

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        if not api_key:
            log.warning("No Google API key provided – using mock responses.")
        self._api_key = api_key
        self._model = model

    def _get_client(self):
        from google import genai
        return genai.Client(api_key=self._api_key)

    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not self._api_key:
            return _mock_response(user_prompt)

        from google.genai import types as gtypes

        client = self._get_client()
        full_prompt = ""
        if context:
            full_prompt += f"Context:\n{context}\n\n"
        full_prompt += user_prompt

        response = await client.aio.models.generate_content(
            model=self._model,
            contents=full_prompt,
            config=gtypes.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=4096,
            ),
        )
        return response.text or ""

    # ── Tool adapter methods ──────────────────────────────────────────────

    def _tool_format_definitions(self, definitions: list[dict]) -> Any:
        from google.genai import types as gtypes
        func_decls = []
        for t in definitions:
            func_decls.append(gtypes.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t.get("input_schema"),
            ))
        return [gtypes.Tool(function_declarations=func_decls)]

    def _tool_init_messages(self, user_prompt, context, system_prompt):
        from google.genai import types as gtypes
        full_prompt = ""
        if context:
            full_prompt += f"Context:\n{context}\n\n"
        full_prompt += user_prompt
        contents = [gtypes.Content(role="user", parts=[gtypes.Part.from_text(text=full_prompt)])]
        return (contents, system_prompt)

    async def _tool_call_api(self, messages_state, tools, *, force):
        if not self._api_key:
            raise RuntimeError("No API key")
        from google.genai import types as gtypes
        contents, system_prompt = messages_state
        client = self._get_client()
        mode = "ANY" if force else "AUTO"
        tool_config = gtypes.ToolConfig(
            function_calling_config=gtypes.FunctionCallingConfig(mode=mode)
        )
        response = await client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=gtypes.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=4096,
                tools=tools,
                tool_config=tool_config,
            ),
        )
        return response

    def _tool_extract(self, response) -> tuple[list[ToolCall], str]:
        candidate = response.candidates[0]
        calls = []
        text_parts = []
        for part in candidate.content.parts:
            if part.function_call:
                fc = part.function_call
                calls.append(ToolCall(
                    name=fc.name,
                    args=dict(fc.args) if fc.args else {},
                ))
            elif part.text:
                text_parts.append(part.text)
        return calls, "\n".join(text_parts)

    def _tool_append_results(self, messages_state, response, results):
        from google.genai import types as gtypes
        contents, _ = messages_state
        candidate = response.candidates[0]
        contents.append(candidate.content)
        function_response_parts = [
            gtypes.Part.from_function_response(
                name=r.name,
                response={"result": r.content},
            )
            for r in results
        ]
        contents.append(gtypes.Content(role="user", parts=function_response_parts))


# ── Mock (no API key) ────────────────────────────────────────────────────────

def _mock_response(user_prompt: str) -> str:
    return (
        "⚠️ No LLM API key is configured. This is a **mock response**.\n\n"
        f"You asked: *{user_prompt[:200]}*\n\n"
        "Please go to **Settings** and enter your API key "
        "(Anthropic, OpenAI, Google, or NLR LiteLLM) to get real answers."
    )


# ── NLR LiteLLM (OpenAI-compatible) ───────────────────────────────────────────

class NlrLitellmProvider(OpenAIProvider):
    """NLR internal LiteLLM proxy — uses the OpenAI SDK with a custom base URL."""

    NLR_BASE_URL = "https://litellm.nlr.gov"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        super().__init__(api_key, model)

    def _get_client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key=self._api_key,
            base_url=self.NLR_BASE_URL,
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def build_llm_provider(provider_name: str, api_key: str, model: str | None = None) -> LLMProvider:
    resolved_model = model or DEFAULT_MODELS.get(provider_name, "")
    providers = {
        "anthropic": lambda: AnthropicProvider(api_key, resolved_model),
        "openai": lambda: OpenAIProvider(api_key, resolved_model),
        "google": lambda: GoogleProvider(api_key, resolved_model),
        "nlr": lambda: NlrLitellmProvider(api_key, resolved_model),
    }
    factory = providers.get(provider_name)
    if factory is None:
        raise ValueError(
            f"Unknown LLM provider: {provider_name!r}. "
            f"Supported: {', '.join(providers.keys())}"
        )
    return factory()
