"""ModelProvider implementations for OpenAI and Anthropic APIs."""

from __future__ import annotations

import os
from typing import Any

from agents import Model, ModelProvider
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from auto_bench.config.schema import LLMConfig


class AutoBenchModelProvider(ModelProvider):
    """ModelProvider that supports custom OpenAI-compatible API endpoints.

    Wraps an AsyncOpenAI client with a configurable base_url,
    allowing use of any OpenAI-compatible API (e.g. vLLM, Ollama,
    LM Studio, Azure OpenAI, or proprietary proxies).
    """

    def __init__(
        self, openai_client: AsyncOpenAI, default_model: str
    ) -> None:
        self._client = openai_client
        self._default_model = default_model

    def get_model(self, model_name: str | None) -> Model:
        name = model_name or self._default_model
        return OpenAIChatCompletionsModel(
            model=name,
            openai_client=self._client,
        )


class AnthropicModelProvider(ModelProvider):
    """ModelProvider for the Anthropic Messages API.

    Wraps an AsyncAnthropic client and returns AnthropicModel
    instances that translate between the openai-agents framework
    format and Anthropic's native API.
    """

    def __init__(
        self,
        anthropic_client: Any,
        default_model: str,
    ) -> None:
        self._client = anthropic_client
        self._default_model = default_model

    def get_model(self, model_name: str | None) -> Model:
        from auto_bench.agent.anthropic_model import AnthropicModel

        name = model_name or self._default_model
        return AnthropicModel(
            model=name,
            anthropic_client=self._client,
        )


def create_model_provider(
    config: LLMConfig,
) -> AutoBenchModelProvider | AnthropicModelProvider:
    """Create a ModelProvider from LLM config.

    For ``provider="openai"`` (default):
        Resolution order for credentials:
            api_key:  config.api_key -> OPENAI_API_KEY env var
            base_url: config.api_base -> OPENAI_BASE_URL env var
                      -> default OpenAI endpoint

    For ``provider="anthropic"``:
        Resolution order for credentials:
            api_key:  config.api_key -> ANTHROPIC_API_KEY env var
            base_url: config.api_base -> (default Anthropic endpoint)
    """
    if config.provider == "anthropic":
        return _create_anthropic_provider(config)
    return _create_openai_provider(config)


def _create_openai_provider(config: LLMConfig) -> AutoBenchModelProvider:
    api_key = config.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "No API key found. "
            "Set llm.api_key in config or OPENAI_API_KEY env var."
        )

    base_url = config.api_base or os.getenv("OPENAI_BASE_URL")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    return AutoBenchModelProvider(
        openai_client=client, default_model=config.model
    )


def _create_anthropic_provider(
    config: LLMConfig,
) -> AnthropicModelProvider:
    from anthropic import AsyncAnthropic

    api_key = config.api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "No API key found. "
            "Set llm.api_key in config or ANTHROPIC_API_KEY env var."
        )

    kwargs: dict = {"api_key": api_key}
    if config.api_base:
        kwargs["base_url"] = config.api_base

    client = AsyncAnthropic(**kwargs)

    return AnthropicModelProvider(
        anthropic_client=client, default_model=config.model
    )
