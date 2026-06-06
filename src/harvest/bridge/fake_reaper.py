"""Fake REAPER simulator for end-to-end testing without the DAW.

Run as a subprocess: python -m harvest.bridge.fake_reaper
It polls /tmp/harvest_cmd.json and writes /tmp/harvest_result.json,
mirroring the behaviour of scripts/reaper_ipc_bridge.lua.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)

_CMD_PATH = Path("/tmp/harvest_cmd.json")
_RESULT_PATH = Path("/tmp/harvest_result.json")
_POLL_INTERVAL = 0.05


# ---------------------------------------------------------------------------
# In-memory project state (matches the CLAUDE.md state model)
# ---------------------------------------------------------------------------

class FakeReaperState:
    def __init__(self) -> None:
        self.project = {
            "name": "FakeSession",
            "bpm": 120,
            "time_sig": "4/4",
            "sample_rate": 48000,
            "cursor": 0.0,
            "length": 120.0,
        }
        self.tracks: list[dict[str, Any]] = []
        self._next_item_id = 0

    # --- tools ----------------------------------------------------------------

    def get_project_state(self, **_: Any) -> dict[str, Any]:
        return {"project": self.project, "tracks": self.tracks}

    def list_tracks(self, **_: Any) -> dict[str, Any]:
        return {"tracks": [{"id": t["id"], "name": t["name"]} for t in self.tracks]}

    def add_track(self, name: str, color: str = "#888888", **_: Any) -> dict[str, Any]:
        track_id = len(self.tracks)
        track = {
            "id": track_id,
            "name": name,
            "type": "audio",
            "vol_db": 0.0,
            "pan": 0.0,
            "muted": False,
            "soloed": False,
            "color": color,
            "fx": [],
            "sends": [],
            "items": [],
        }
        self.tracks.append(track)
        return {"id": track_id, "name": name}

    def delete_track(self, track_id: int, **_: Any) -> dict[str, Any]:
        before = len(self.tracks)
        self.tracks = [t for t in self.tracks if t["id"] != track_id]
        return {"deleted": before - len(self.tracks)}

    def rename_track(self, track_id: int, name: str, **_: Any) -> dict[str, Any]:
        track = self._get_track(track_id)
        track["name"] = name
        return {"id": track_id, "name": name}

    def set_track_volume(self, track_id: int, vol_db: float, **_: Any) -> dict[str, Any]:
        track = self._get_track(track_id)
        track["vol_db"] = vol_db
        return {"id": track_id, "vol_db": vol_db}

    def insert_midi_item(
        self, track_id: int, start: float = 0.0, length: float = 4.0, **_: Any
    ) -> dict[str, Any]:
        track = self._get_track(track_id)
        item_id = f"i{self._next_item_id}"
        self._next_item_id += 1
        item = {"id": item_id, "start": start, "len": length, "type": "midi", "notes": []}
        track["items"].append(item)
        return {"item_id": item_id, "track_id": track_id, "start": start, "len": length}

    def add_midi_note(
        self,
        track_id: int,
        item_id: str,
        pitch: int,
        start_beat: float = 0.0,
        duration_beats: float = 1.0,
        velocity: int = 100,
        **_: Any,
    ) -> dict[str, Any]:
        track = self._get_track(track_id)
        item = next((i for i in track["items"] if i["id"] == item_id), None)
        if item is None:
            raise KeyError(f"Item '{item_id}' not found on track {track_id}")
        note = {
            "pitch": pitch,
            "start_beat": start_beat,
            "duration_beats": duration_beats,
            "velocity": velocity,
        }
        item["notes"].append(note)
        return {"added": note}

    def add_fx(self, track_id: int, fx_name: str, **_: Any) -> dict[str, Any]:
        track = self._get_track(track_id)
        idx = len(track["fx"])
        entry = {"idx": idx, "name": fx_name, "enabled": True}
        track["fx"].append(entry)
        return {"track_id": track_id, "fx_idx": idx, "name": fx_name}

    def play(self, **_: Any) -> dict[str, Any]:
        return {"status": "playing"}

    def stop(self, **_: Any) -> dict[str, Any]:
        return {"status": "stopped"}

    # --- helpers --------------------------------------------------------------

    def _get_track(self, track_id: int) -> dict[str, Any]:
        for t in self.tracks:
            if t["id"] == track_id:
                return t
        raise KeyError(f"Track {track_id} not found")

    def dispatch(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "get_project_state": self.get_project_state,
            "list_tracks": self.list_tracks,
            "add_track": self.add_track,
            "delete_track": self.delete_track,
            "rename_track": self.rename_track,
            "set_track_volume": self.set_track_volume,
            "insert_midi_item": self.insert_midi_item,
            "add_midi_note": self.add_midi_note,
            "add_fx": self.add_fx,
            "play": self.play,
            "stop": self.stop,
        }
        handler = handlers.get(tool)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool}")
        return handler(**params)


# ---------------------------------------------------------------------------
# File-polling runner (mirrors reaper_ipc_bridge.lua behaviour)
# ---------------------------------------------------------------------------

async def run_simulator(
    cmd_path: Path = _CMD_PATH,
    result_path: Path = _RESULT_PATH,
) -> None:
    state = FakeReaperState()

    # Consume any stale command file without processing it
    last_id: str | None = None
    if cmd_path.exists():
        try:
            stale = json.loads(cmd_path.read_text())
            last_id = stale.get("id")
        except Exception:
            pass

    print(f"[fake-reaper] listening on {cmd_path}")
    print("[fake-reaper] Ctrl-C to stop\n")

    while True:
        await asyncio.sleep(_POLL_INTERVAL)

        if not cmd_path.exists():
            continue

        try:
            async with aiofiles.open(cmd_path, "r") as f:
                raw = await f.read()
            data = json.loads(raw)
        except Exception:
            continue

        cmd_id = data.get("id")
        if not cmd_id or cmd_id == last_id:
            continue

        last_id = cmd_id
        tool = data.get("tool", "")
        params = data.get("params", {})

        print(f"[fake-reaper] ← {tool}({params})")
        t0 = time.perf_counter()

        try:
            result = state.dispatch(tool, params)
            response = {"id": cmd_id, "ok": True, "result": result}
        except Exception as exc:
            response = {"id": cmd_id, "ok": False, "error": str(exc)}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        status = "ok" if response["ok"] else "err"
        print(f"[fake-reaper] → {status} {elapsed_ms}ms")

        # Write result atomically
        tmp = str(result_path) + ".tmp"
        async with aiofiles.open(tmp, "w") as f:
            await f.write(json.dumps(response))
        os.replace(tmp, result_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(run_simulator())
    except KeyboardInterrupt:
        print("\n[fake-reaper] stopped")
