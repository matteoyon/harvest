"""In-process tool registry aggregating all REAPER tool specs."""

import json
import logging
from typing import TYPE_CHECKING, Any

from .tools import fx, items, midi, tracks, transport

if TYPE_CHECKING:
    from harvest.bridge.reaper import ReaperBridge

logger = logging.getLogger(__name__)

_ALL_TOOL_SPECS: list[dict[str, Any]] = (
    tracks.TOOLS + items.TOOLS + midi.TOOLS + fx.TOOLS + transport.TOOLS
)

# bridge_tool name may differ from function name; index both
_BY_NAME: dict[str, dict[str, Any]] = {
    spec["function"]["name"]: spec for spec in _ALL_TOOL_SPECS
}


class ToolRegistry:
    """Provides OpenAI-format schemas and dispatches tool calls to the bridge."""

    def openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
        return [
            {"type": "function", "function": spec["function"]}
            for spec in _ALL_TOOL_SPECS
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        bridge: "ReaperBridge",
    ) -> dict[str, Any]:
        spec = _BY_NAME.get(name)
        if spec is None:
            logger.warning(f"Unknown tool requested: {name}")
            return {"error": f"Unknown tool: {name}"}

        bridge_tool = spec.get("bridge_tool", name)
        logger.debug(f"execute {name} → bridge:{bridge_tool}({arguments})")

        try:
            result = await bridge.call(bridge_tool, arguments)
            return result
        except Exception as exc:
            logger.error(f"Tool '{name}' failed: {exc}")
            return {"error": str(exc)}
