"""Tests for the REAPER IPC bridge and FakeReaperState."""

import asyncio
import json
import os
import pytest
from pathlib import Path

from harvest.bridge.fake_reaper import FakeReaperState, run_simulator
from harvest.bridge.reaper import ReaperBridge, ReaperBridgeError


# ---------------------------------------------------------------------------
# FakeReaperState unit tests (no I/O)
# ---------------------------------------------------------------------------

class TestFakeReaperState:
    def setup_method(self):
        self.state = FakeReaperState()

    def test_initial_state_empty(self):
        result = self.state.get_project_state()
        assert result["tracks"] == []
        assert result["project"]["bpm"] == 120

    def test_add_track(self):
        result = self.state.add_track(name="Kick", color="#FF4444")
        assert result["id"] == 0
        assert result["name"] == "Kick"
        assert len(self.state.tracks) == 1
        assert self.state.tracks[0]["color"] == "#FF4444"

    def test_add_multiple_tracks(self):
        self.state.add_track(name="A")
        self.state.add_track(name="B")
        self.state.add_track(name="C")
        assert len(self.state.tracks) == 3
        ids = [t["id"] for t in self.state.tracks]
        assert ids == [0, 1, 2]

    def test_delete_track(self):
        self.state.add_track(name="X")
        self.state.add_track(name="Y")
        result = self.state.delete_track(track_id=0)
        assert result["deleted"] == 1
        assert len(self.state.tracks) == 1
        assert self.state.tracks[0]["name"] == "Y"

    def test_rename_track(self):
        self.state.add_track(name="Old")
        result = self.state.rename_track(track_id=0, name="New")
        assert result["name"] == "New"
        assert self.state.tracks[0]["name"] == "New"

    def test_set_track_volume(self):
        self.state.add_track(name="Bass")
        result = self.state.set_track_volume(track_id=0, vol_db=-6.0)
        assert result["vol_db"] == -6.0

    def test_insert_midi_item(self):
        self.state.add_track(name="MIDI")
        result = self.state.insert_midi_item(track_id=0, start=0.0, length=8.0)
        assert result["item_id"] == "i0"
        assert self.state.tracks[0]["items"][0]["len"] == 8.0

    def test_add_midi_note(self):
        self.state.add_track(name="MIDI")
        self.state.insert_midi_item(track_id=0)
        result = self.state.add_midi_note(
            track_id=0, item_id="i0", pitch=60,
            start_beat=0.0, duration_beats=1.0, velocity=100
        )
        assert result["added"]["pitch"] == 60

    def test_add_fx(self):
        self.state.add_track(name="Kick")
        result = self.state.add_fx(track_id=0, fx_name="ReaComp")
        assert result["name"] == "ReaComp"
        assert result["fx_idx"] == 0
        assert self.state.tracks[0]["fx"][0]["name"] == "ReaComp"

    def test_play_stop(self):
        assert self.state.play()["status"] == "playing"
        assert self.state.stop()["status"] == "stopped"

    def test_dispatch_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            self.state.dispatch("nonexistent", {})

    def test_get_track_not_found(self):
        with pytest.raises(KeyError):
            self.state._get_track(99)


# ---------------------------------------------------------------------------
# ReaperBridge integration test using the fake simulator as file responder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bridge_round_trip(tmp_path):
    cmd_path = tmp_path / "cmd.json"
    result_path = tmp_path / "result.json"

    bridge = ReaperBridge(cmd_path=cmd_path, result_path=result_path)

    # Simulate the REAPER side: write a matching result after seeing the command
    async def fake_responder():
        while not cmd_path.exists():
            await asyncio.sleep(0.01)
        raw = cmd_path.read_text()
        data = json.loads(raw)
        response = {"id": data["id"], "ok": True, "result": {"status": "ok"}}
        result_path.write_text(json.dumps(response))

    responder_task = asyncio.create_task(fake_responder())
    result = await bridge.call("play", {}, timeout=2.0)
    await responder_task
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_bridge_timeout(tmp_path):
    cmd_path = tmp_path / "cmd.json"
    result_path = tmp_path / "result.json"

    bridge = ReaperBridge(cmd_path=cmd_path, result_path=result_path)

    with pytest.raises(TimeoutError, match="No response"):
        await bridge.call("play", {}, timeout=0.2)


@pytest.mark.asyncio
async def test_bridge_error_response(tmp_path):
    cmd_path = tmp_path / "cmd.json"
    result_path = tmp_path / "result.json"

    bridge = ReaperBridge(cmd_path=cmd_path, result_path=result_path)

    async def error_responder():
        while not cmd_path.exists():
            await asyncio.sleep(0.01)
        raw = cmd_path.read_text()
        data = json.loads(raw)
        response = {"id": data["id"], "ok": False, "error": "Track not found"}
        result_path.write_text(json.dumps(response))

    asyncio.create_task(error_responder())
    with pytest.raises(ReaperBridgeError, match="Track not found"):
        await bridge.call("delete_track", {"track_id": 99}, timeout=2.0)


@pytest.mark.asyncio
async def test_bridge_id_mismatch_then_match(tmp_path):
    """Bridge must ignore responses whose id doesn't match."""
    cmd_path = tmp_path / "cmd.json"
    result_path = tmp_path / "result.json"

    bridge = ReaperBridge(cmd_path=cmd_path, result_path=result_path)

    async def delayed_correct_responder():
        while not cmd_path.exists():
            await asyncio.sleep(0.01)
        raw = cmd_path.read_text()
        data = json.loads(raw)
        # First write a wrong id
        result_path.write_text(json.dumps({"id": "wrong-id", "ok": True, "result": {}}))
        await asyncio.sleep(0.1)
        # Then write the correct one
        result_path.write_text(json.dumps({"id": data["id"], "ok": True, "result": {"hit": True}}))

    asyncio.create_task(delayed_correct_responder())
    result = await bridge.call("play", {}, timeout=2.0)
    assert result == {"hit": True}
