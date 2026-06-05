#!/usr/bin/env python3
"""Manual test script for LLM Router."""

import asyncio
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console
from rich.table import Table

from harvest.llm import LLMRouter, load_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

console = Console()


async def test_with_mock():
    """Test router with mocked LLM responses."""
    console.print("\n[bold cyan]Testing LLM Router with mocked responses[/bold cyan]\n")

    # Load config
    config_path = Path("config/providers.example.toml")
    console.print(f"Loading config from: {config_path}")
    config = load_config(config_path)

    # Display available providers
    table = Table(title="Available Providers")
    table.add_column("Name", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("API Base", style="yellow")

    for name, provider in config.providers.items():
        table.add_row(
            name,
            provider.model,
            provider.api_base or "default"
        )

    console.print(table)
    console.print(f"\n[bold]Default provider:[/bold] {config.default_provider}\n")

    # Create router
    router = LLMRouter(config)
    console.print(f"Router initialized with provider: [green]{router.current_provider}[/green]\n")

    # Mock response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message = MagicMock()
    mock_response.choices[0].message.content = "Hello! I'm a mocked LLM response."
    mock_response.choices[0].message.tool_calls = None

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
        mock_completion.return_value = mock_response

        # Test 1: Simple text response
        console.print("[bold yellow]Test 1: Simple text response[/bold yellow]")
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        response = await router.chat(messages)

        console.print(f"Provider: [green]{response.provider}[/green]")
        console.print(f"Model: [blue]{response.model}[/blue]")
        console.print(f"Latency: [magenta]{response.latency_ms}ms[/magenta]")
        console.print(f"Content: {response.content}\n")

        # Test 2: Switch provider
        console.print("[bold yellow]Test 2: Switch provider[/bold yellow]")
        console.print(f"Current provider: {router.current_provider}")
        router.switch_provider("openai")
        console.print(f"Switched to: [green]{router.current_provider}[/green]\n")

        # Test 3: Test with tool call
        console.print("[bold yellow]Test 3: Test with tool calls[/bold yellow]")

        # Mock tool call response
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_abc123"
        mock_tool_call.function = MagicMock()
        mock_tool_call.function.name = "add_track"
        mock_tool_call.function.arguments = '{"name": "Bass", "color": "#0000FF"}'

        mock_response_with_tools = MagicMock()
        mock_response_with_tools.choices = [MagicMock()]
        mock_response_with_tools.choices[0].message = MagicMock()
        mock_response_with_tools.choices[0].message.content = None
        mock_response_with_tools.choices[0].message.tool_calls = [mock_tool_call]

        mock_completion.return_value = mock_response_with_tools

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_track",
                    "description": "Add a new track to the project",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Track name"},
                            "color": {"type": "string", "description": "Track color (hex)"}
                        },
                        "required": ["name"]
                    }
                }
            }
        ]

        response = await router.chat(
            [{"role": "user", "content": "Add a bass track colored blue"}],
            tools=tools
        )

        console.print(f"Provider: [green]{response.provider}[/green]")
        console.print(f"Model: [blue]{response.model}[/blue]")
        console.print(f"Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")

        if response.tool_calls:
            for tc in response.tool_calls:
                console.print(f"  - [cyan]{tc.name}[/cyan]({tc.arguments})")

    console.print("\n[bold green]✓ All manual tests completed successfully![/bold green]\n")


async def test_with_real_api():
    """Test router with real API (if ANTHROPIC_API_KEY is set)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        console.print(
            "[yellow]⚠ ANTHROPIC_API_KEY not set. Skipping real API test.[/yellow]\n"
            "[dim]Set ANTHROPIC_API_KEY environment variable to test with real API.[/dim]\n"
        )
        return

    console.print("\n[bold cyan]Testing LLM Router with real Anthropic API[/bold cyan]\n")

    # Create a simple config for Anthropic
    from harvest.llm import AppConfig, ProviderConfig

    config = AppConfig(
        default_provider="anthropic",
        providers={
            "anthropic": ProviderConfig(
                model="claude-sonnet-4-5",
                api_key=api_key,
                timeout=30
            )
        }
    )

    router = LLMRouter(config)

    try:
        console.print("Sending real request to Anthropic API...")
        response = await router.chat([
            {"role": "user", "content": "Say hello in exactly 5 words."}
        ])

        console.print(f"\n[bold green]✓ Real API test successful![/bold green]")
        console.print(f"Provider: [green]{response.provider}[/green]")
        console.print(f"Model: [blue]{response.model}[/blue]")
        console.print(f"Latency: [magenta]{response.latency_ms}ms[/magenta]")
        console.print(f"Response: {response.content}\n")

    except Exception as e:
        console.print(f"[red]✗ Real API test failed: {e}[/red]\n")


async def main():
    """Run all manual tests."""
    await test_with_mock()
    await test_with_real_api()


if __name__ == "__main__":
    asyncio.run(main())
