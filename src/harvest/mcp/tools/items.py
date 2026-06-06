"""Media-item tools."""

TOOLS = [
    {
        "type": "function",
        "bridge_tool": "insert_midi_item",
        "function": {
            "name": "insert_midi_item",
            "description": (
                "Insert an empty MIDI item on a track. "
                "Returns an item_id you can use with add_midi_note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "integer", "description": "Numeric track id"},
                    "start": {
                        "type": "number",
                        "description": "Item start position in seconds from the project start",
                    },
                    "length": {
                        "type": "number",
                        "description": "Item length in seconds (4 beats at 120 BPM = 8 seconds)",
                    },
                },
                "required": ["track_id"],
            },
        },
    },
]
