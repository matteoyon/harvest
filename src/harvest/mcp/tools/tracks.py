"""Track-level REAPER tools."""

TOOLS = [
    {
        "type": "function",
        "bridge_tool": "get_project_state",
        "function": {
            "name": "get_project_state",
            "description": (
                "Return the full project snapshot: tempo, time signature, cursor position, "
                "and all tracks with their FX, sends, and items."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "bridge_tool": "list_tracks",
        "function": {
            "name": "list_tracks",
            "description": "Return a compact list of all track ids and names.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "bridge_tool": "add_track",
        "function": {
            "name": "add_track",
            "description": "Add a new track to the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Track name"},
                    "color": {
                        "type": "string",
                        "description": "Track color as a hex string, e.g. '#FF4444'",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "bridge_tool": "delete_track",
        "function": {
            "name": "delete_track",
            "description": "Delete a track by its numeric id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "integer", "description": "Numeric track id"}
                },
                "required": ["track_id"],
            },
        },
    },
    {
        "type": "function",
        "bridge_tool": "rename_track",
        "function": {
            "name": "rename_track",
            "description": "Rename an existing track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "integer", "description": "Numeric track id"},
                    "name": {"type": "string", "description": "New track name"},
                },
                "required": ["track_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "bridge_tool": "set_track_volume",
        "function": {
            "name": "set_track_volume",
            "description": "Set the fader volume of a track in dB (0 dB = unity gain).",
            "parameters": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "integer", "description": "Numeric track id"},
                    "vol_db": {
                        "type": "number",
                        "description": "Volume in decibels. 0 = unity, -6 = half, -inf = silent.",
                    },
                },
                "required": ["track_id", "vol_db"],
            },
        },
    },
]
