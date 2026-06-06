"""FX tools."""

TOOLS = [
    {
        "type": "function",
        "bridge_tool": "add_fx",
        "function": {
            "name": "add_fx",
            "description": (
                "Add a VST/JS/AU plugin to a track's FX chain. "
                "Use the plugin's display name exactly as it appears in REAPER, "
                "e.g. 'ReaComp', 'ReaEQ', 'ReaVerb'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "integer", "description": "Numeric track id"},
                    "fx_name": {
                        "type": "string",
                        "description": "Plugin name as it appears in REAPER (e.g. 'ReaComp', 'ReaEQ')",
                    },
                },
                "required": ["track_id", "fx_name"],
            },
        },
    },
]
