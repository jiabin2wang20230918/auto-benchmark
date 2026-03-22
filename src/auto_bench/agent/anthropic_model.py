"""AnthropicModel — agents.Model implementation using the Anthropic SDK.

Converts between the openai-agents framework's internal format
(TResponseInputItem / TResponseOutputItem) and the Anthropic Messages API.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from agents import ModelResponse, Usage
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.model_settings import ModelSettings
from agents.models.chatcmpl_converter import Converter
from agents.models.interface import Model, ModelTracing
from agents.tool import Tool
from agents.tracing import generation_span
from anthropic import AsyncAnthropic
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

logger = logging.getLogger(__name__)

# Sentinel for parameters that should be omitted.
_OMIT = object()


class AnthropicModel(Model):
    """Model that calls the Anthropic Messages API directly.

    Accepts the same ``system_instructions``, ``input`` and ``tools``
    that the openai-agents ``Runner`` passes to every ``Model``, but
    translates them into Anthropic's native format before calling the
    API and translates the response back.
    """

    def __init__(
        self,
        model: str,
        anthropic_client: AsyncAnthropic,
    ) -> None:
        self.model = model
        self._client = anthropic_client

    # ----------------------------------------------------------
    # Model interface
    # ----------------------------------------------------------

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any | None = None,
    ) -> ModelResponse:
        with generation_span(
            model=self.model,
            model_config=model_settings.to_json_dict(),
            disabled=tracing.is_disabled(),
        ) as span:
            messages = self._convert_input(input)
            anthropic_tools = self._convert_tools(tools, handoffs)

            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": model_settings.max_tokens or 16000,
                "messages": messages,
            }
            if system_instructions:
                kwargs["system"] = system_instructions
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools
            if model_settings.temperature is not None:
                kwargs["temperature"] = model_settings.temperature

            if tracing.include_data():
                span.span_data.input = messages

            response = await self._client.messages.create(**kwargs)

            # Convert Anthropic response → ChatCompletionMessage
            # so we can reuse the framework's converter.
            chat_msg = self._response_to_chat_message(response)

            usage = Usage(
                requests=1,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=(
                    response.usage.input_tokens
                    + response.usage.output_tokens
                ),
            )

            if tracing.include_data():
                span.span_data.output = [chat_msg.model_dump()]
            span.span_data.usage = {
                "requests": 1,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            }

            provider_data = {"model": self.model}
            items = Converter.message_to_output_items(
                chat_msg, provider_data=provider_data
            )

            return ModelResponse(
                output=items,
                usage=usage,
                response_id=response.id,
            )

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any | None = None,
    ) -> AsyncIterator[Any]:
        raise NotImplementedError(
            "Streaming is not yet supported for AnthropicModel"
        )

    # ----------------------------------------------------------
    # Input conversion: openai-agents format → Anthropic format
    # ----------------------------------------------------------

    def _convert_input(
        self, input: str | list[Any]
    ) -> list[dict[str, Any]]:
        """Convert openai-agents input items to Anthropic messages."""
        # First convert to OpenAI chat completion messages
        # using the SDK's built-in converter.
        chat_messages = Converter.items_to_messages(input)

        anthropic_messages: list[dict[str, Any]] = []
        for msg in chat_messages:
            role = msg.get("role", "user")
            # Anthropic only accepts "user" and "assistant" roles.
            # System is handled separately; tool messages become user
            # messages with tool_result content blocks.
            if role == "system":
                # Skip — system is passed separately.
                continue
            elif role == "tool":
                # Tool result → user message with tool_result block.
                anthropic_messages.append(
                    self._convert_tool_result(msg)
                )
            elif role == "assistant":
                anthropic_messages.append(
                    self._convert_assistant_message(msg)
                )
            else:
                # user / developer
                anthropic_messages.append(
                    self._convert_user_message(msg)
                )

        # Anthropic requires messages to alternate user/assistant.
        # Merge consecutive messages with the same role.
        return self._merge_consecutive_roles(anthropic_messages)

    @staticmethod
    def _convert_user_message(msg: dict) -> dict[str, Any]:
        content = msg.get("content", "")
        if isinstance(content, str):
            return {"role": "user", "content": content}
        # Content is a list of parts (multimodal).
        blocks: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, str):
                blocks.append({"type": "text", "text": part})
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    blocks.append(
                        {"type": "text", "text": part.get("text", "")}
                    )
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        # data URI → Anthropic base64 source
                        media_type, _, b64 = url.partition(";base64,")
                        media_type = media_type.replace("data:", "")
                        blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        })
                    else:
                        blocks.append({
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": url,
                            },
                        })
        return {"role": "user", "content": blocks or content}

    @staticmethod
    def _convert_assistant_message(msg: dict) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        content = msg.get("content")
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    blocks.append(
                        {"type": "text", "text": part.get("text", "")}
                    )

        # Tool calls → tool_use blocks.
        for tc in msg.get("tool_calls", []) or []:
            fn = tc if isinstance(tc, dict) else tc
            func = fn.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            blocks.append({
                "type": "tool_use",
                "id": fn.get("id", str(uuid.uuid4())),
                "name": func.get("name", ""),
                "input": args,
            })

        return {
            "role": "assistant",
            "content": blocks or [{"type": "text", "text": ""}],
        }

    @staticmethod
    def _convert_tool_result(msg: dict) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": str(msg.get("content", "")),
                }
            ],
        }

    @staticmethod
    def _merge_consecutive_roles(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge consecutive messages with the same role.

        Anthropic requires strictly alternating user/assistant turns.
        """
        if not messages:
            return messages

        merged: list[dict[str, Any]] = [messages[0]]
        for msg in messages[1:]:
            if msg["role"] == merged[-1]["role"]:
                prev = merged[-1]
                # Merge content.
                prev_content = prev.get("content", "")
                cur_content = msg.get("content", "")
                if isinstance(prev_content, str):
                    prev_content = [
                        {"type": "text", "text": prev_content}
                    ]
                if isinstance(cur_content, str):
                    cur_content = [
                        {"type": "text", "text": cur_content}
                    ]
                prev["content"] = prev_content + cur_content
            else:
                merged.append(msg)
        return merged

    # ----------------------------------------------------------
    # Tool conversion
    # ----------------------------------------------------------

    @staticmethod
    def _convert_tools(
        tools: list[Tool], handoffs: list[Handoff]
    ) -> list[dict[str, Any]]:
        """Convert openai-agents Tool objects to Anthropic tool dicts."""
        result: list[dict[str, Any]] = []
        # Use the framework's converter to get OpenAI tool schemas,
        # then translate to Anthropic format.
        for tool in tools:
            oai = Converter.tool_to_openai(tool)
            func = oai.get("function", {})
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            })
        for handoff in handoffs:
            oai = Converter.convert_handoff_tool(handoff)
            func = oai.get("function", {})
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            })
        return result

    # ----------------------------------------------------------
    # Response conversion: Anthropic → ChatCompletionMessage
    # ----------------------------------------------------------

    @staticmethod
    def _response_to_chat_message(
        response: Any,
    ) -> ChatCompletionMessage:
        """Convert Anthropic Message to a ChatCompletionMessage.

        This lets us reuse the framework's
        ``Converter.message_to_output_items`` without reimplementing
        the full output-item creation logic.
        """
        text_parts: list[str] = []
        tool_calls: list[ChatCompletionMessageToolCall] = []

        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(block.text)
            elif block_type == "tool_use":
                tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=block.id,
                        type="function",
                        function=Function(
                            name=block.name,
                            arguments=json.dumps(block.input),
                        ),
                    )
                )

        return ChatCompletionMessage(
            role="assistant",
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls or None,
        )
