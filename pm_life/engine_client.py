from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any


class EngineError(RuntimeError):
    """Raised when the bundled JavaScript engine rejects or loses a request."""


class EngineClient:
    def __init__(
        self,
        worker_path: Path,
        node_path: str = "node",
        timeout: float = 20.0,
        logger: Any | None = None,
    ) -> None:
        self.worker_path = Path(worker_path).resolve()
        self.node_path = node_path
        self.timeout = timeout
        self.logger = logger
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self) -> dict[str, Any]:
        return await self.request("ping")

    async def request(self, action: str, **payload: Any) -> dict[str, Any]:
        async with self._lock:
            await self._ensure_process()
            assert self._process is not None
            assert self._process.stdin is not None
            assert self._process.stdout is not None

            request_id = uuid.uuid4().hex
            raw = json.dumps(
                {"id": request_id, "action": action, **payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            try:
                self._process.stdin.write(raw)
                await self._process.stdin.drain()
                line = await asyncio.wait_for(
                    self._process.stdout.readline(), timeout=self.timeout
                )
            except (TimeoutError, BrokenPipeError, ConnectionError) as exc:
                await self._stop_unlocked()
                raise EngineError(f"游戏引擎请求失败或超时：{exc}") from exc

            if not line:
                code = await self._process.wait()
                await self._stop_unlocked()
                raise EngineError(f"游戏引擎意外退出，退出码 {code}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                await self._stop_unlocked()
                raise EngineError("游戏引擎返回了无效数据") from exc
            if response.get("id") != request_id:
                await self._stop_unlocked()
                raise EngineError("游戏引擎响应序号不匹配")
            if not response.get("ok"):
                raise EngineError(str(response.get("error") or "未知游戏引擎错误"))
            result = response.get("result")
            if not isinstance(result, dict):
                raise EngineError("游戏引擎响应缺少结果")
            return result

    async def close(self) -> None:
        async with self._lock:
            await self._stop_unlocked()

    async def _ensure_process(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.node_path,
                str(self.worker_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.worker_path.parent),
            )
        except FileNotFoundError as exc:
            raise EngineError(
                f"找不到 Node.js 可执行文件“{self.node_path}”，请安装 Node.js 20+ 或修改插件配置"
            ) from exc
        assert self._process.stderr is not None
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        while line := await process.stderr.readline():
            if self.logger:
                self.logger.warning(
                    "[月计人生/Node] %s", line.decode("utf-8", errors="replace").rstrip()
                )

    async def _stop_unlocked(self) -> None:
        process, self._process = self._process, None
        stderr_task, self._stderr_task = self._stderr_task, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task is not None:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
