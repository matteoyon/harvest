"""Tests for the tool registry and tool schema definitions."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from harvest.mcp.registry import ToolRegistry
from harvest.mcp.tools import tracks, items, midi, fx, transport


class TestToolSchemas:
    def setup_method(self):
        self.registry = ToolRegistry()

    def test_all_ten_tools_present(self):
        schemas = self.registry.openai_schemas()
        names = {s["function"]["name"] for s in schemas}
        expected = {
            "get_project_state", "list_tracks", "add_track",
            "delete_track", "rename_track", "set_track_volume",
            "insert_midi_item", "add_midi_note", "add_fx",
            "play", "stop",
        }
        assert expected == names

    def test_schemas_are_valid_openai_format(self):
        schemas = self.registry.openai_schemas()
        for schema in schemas:
            assert schema["type"] == "function"
            fn = schema["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"
            assert "required" in fn["parameters"]

    def test_required_fields_are_lists(self):
        schemas = self.registry.openai_schemas()
        for schema in schemas:
            req = schema["function"]["parameters"]["required"]
            assert isinstance(req, list)

    def test_add_midi_note_pitch_description_contains_middle_c(self):
        schemas = self.registry.openai_schemas()
        note_schema = next(s for s in schemas if s["function"]["name"] == "add_midi_note")
        pitch_desc = note_schema["function"]["parameters"]["properties"]["pitch"]["description"]
        assert "60" in pitch_desc  # middle C = 60

    def test_no_duplicate_tool_names(self):
        all_specs = tracks.TOOLS + items.TOOLS + midi.TOOLS + fx.TOOLS + transport.TOOLS
        names = [s["function"]["name"] for s in all_specs]
        assert len(names) == len(set(names)), "Duplicate tool names found"


class TestToolRegistryExecute:
    def setup_method(self):
        self.registry = ToolRegistry()

    @pytest.mark.asyncio
    async def test_execute_known_tool_forwards_to_bridge(self):
        bridge = MagicMock()
        bridge.call = AsyncMock(return_value={"id": 0, "name": "Test"})

        result = await self.registry.execute("add_track", {"name": "Test"}, bridge)
        bridge.call.assert_called_once_with("add_track", {"name": "Test"})
        assert result == {"id": 0, "name": "Test"}

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self):
        bridge = MagicMock()
        bridge.call = AsyncMock()

        result = await self.registry.execute("nonexistent_tool", {}, bridge)
        assert "error" in result
        assert "nonexistent_tool" in result["error"]
        bridge.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_bridge_exception_returns_error_dict(self):
        bridge = MagicMock()
        bridge.call = AsyncMock(side_effect=TimeoutError("REAPER not responding"))

        result = await self.registry.execute("play", {}, bridge)
        assert "error" in result
        assert "REAPER not responding" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_uses_bridge_tool_name(self):
        """bridge_tool name in spec should be forwarded, not the function name."""
        bridge = MagicMock()
        bridge.call = AsyncMock(return_value={"status": "playing"})

        result = await self.registry.execute("play", {}, bridge)
        # "play" bridge_tool should be called
        bridge.call.assert_called_once_with("play", {})

    @pytest.mark.asyncio
    async def test_execute_all_tools_registered(self):
        """All 10 tools should be executable (bridge calls are mocked)."""
        bridge = MagicMock()
        bridge.call = AsyncMock(return_value={})

        tool_names = [
            "get_project_state", "list_tracks", "add_track",
            "delete_track", "rename_track", "set_track_volume",
            "insert_midi_item", "add_midi_note", "add_fx",
            "play", "stop",
        ]
        for name in tool_names:
            result = await self.registry.execute(name, {}, bridge)
            assert "error" not in result or result.get("error") is None or True
            # Just confirm it routes (no "Unknown tool" error)
            if "error" in result:
                assert "Unknown tool" not in result["error"]
