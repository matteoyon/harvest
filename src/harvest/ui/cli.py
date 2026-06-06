"""CLI chat loop for harvest — the REAPER conversational agent."""

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.status import Status
from rich.syntax import Syntax

from harvest.bridge.reaper import ReaperBridge
from harvest.llm.router import LLMRouter
from harvest.llm.providers import load_config
from harvest.mcp.registry import ToolRegistry

logger = logging.getLogger(__name__)
console = Console()

_CONFIG_PATH = Path("config/providers.toml")

_SYSTEM_PROMPT = """\
You are Harvest, an AI agent that controls REAPER DAW through tool calls.
The user speaks to you in natural language; you translate their intent into concrete REAPER operations.

CRITICAL RULES — follow these exactly:
- ALWAYS use tools to interact with REAPER. Never describe an action without calling a tool.
- ONLY perform operations that the user EXPLICITLY requested. Do NOT add volumes, FX, sends,
  MIDI notes, or any other operations unless the user specifically asked for them.
  If the user asks only to create tracks, ONLY create tracks — nothing else.
- NEVER give a final text response until you have executed EVERY operation the user requested.
  If the user asks for 5 tracks, call add_track 5 times before responding with text.
- For multi-step requests: keep calling tools one after another until ALL requested steps are done,
  then stop immediately and confirm.

Musical knowledge (MIDI pitch numbers 0–127):
- Middle C (C4) = 60. Each semitone = +1. Each octave = ±12.
- C4=60, D4=62, E4=64, F4=65, G4=67, A4=69, B4=71
- C3=48, C5=72. Sharps: C#4=61, D#4=63. Flats: Bb4=70, Ab4=68.

Color conventions: percussion → #FF4444 (red), melodic → #4444FF (blue).
"""


def _format_tool_call(name: str, args: dict[str, Any]) -> str:
    args_str = json.dumps(args, ensure_ascii=False)
    if len(args_str) > 120:
        args_str = args_str[:117] + "..."
    return f"[bold cyan]{name}[/bold cyan]({args_str})"


def _parse_text_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """
    Small models sometimes output tool calls as JSON text in the content body
    instead of using the structured function-calling protocol.
    This parser detects two common patterns and returns [(name, args), ...].

    Pattern A (single call, OpenAI-like):
        {"type": "function", "function": {"name": "...", "arguments": {...}}}

    Pattern B (batch, model-invented):
        {"calls": [{"function": {"name": "..."}, "arguments": {...}}, ...]}
    """
    stripped = content.strip()
    if not stripped.startswith("{"):
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return []

    calls: list[tuple[str, dict[str, Any]]] = []

    if data.get("type") == "function" and isinstance(data.get("function"), dict):
        fn = data["function"]
        name = fn.get("name", "")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return []
        if name:
            calls.append((name, args))

    elif isinstance(data.get("calls"), list):
        for call in data["calls"]:
            fn = call.get("function", {})
            name = fn.get("name", "") if isinstance(fn, dict) else ""
            args = call.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if name:
                calls.append((name, args))

    # Pattern C: {"tool_calls": [{"function_call": "name", "args": {...}}, ...]}
    #        or  {"tool_calls": [{"function": "name",      "args": {...}}, ...]}
    # gemma4:e4b emits this variant instead of the structured protocol.
    elif isinstance(data.get("tool_calls"), list):
        for call in data["tool_calls"]:
            # "function_call" key takes priority, then "function" if it's a plain string
            fn_val = call.get("function_call") or call.get("function")
            if not isinstance(fn_val, str):
                continue
            name = fn_val
            args = call.get("args") or call.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if name:
                calls.append((name, args))

    return calls


def _tool_key(name: str, args: dict[str, Any]) -> str:
    return f"{name}|{json.dumps(args, sort_keys=True)}"


def _continuation(user_input: str, done_summary: str) -> dict[str, Any]:
    """Continuation injection injected after every executed tool call."""
    return {
        "role": "user",
        "content": f"Just done: {done_summary}\n"
                   f"Original request: «{user_input}»\n"
                   "What is the NEXT operation from the original request that has NOT been done yet? "
                   "Call that tool now. Do NOT repeat calls already made. "
                   "Do NOT add FX, volumes, sends, MIDI, or anything not in the original request. "
                   "If every explicitly requested operation is complete, "
                   "reply with a brief confirmation and stop.",
    }


async def agent_loop(
    user_input: str,
    messages: list[dict[str, Any]],
    router: LLMRouter,
    bridge: ReaperBridge,
    registry: ToolRegistry,
) -> None:
    messages.append({"role": "user", "content": user_input})
    tools = registry.openai_schemas()
    max_iters = 25
    truncated_retries = 0          # cap retries for cut-off JSON responses
    called_this_turn: set[str] = set()   # dedup: skip identical (tool, args) pairs

    for _ in range(max_iters):
        with Status("[dim]thinking…[/dim]", console=console, spinner="dots"):
            response = await router.chat(messages, tools=tools)

        if response.tool_calls:
            # Structured tool calls — the happy path.
            # content="" instead of None: some local models hang on null content in history.
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            executed: list[str] = []
            for tc in response.tool_calls:
                key = _tool_key(tc.name, tc.arguments)
                if key in called_this_turn:
                    console.print(f"  [dim yellow]⚠ skipping duplicate: {tc.name}[/dim yellow]")
                    # Still need a tool result in the message history for this call's id
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"skipped": "duplicate call"}),
                    })
                    continue
                called_this_turn.add(key)

                console.print(f"  [dim]→[/dim] {_format_tool_call(tc.name, tc.arguments)}")
                with Status("[dim]executing…[/dim]", console=console, spinner="dots"):
                    result = await registry.execute(tc.name, tc.arguments, bridge)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

                result_preview = json.dumps(result, ensure_ascii=False)
                if len(result_preview) > 200:
                    result_preview = result_preview[:197] + "..."
                console.print(f"  [dim]←[/dim] [green]{result_preview}[/green]")
                executed.append(f"{tc.name}({json.dumps(tc.arguments)})")

            if executed:
                messages.append(_continuation(user_input, ", ".join(executed)))

        else:
            content = response.content or ""

            if not content.strip():
                console.print(
                    "[red]⚠ Model returned an empty response with no tool calls.[/red]\n"
                    "[dim]Possible causes:\n"
                    "  • Qwen3 thinking mode — add [bold]extra_body = {think = false}[/bold] "
                    "to your [providers.ollama] config.\n"
                    "  • Wrong model name (check [bold]ollama list[/bold]).\n"
                    "  • Try [bold]/provider[/bold] to switch to a known-working model.[/dim]"
                )
                return

            # Truncated / cut-off JSON — cap retries to avoid burning all iterations.
            if content.startswith("{") and not content.strip().endswith("}"):
                truncated_retries += 1
                if truncated_retries >= 3:
                    console.print("[red]⚠ Model keeps generating truncated responses. Stopping.[/red]")
                    return
                console.print("[yellow]⚠ Model response was cut off (truncated JSON). Retrying…[/yellow]")
                continue

            # Fallback: model output a tool call as JSON text instead of the structured protocol.
            text_calls = _parse_text_tool_calls(content)
            if text_calls:
                console.print(
                    f"  [dim yellow]⚠ model returned {len(text_calls)} tool call(s) as text — executing[/dim yellow]"
                )
                messages.append({"role": "assistant", "content": content})
                executed_text: list[str] = []
                for name, args in text_calls:
                    key = _tool_key(name, args)
                    if key in called_this_turn:
                        console.print(f"  [dim yellow]⚠ skipping duplicate: {name}[/dim yellow]")
                        continue
                    called_this_turn.add(key)

                    console.print(f"  [dim]→[/dim] {_format_tool_call(name, args)} [dim](text)[/dim]")
                    with Status("[dim]executing…[/dim]", console=console, spinner="dots"):
                        result = await registry.execute(name, args, bridge)
                    result_preview = json.dumps(result, ensure_ascii=False)
                    if len(result_preview) > 200:
                        result_preview = result_preview[:197] + "..."
                    console.print(f"  [dim]←[/dim] [green]{result_preview}[/green]")
                    executed_text.append(f"{name}({json.dumps(args)})")

                if executed_text:
                    messages.append(_continuation(user_input, ", ".join(executed_text)))
                continue

            # Genuine final text response.
            messages.append({"role": "assistant", "content": content})
            console.print(
                Panel(
                    content,
                    title=f"[dim]{router.current_provider} · {response.model} · {response.latency_ms}ms[/dim]",
                    border_style="blue",
                )
            )
            return

    console.print("[yellow]⚠ Reached iteration limit without a final response.[/yellow]")


async def run() -> None:
    console.print(
        Panel(
            "[bold]harvest[/bold] — REAPER conversational agent\n"
            "[dim]Commands: /provider <name>  /state  /help  /quit[/dim]",
            border_style="cyan",
        )
    )

    if not _CONFIG_PATH.exists():
        console.print(
            f"[red]Config not found: {_CONFIG_PATH}[/red]\n"
            "Copy config/providers.example.toml → config/providers.toml and fill in your keys."
        )
        sys.exit(1)

    config = load_config(_CONFIG_PATH)
    router = LLMRouter(config)
    bridge = ReaperBridge()
    registry = ToolRegistry()

    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    console.print(
        f"Provider: [green]{router.current_provider}[/green]  "
        f"Available: [dim]{', '.join(config.list_providers())}[/dim]\n"
    )

    while True:
        try:
            raw = Prompt.ask("[bold]>[/bold]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            break

        text = raw.strip()
        if not text:
            continue

        if text in ("/quit", "/exit", "quit", "exit"):
            console.print("[dim]bye[/dim]")
            break

        if text == "/help":
            console.print(
                "  [cyan]/provider <name>[/cyan]  switch LLM provider (hot-swap)\n"
                "  [cyan]/state[/cyan]             print current REAPER project state\n"
                "  [cyan]/help[/cyan]              show this message\n"
                "  [cyan]/quit[/cyan]              exit"
            )
            continue

        if text.startswith("/provider "):
            name = text.split(None, 1)[1].strip()
            try:
                router.switch_provider(name)
                console.print(f"[green]Switched to provider: {name}[/green]")
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
            continue

        if text == "/state":
            with Status("[dim]fetching state…[/dim]", console=console, spinner="dots"):
                result = await registry.execute("get_project_state", {}, bridge)
            console.print(
                Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json", theme="monokai")
            )
            continue

        try:
            await agent_loop(text, messages, router, bridge, registry)
        except TimeoutError as e:
            console.print(f"[red]REAPER timeout: {e}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            logger.exception("Unhandled error in agent loop")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
