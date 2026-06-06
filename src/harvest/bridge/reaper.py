"""REAPER IPC bridge — file-based command/result protocol."""

import asyncio
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

import aiofiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_CMD_PATH = Path("/tmp/harvest_cmd.json")
_DEFAULT_RESULT_PATH = Path("/tmp/harvest_result.json")
_POLL_INTERVAL = 0.05  # 50 ms


class IPCCommand(BaseModel):
    id: str
    tool: str
    params: dict[str, Any]


class IPCResponse(BaseModel):
    id: str
    ok: bool
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ReaperBridgeError(RuntimeError):
    pass


class ReaperBridge:
    """Async client for the file-based REAPER IPC protocol."""

    def __init__(
        self,
        cmd_path: Path = _DEFAULT_CMD_PATH,
        result_path: Path = _DEFAULT_RESULT_PATH,
    ) -> None:
        self._cmd_path = cmd_path
        self._result_path = result_path

    async def call(
        self,
        tool: str,
        params: dict[str, Any],
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        cmd_id = str(uuid.uuid4())
        cmd = IPCCommand(id=cmd_id, tool=tool, params=params)

        # Remove stale result from a previous run
        try:
            self._result_path.unlink(missing_ok=True)
        except OSError:
            pass

        # Write command atomically
        await self._write_atomic(self._cmd_path, cmd.model_dump_json())
        logger.debug(f"Bridge → tool={tool} id={cmd_id}")

        # Poll for matching result
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

            raw = await self._try_read(self._result_path)
            if raw is None:
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("id") != cmd_id:
                continue

            resp = IPCResponse(**data)
            if not resp.ok:
                raise ReaperBridgeError(
                    f"REAPER error for '{tool}': {resp.error}"
                )
            logger.debug(f"Bridge ← ok id={cmd_id}")
            return resp.result or {}

        raise TimeoutError(
            f"No response from REAPER for '{tool}' after {timeout}s — "
            "is reaper_ipc_bridge.lua running?"
        )

    async def _write_atomic(self, path: Path, content: str) -> None:
        dir_ = path.parent
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            async with aiofiles.open(tmp, "w") as f:
                await f.write(content)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    async def _try_read(self, path: Path) -> Optional[str]:
        try:
            async with aiofiles.open(path, "r") as f:
                return await f.read()
        except (FileNotFoundError, PermissionError):
            return None
