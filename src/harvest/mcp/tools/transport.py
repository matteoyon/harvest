"""Transport control tools."""

TOOLS = [
    {
        "type": "function",
        "bridge_tool": "play",
        "function": {
            "name": "play",
            "description": "Start REAPER playback from the current cursor position.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "bridge_tool": "stop",
        "function": {
            "name": "stop",
            "description": "Stop REAPER playback.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]
