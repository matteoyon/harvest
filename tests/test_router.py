"""Tests for LLM Router."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harvest.llm import AppConfig, LLMRouter, ProviderConfig, load_config


@pytest.fixture
def sample_config_dict():
    """Sample configuration dictionary."""
    return {
        "default": {"provider": "anthropic"},
        "providers.anthropic": {
            "model": "claude-sonnet-4-5",
            "api_key": "test-key-anthropic",
            "timeout": 300,
        },
        "providers.openai": {
            "model": "gpt-4o-mini",
            "api_key": "test-key-openai",
            "timeout": 300,
        },
        "providers.ollama": {
            "model": "ollama/qwen2.5:7b",
            "api_base": "http://localhost:11434",
            "api_key": "ollama",
            "timeout": 300,
        },
    }


@pytest.fixture
def sample_config_file(tmp_path, sample_config_dict):
    """Create a temporary TOML config file."""
    config_path = tmp_path / "providers.toml"

    # Convert dict to TOML format
    toml_content = "[default]\n"
    toml_content += f'provider = "{sample_config_dict["default"]["provider"]}"\n\n'

    for key, value in sample_config_dict.items():
        if key.startswith("providers."):
            provider_name = key.split(".", 1)[1]
            toml_content += f"[providers.{provider_name}]\n"
            for k, v in value.items():
                if isinstance(v, str):
                    toml_content += f'{k} = "{v}"\n'
                else:
                    toml_content += f"{k} = {v}\n"
            toml_content += "\n"

    config_path.write_text(toml_content)
    return config_path


@pytest.fixture
def app_config():
    """Create AppConfig for testing."""
    return AppConfig(
        default_provider="anthropic",
        providers={
            "anthropic": ProviderConfig(
                model="claude-sonnet-4-5", api_key="test-key-anthropic", timeout=300
            ),
            "openai": ProviderConfig(
                model="gpt-4o-mini", api_key="test-key-openai", timeout=300
            ),
            "ollama": ProviderConfig(
                model="ollama/qwen2.5:7b",
                api_base="http://localhost:11434",
                api_key="ollama",
                timeout=300,
            ),
        },
    )


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_config_from_file(self, sample_config_file):
        """Test loading configuration from TOML file."""
        config = load_config(sample_config_file)

        assert config.default_provider == "anthropic"
        assert len(config.providers) == 3
        assert "anthropic" in config.providers
        assert "openai" in config.providers
        assert "ollama" in config.providers

        anthropic_config = config.get_provider("anthropic")
        assert anthropic_config.model == "claude-sonnet-4-5"
        assert anthropic_config.api_key == "test-key-anthropic"

    def test_load_config_missing_file(self, tmp_path):
        """Test error when config file doesn't exist."""
        missing_path = tmp_path / "nonexistent.toml"
        with pytest.raises(FileNotFoundError):
            load_config(missing_path)

    def test_load_config_missing_default_provider(self, tmp_path):
        """Test error when default provider is not specified."""
        config_path = tmp_path / "invalid.toml"
        config_path.write_text("[providers.anthropic]\nmodel = 'claude-sonnet-4-5'\n")

        with pytest.raises(ValueError, match="Missing 'default.provider'"):
            load_config(config_path)

    def test_load_config_default_provider_not_in_providers(self, tmp_path):
        """Test error when default provider is not in providers section."""
        config_path = tmp_path / "invalid.toml"
        config_path.write_text(
            "[default]\nprovider = 'nonexistent'\n\n"
            "[providers.anthropic]\nmodel = 'claude-sonnet-4-5'\n"
        )

        with pytest.raises(ValueError, match="Default provider 'nonexistent' not found"):
            load_config(config_path)

    def test_list_providers(self, app_config):
        """Test listing available providers."""
        providers = app_config.list_providers()
        assert set(providers) == {"anthropic", "openai", "ollama"}


class TestLLMRouter:
    """Tests for LLM Router."""

    def test_router_initialization(self, app_config):
        """Test router initialization with default provider."""
        router = LLMRouter(app_config)
        assert router.current_provider == "anthropic"

    def test_switch_provider_valid(self, app_config):
        """Test switching to a valid provider."""
        router = LLMRouter(app_config)
        assert router.current_provider == "anthropic"

        router.switch_provider("openai")
        assert router.current_provider == "openai"

        router.switch_provider("ollama")
        assert router.current_provider == "ollama"

    def test_switch_provider_invalid(self, app_config):
        """Test error when switching to non-existent provider."""
        router = LLMRouter(app_config)

        with pytest.raises(ValueError, match="Provider 'nonexistent' not found"):
            router.switch_provider("nonexistent")

    @pytest.mark.asyncio
    async def test_chat_text_response(self, app_config):
        """Test chat with text-only response."""
        router = LLMRouter(app_config)

        # Mock response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Hello! How can I help you?"
        mock_response.choices[0].message.tool_calls = None

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.return_value = mock_response

            messages = [{"role": "user", "content": "Hello"}]
            result = await router.chat(messages)

            assert result.content == "Hello! How can I help you?"
            assert result.tool_calls is None
            assert result.provider == "anthropic"
            assert result.model == "claude-sonnet-4-5"
            assert result.latency_ms >= 0

            # Verify litellm was called correctly
            mock_completion.assert_called_once()
            call_kwargs = mock_completion.call_args[1]
            assert call_kwargs["model"] == "claude-sonnet-4-5"
            assert call_kwargs["messages"] == messages
            assert call_kwargs["api_key"] == "test-key-anthropic"

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls(self, app_config):
        """Test chat with tool calls in response."""
        router = LLMRouter(app_config)

        # Mock response with tool calls
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function = MagicMock()
        mock_tool_call.function.name = "add_track"
        mock_tool_call.function.arguments = json.dumps({"name": "Bass", "color": "#0000FF"})

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.tool_calls = [mock_tool_call]

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.return_value = mock_response

            messages = [{"role": "user", "content": "Add a bass track"}]
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "add_track",
                        "description": "Add a new track",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "color": {"type": "string"},
                            },
                        },
                    },
                }
            ]

            result = await router.chat(messages, tools=tools)

            assert result.content is None
            assert result.tool_calls is not None
            assert len(result.tool_calls) == 1

            tool_call = result.tool_calls[0]
            assert tool_call.id == "call_123"
            assert tool_call.name == "add_track"
            assert tool_call.arguments == {"name": "Bass", "color": "#0000FF"}

            # Verify tools were passed to litellm
            call_kwargs = mock_completion.call_args[1]
            assert call_kwargs["tools"] == tools

    @pytest.mark.asyncio
    async def test_chat_retry_on_error(self, app_config):
        """Test automatic retry on network error."""
        router = LLMRouter(app_config)

        # Mock response that succeeds on second attempt
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Success after retry"
        mock_response.choices[0].message.tool_calls = None

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            # First call fails, second succeeds
            mock_completion.side_effect = [
                Exception("Network error"),
                mock_response,
            ]

            messages = [{"role": "user", "content": "Test"}]
            result = await router.chat(messages)

            assert result.content == "Success after retry"
            assert mock_completion.call_count == 2

    @pytest.mark.asyncio
    async def test_chat_fails_after_retries(self, app_config):
        """Test that error is raised after all retries fail."""
        router = LLMRouter(app_config)

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            # All attempts fail
            mock_completion.side_effect = Exception("Persistent error")

            messages = [{"role": "user", "content": "Test"}]

            with pytest.raises(Exception, match="Persistent error"):
                await router.chat(messages)

            # Should have tried twice
            assert mock_completion.call_count == 2

    @pytest.mark.asyncio
    async def test_chat_with_different_providers(self, app_config):
        """Test switching providers and making calls."""
        router = LLMRouter(app_config)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].message.tool_calls = None

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.return_value = mock_response

            # Test with anthropic
            messages = [{"role": "user", "content": "Test"}]
            result = await router.chat(messages)
            assert result.provider == "anthropic"
            assert result.model == "claude-sonnet-4-5"

            # Switch to openai
            router.switch_provider("openai")
            result = await router.chat(messages)
            assert result.provider == "openai"
            assert result.model == "gpt-4o-mini"

            # Verify different models were called
            calls = mock_completion.call_args_list
            assert calls[0][1]["model"] == "claude-sonnet-4-5"
            assert calls[1][1]["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_tool_call_missing_id_gets_uuid(self, app_config):
        """Tool calls with missing/empty id should receive a generated uuid."""
        router = LLMRouter(app_config)

        mock_tool_call = MagicMock()
        mock_tool_call.id = None  # local models may omit this
        mock_tool_call.function = MagicMock()
        mock_tool_call.function.name = "play"
        mock_tool_call.function.arguments = "{}"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.tool_calls = [mock_tool_call]

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.return_value = mock_response
            result = await router.chat([{"role": "user", "content": "Play"}])

        assert result.tool_calls is not None
        tc = result.tool_calls[0]
        assert tc.id  # must be non-empty
        assert len(tc.id) == 36  # uuid4 format
