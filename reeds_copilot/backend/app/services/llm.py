"""Pluggable LLM service – Anthropic, OpenAI, and Google Gemini."""
from __future__ import annotations

import abc
import logging

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

# Default models per provider (used when no model override is given)
DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-1",
    "openai": "gpt-4o",
    "google": "gemini-2.5-pro-preview-05-06",
}


class LLMProvider(abc.ABC):
    """Abstract base for LLM providers."""

    @abc.abstractmethod
    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str: ...


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-opus-4-1"):
        if not api_key:
            log.warning("No Anthropic API key provided – using mock responses.")
        self._api_key = api_key
        self._model = model

    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not self._api_key:
            return _mock_response(user_prompt)

        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        messages = []
        if context:
            messages.append(
                {"role": "user", "content": f"<context>\n{context}\n</context>"}
            )
            messages.append(
                {"role": "assistant", "content": "Thank you, I have the context."}
            )
        messages.append({"role": "user", "content": user_prompt})

        response = await client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        if not api_key:
            log.warning("No OpenAI API key provided – using mock responses.")
        self._api_key = api_key
        self._model = model

    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not self._api_key:
            return _mock_response(user_prompt)

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "user", "content": f"Context:\n{context}"})
            messages.append({"role": "assistant", "content": "Thank you, I have the context."})
        messages.append({"role": "user", "content": user_prompt})

        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            messages=messages,
        )
        return response.choices[0].message.content or ""


# ── Google Gemini ─────────────────────────────────────────────────────────────

class GoogleProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-pro-preview-05-06"):
        if not api_key:
            log.warning("No Google API key provided – using mock responses.")
        self._api_key = api_key
        self._model = model

    async def generate(
        self,
        user_prompt: str,
        context: str = "",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not self._api_key:
            return _mock_response(user_prompt)

        from google import genai

        client = genai.Client(api_key=self._api_key)

        full_prompt = ""
        if context:
            full_prompt += f"Context:\n{context}\n\n"
        full_prompt += user_prompt

        response = await client.aio.models.generate_content(
            model=self._model,
            contents=full_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=4096,
            ),
        )
        return response.text or ""


# ── Mock (no API key) ────────────────────────────────────────────────────────

def _mock_response(user_prompt: str) -> str:
    return (
        "⚠️ No LLM API key is configured. This is a **mock response**.\n\n"
        f"You asked: *{user_prompt[:200]}*\n\n"
        "Please go to **Settings** and enter your API key "
        "(Anthropic, OpenAI, or Google) to get real answers."
    )


# ── Factory ───────────────────────────────────────────────────────────────────

def build_llm_provider(provider_name: str, api_key: str, model: str | None = None) -> LLMProvider:
    resolved_model = model or DEFAULT_MODELS.get(provider_name, "")
    providers = {
        "anthropic": lambda: AnthropicProvider(api_key, resolved_model),
        "openai": lambda: OpenAIProvider(api_key, resolved_model),
        "google": lambda: GoogleProvider(api_key, resolved_model),
    }
    factory = providers.get(provider_name)
    if factory is None:
        raise ValueError(
            f"Unknown LLM provider: {provider_name!r}. "
            f"Supported: {', '.join(providers.keys())}"
        )
    return factory()
