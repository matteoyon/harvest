"""LLM Router with multi-provider support via LiteLLM."""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import litellm

from .providers import AppConfig, ProviderConfig, get_api_key_for_provider

# Suppress LiteLLM's verbose logging by default
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: Optional[str]
    tool_calls: Optional[list[ToolCall]]
    provider: str
    latency_ms: int
    model: str


class LLMRouter:
    """
    Routes LLM requests to different providers using LiteLLM.

    Supports hot-swapping providers without losing conversation history.
    """

    def __init__(self, config: AppConfig) -> None:
        """
        Initialize the router with application configuration.

        Args:
            config: Application configuration with provider settings
        """
        self._config = config
        self._current_provider_name = config.default_provider
        logger.info(f"LLMRouter initialized with default provider: {self._current_provider_name}")

    @property
    def current_provider(self) -> str:
        """Return the name of the currently active provider."""
        return self._current_provider_name

    def switch_provider(self, name: str) -> None:
        """
        Switch to a different provider.

        Args:
            name: Name of the provider to switch to

        Raises:
            ValueError: If the provider name is not configured
        """
        if name not in self._config.providers:
            available = ", ".join(self._config.list_providers())
            raise ValueError(
                f"Provider '{name}' not found. Available providers: {available}"
            )

        old_provider = self._current_provider_name
        self._current_provider_name = name
        logger.info(f"Switched provider: {old_provider} → {name}")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send a chat request to the current LLM provider.

        Args:
            messages: List of messages in OpenAI format
            tools: Optional list of tool definitions in OpenAI format
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            LLMResponse: The response from the LLM

        Raises:
            Exception: If the request fails after retry
        """
        provider_config = self._config.get_provider(self._current_provider_name)
        api_key = get_api_key_for_provider(self._current_provider_name, provider_config)

        # Build litellm arguments
        litellm_kwargs = {
            "model": provider_config.model,
            "messages": messages,
            "api_key": api_key,
            "timeout": provider_config.timeout,
            **kwargs,
        }

        if provider_config.api_base:
            litellm_kwargs["api_base"] = provider_config.api_base

        if tools:
            litellm_kwargs["tools"] = tools

        # Extra fields merged directly into the request body (e.g. {think: false} for Qwen3)
        if provider_config.extra_body:
            litellm_kwargs["extra_body"] = provider_config.extra_body

        # Try request with one retry
        max_attempts = 2
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                start_time = time.perf_counter()
                logger.debug(
                    f"Calling {self._current_provider_name} "
                    f"(model={provider_config.model}, attempt={attempt})"
                )

                response = await litellm.acompletion(**litellm_kwargs)

                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                # Parse response
                choice = response.choices[0]
                message = choice.message

                content = message.content if hasattr(message, "content") else None
                tool_calls_raw = message.tool_calls if hasattr(message, "tool_calls") else None

                # Convert tool calls to our format
                tool_calls = None
                if tool_calls_raw:
                    tool_calls = []
                    for tc in tool_calls_raw:
                        # Parse arguments (LiteLLM returns it as a string)
                        import json

                        args_dict = {}
                        if hasattr(tc, "function") and tc.function:
                            args_str = tc.function.arguments
                            try:
                                args_dict = json.loads(args_str) if args_str else {}
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse tool arguments: {args_str}")
                                args_dict = {"raw": args_str}

                            tc_id = (tc.id if hasattr(tc, "id") and tc.id else None) or str(uuid.uuid4())
                            tool_calls.append(
                                ToolCall(
                                    id=tc_id,
                                    name=tc.function.name,
                                    arguments=args_dict,
                                )
                            )

                logger.info(
                    f"✓ {self._current_provider_name} responded in {elapsed_ms}ms "
                    f"(model={provider_config.model})"
                )

                return LLMResponse(
                    content=content,
                    tool_calls=tool_calls,
                    provider=self._current_provider_name,
                    latency_ms=elapsed_ms,
                    model=provider_config.model,
                )

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for "
                    f"{self._current_provider_name}: {type(e).__name__}: {e}"
                )

                if attempt < max_attempts:
                    logger.info("Retrying...")
                    # Small delay before retry
                    import asyncio
                    await asyncio.sleep(1)

        # All attempts failed
        logger.error(
            f"All {max_attempts} attempts failed for provider '{self._current_provider_name}'"
        )
        raise last_error  # type: ignore
