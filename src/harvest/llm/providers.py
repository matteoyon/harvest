"""Provider configuration models and loader."""

import os
import tomllib
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    model: str = Field(..., description="Model identifier (e.g., 'claude-sonnet-4-5', 'gpt-4o')")
    api_key: Optional[str] = Field(
        default=None, description="API key (can be empty if using env vars)"
    )
    api_base: Optional[str] = Field(default=None, description="Base URL for API calls")
    timeout: int = Field(default=300, description="Request timeout in seconds", ge=1, le=600)

    @field_validator("api_key", mode="after")
    @classmethod
    def resolve_api_key_from_env(cls, v: Optional[str], info) -> Optional[str]:
        """If api_key is empty or None, try to get it from environment variables."""
        if v and v.strip():
            return v
        return None


class AppConfig(BaseModel):
    """Application configuration with all providers."""

    default_provider: str = Field(..., description="Name of the default provider to use")
    providers: dict[str, ProviderConfig] = Field(
        ..., description="Map of provider name to configuration"
    )

    def get_provider(self, name: str) -> ProviderConfig:
        """Get provider config by name, raise KeyError if not found."""
        return self.providers[name]

    def list_providers(self) -> list[str]:
        """Return list of available provider names."""
        return list(self.providers.keys())


def load_config(path: Path) -> AppConfig:
    """
    Load configuration from TOML file.

    Args:
        path: Path to the TOML configuration file

    Returns:
        AppConfig: Parsed and validated configuration

    Raises:
        FileNotFoundError: If the config file doesn't exist
        ValueError: If the config file is malformed or validation fails
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse TOML file: {e}") from e

    # Extract default provider
    default_section = data.get("default", {})
    default_provider = default_section.get("provider")
    if not default_provider:
        raise ValueError("Missing 'default.provider' in config file")

    # Parse provider configurations
    # TOML parses [providers.anthropic] as data["providers"]["anthropic"]
    providers_section = data.get("providers", {})
    if not providers_section:
        raise ValueError("No providers configured in config file")

    providers_data = providers_section

    if default_provider not in providers_data:
        raise ValueError(
            f"Default provider '{default_provider}' not found in providers section"
        )

    # Create ProviderConfig objects
    providers = {}
    for name, config_dict in providers_data.items():
        try:
            providers[name] = ProviderConfig(**config_dict)
        except Exception as e:
            raise ValueError(f"Invalid config for provider '{name}': {e}") from e

    return AppConfig(default_provider=default_provider, providers=providers)


def get_api_key_for_provider(provider_name: str, config: ProviderConfig) -> str:
    """
    Get API key for a provider, checking config first then environment variables.

    Args:
        provider_name: Name of the provider (e.g., 'anthropic', 'openai')
        config: Provider configuration

    Returns:
        str: The API key to use

    Raises:
        ValueError: If no API key is found in config or environment
    """
    # If explicitly set in config, use it
    if config.api_key and config.api_key.strip():
        return config.api_key

    # Try environment variable
    env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "ollama": "OLLAMA_API_KEY",
        "llamacpp": "LLAMACPP_API_KEY",
    }

    env_var = env_var_map.get(provider_name, f"{provider_name.upper()}_API_KEY")
    api_key = os.getenv(env_var)

    if not api_key:
        raise ValueError(
            f"No API key found for provider '{provider_name}'. "
            f"Set it in config file or environment variable '{env_var}'"
        )

    return api_key
