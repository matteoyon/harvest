"""MIDI editing tools."""

TOOLS = [
    {
        "type": "function",
        "bridge_tool": "add_midi_note",
        "function": {
            "name": "add_midi_note",
            "description": (
                "Add a MIDI note to an existing MIDI item. "
                "Pitch is a MIDI note number 0–127 where middle C (C4) = 60. "
                "Musical note-to-pitch mapping: C4=60, D4=62, E4=64, F4=65, G4=67, A4=69, B4=71. "
                "For other octaves add or subtract 12 per octave (C3=48, C5=72)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "integer", "description": "Numeric track id"},
                    "item_id": {
                        "type": "string",
                        "description": "Item id returned by insert_midi_item",
                    },
                    "pitch": {
                        "type": "integer",
                        "description": "MIDI note number 0–127 (C4=60, D4=62, E4=64, G4=67, B4=71)",
                    },
                    "start_beat": {
                        "type": "number",
                        "description": "Note start in beats from the item's beginning (0 = item start)",
                    },
                    "duration_beats": {
                        "type": "number",
                        "description": "Note duration in beats (1 = one quarter note)",
                    },
                    "velocity": {
                        "type": "integer",
                        "description": "MIDI velocity 1–127 (default 100)",
                    },
                },
                "required": ["track_id", "item_id", "pitch"],
            },
        },
    },
]
