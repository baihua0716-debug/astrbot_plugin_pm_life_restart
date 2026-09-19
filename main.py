from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Node, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .pm_life.engine_client import EngineClient, EngineError
from .pm_life.formatting import (
    chunk_trajectory,
    format_achievements,
    format_property_prompt,
    format_summary,
    format_talents,
    profile_counts,
)
from .pm_life.storage import SQLiteStore, build_scope_key


PLUGIN_NAME = "astrbot_plugin_pm_life_restart"


@register(
    PLUGIN_NAME,
    "baihua0716-debug",
    "在 QQ 群聊或私聊中游玩独立存档的月计人生重开模拟器。",
    "0.1.2",
    "https://github.com/baihua0716-debug/astrbot_plugin_pm_life_restart",
)
class Main(Star):
    """群聊与私聊独立存档的 Project Moon 人生重开模拟器。"""

    def __init__(self, context: Context, config: Any | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        plugin_root = Path(__file__).resolve().parent
        data_root = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        history_limit = self._config_int("history_limit", 10, minimum=1, maximum=100)
        self.store = SQLiteStore(data_root / "saves.sqlite3", history_limit)
        self.engine = EngineClient(
            plugin_root / "engine" / "worker.js",
            node_path=str(self._config_get("node_path", "node")),
            timeout=float(self._config_int("engine_timeout", 20, 5, 120)),
            logger=logger,
        )
        self.forward_chunk_chars = self._config_int(
            "forward_chunk_chars", 2500, 500, 10000
        )
        self._user_locks: dict[tuple[str, str], asyncio.Lock] = {}
        logger.info("月计人生插件 v0.1.2 已加载，指令：/月计人生")

    @filter.command("月计人生", alias={"pmlife", "pm人生"})
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def monthly_life(self, event: AstrMessageEvent):
        """开始或继续月计人生；发送“/月计人生 帮助”查看玩法。"""
        if getattr(event, "_pm_life_handled", False):
            return
        setattr(event, "_pm_life_handled", True)
        event.stop_event()
        user_id = event.get_sender_id()
        if not user_id:
            yield event.plain_result("无法识别当前 QQ 用户，暂时不能建立存档。")
            event.stop_event()
            return

        user_key = str(user_id)
        group_key = build_scope_key(
            event.get_platform_name(), event.get_group_id(), user_key
        )
        lock = self._user_locks.setdefault((group_key, user_key), asyncio.Lock())
        if lock.locked():
            yield event.plain_result("你的上一条月计人生指令仍在处理中，请稍候。")
            event.stop_event()
            return

        args = self._parse_args(event)
        action = args[0].lower() if args else ""
        rest = args[1:]
        async with lock:
            try:
                if action in {"帮助", "help", "?"}:
                    yield event.plain_result(self._help_text())
                elif action in {"档案", "profile"}:
                    yield event.plain_result(
                        await self._profile_text(group_key, user_key)
                    )
                elif action in {"删除存档", "删档", "delete"}:
                    confirmed = (
                        len(rest) == 1
                        and rest[0].lower() in {"确认", "confirm"}
                    )
                    if not confirmed:
                        yield event.plain_result(
                            "⚠️ 这会永久删除当前会话的档案、历史记录和未完成流程。\n"
                            "如需继续，请发送：/月计人生 删除存档 确认"
                        )
                    else:
                        await asyncio.to_thread(
                            self.store.delete_user_data, group_key, user_key
                        )
                        yield event.plain_result(
                            "当前会话的月计人生存档已永久删除。"
                        )
                elif action in {"记录", "历史", "history"}:
                    position = self._positive_int(rest[0]) if rest else 1
                    run = await asyncio.to_thread(
                        self.store.get_run, group_key, user_key, position
                    )
                    if run is None:
                        yield event.plain_result(f"没有找到倒数第 {position} 局记录。")
                    else:
                        yield event.plain_result(
                            format_summary(
                                run["summary"], run["seed"], run.get("details")
                            )
                        )
                        event.stop_event()
                        yield self._forward_result(event, run["trajectory"])
                elif action in {"放弃", "取消", "cancel"}:
                    await asyncio.to_thread(
                        self.store.clear_session, group_key, user_key
                    )
                    yield event.plain_result("已放弃当前未完成的开局。个人档案没有被删除。")
                elif action in {"继承", "inherit"}:
                    yield await self._inherit(event, group_key, user_key, rest)
                elif action in {"跳过", "skip"}:
                    yield await self._skip_inherit(event, group_key, user_key)
                elif action in {"天赋", "talent"}:
                    yield await self._choose_talents(group_key, user_key, rest, event)
                elif action in {"属性", "property", "prop"}:
                    yield event.plain_result("⏳ 正在推演完整人生，请稍候……")
                    event.stop_event()
                    results = await self._simulate(group_key, user_key, rest)
                    yield event.plain_result(results["summary_text"])
                    event.stop_event()
                    yield self._forward_result(event, results["trajectory"])
                    event.stop_event()
                    if results["achievement_text"]:
                        yield event.plain_result(results["achievement_text"])
                        event.stop_event()
                    yield event.plain_result(results["inherit_text"])
                elif not action or action in {"开始", "重开", "start", "restart"}:
                    force = bool(action)
                    yield event.plain_result(
                        await self._start(group_key, user_key, force=force)
                    )
                else:
                    yield event.plain_result(
                        f"未知操作“{args[0]}”。发送 /月计人生 帮助 查看指令。"
                    )
            except (EngineError, ValueError) as exc:
                logger.warning("月计人生指令失败: %s", exc)
                yield event.plain_result(f"⚠️ {exc}")
            except Exception as exc:
                logger.exception("月计人生发生未处理错误")
                yield event.plain_result("⚠️ 月计人生运行失败，请管理员查看 AstrBot 日志。")
            finally:
                event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def quick_reply(self, event: AstrMessageEvent):
        """在已开始的流程中直接接收数字，不要求重复输入命令前缀。"""
        message = event.get_message_str().strip()
        if not message:
            return

        if self._is_command_message(message):
            if not getattr(event, "_pm_life_handled", False):
                async for result in self.monthly_life(event):
                    yield result
            return

        normalized = message.replace("，", " ").replace(",", " ")
        values = normalized.split()
        skip = message in {"跳过", "不继承"}
        if not skip:
            if not values or len(values) > 8:
                return
            try:
                [int(value) for value in values]
            except ValueError:
                return

        user_id = event.get_sender_id()
        if not user_id:
            return
        user_key = str(user_id)
        group_key = build_scope_key(
            event.get_platform_name(), event.get_group_id(), user_key
        )
        session = await asyncio.to_thread(
            self.store.get_session, group_key, user_key
        )
        if not session:
            return

        phase = session.get("phase")
        if phase not in {"talent", "property", "inherit"}:
            return
        if skip and phase != "inherit":
            return

        event.stop_event()
        lock = self._user_locks.setdefault((group_key, user_key), asyncio.Lock())
        if lock.locked():
            yield event.plain_result("你的上一项操作仍在处理中，请稍候。")
            return

        async with lock:
            try:
                if phase == "talent":
                    yield await self._choose_talents(
                        group_key, user_key, values, event
                    )
                elif phase == "property":
                    yield event.plain_result("⏳ 正在推演完整人生，请稍候……")
                    results = await self._simulate(group_key, user_key, values)
                    yield event.plain_result(results["summary_text"])
                    yield self._forward_result(event, results["trajectory"])
                    if results["achievement_text"]:
                        yield event.plain_result(results["achievement_text"])
                    yield event.plain_result(results["inherit_text"])
                elif skip:
                    yield await self._skip_inherit(event, group_key, user_key)
                else:
                    yield await self._inherit(
                        event, group_key, user_key, values
                    )
            except (EngineError, ValueError) as exc:
                logger.warning("月计人生快捷回复失败: %s", exc)
                yield event.plain_result(f"⚠️ {exc}")
            except Exception:
                logger.exception("月计人生快捷回复发生未处理错误")
                yield event.plain_result(
                    "⚠️ 月计人生运行失败，请管理员查看 AstrBot 日志。"
                )
            finally:
                event.stop_event()

    async def _start(self, group_id: str, user_id: str, force: bool) -> str:
        session = await asyncio.to_thread(self.store.get_session, group_id, user_id)
        if session and not force:
            phase = session.get("phase")
            if phase == "talent":
                return format_talents(session.get("talents", []))
            if phase == "property":
                return format_property_prompt(
                    int(session["points"]), session.get("selected", [])
                )
            if phase == "inherit":
                return self._inherit_prompt(session.get("options", []))

        profile = await asyncio.to_thread(self.store.get_profile, group_id, user_id)
        seed = secrets.token_hex(12)
        result = await self.engine.request("draw", profile=profile, seed=seed)
        session = {
            "phase": "talent",
            "seed": seed,
            "talents": result["talents"],
        }
        await asyncio.to_thread(
            self.store.save_session, group_id, user_id, session
        )
        return format_talents(result["talents"])

    async def _choose_talents(
        self,
        group_id: str,
        user_id: str,
        values: list[str],
        event: AstrMessageEvent,
    ):
        if len(values) != 4:
            return event.plain_result("请直接回复 4 个天赋编号，例如：1 2 3 4")
        try:
            indexes = [int(value) for value in values]
        except ValueError as exc:
            raise ValueError("天赋编号必须是整数") from exc
        session = await asyncio.to_thread(self.store.get_session, group_id, user_id)
        if not session or session.get("phase") not in {"talent", "property"}:
            raise ValueError("当前没有等待选择天赋的开局，请先发送 /月计人生")
        profile = await asyncio.to_thread(self.store.get_profile, group_id, user_id)
        result = await self.engine.request(
            "prepare",
            profile=profile,
            seed=session["seed"],
            indexes=indexes,
        )
        session.update(
            {
                "phase": "property",
                "indexes": indexes,
                "selected": result["selected"],
                "points": result["points"],
            }
        )
        await asyncio.to_thread(
            self.store.save_session, group_id, user_id, session
        )
        return event.plain_result(
            format_property_prompt(result["points"], result["selected"])
        )

    async def _simulate(
        self, group_id: str, user_id: str, values: list[str]
    ) -> dict[str, Any]:
        if len(values) != 4:
            raise ValueError(
                "请依次回复运气、智力、体质、家境，例如：5 5 5 5"
            )
        try:
            numbers = [int(value) for value in values]
        except ValueError as exc:
            raise ValueError("属性值必须是整数") from exc
        session = await asyncio.to_thread(self.store.get_session, group_id, user_id)
        if not session or session.get("phase") != "property":
            raise ValueError("当前没有等待分配属性的开局，请先发送 /月计人生")
        profile = await asyncio.to_thread(self.store.get_profile, group_id, user_id)
        allocation = dict(zip(["CHR", "INT", "STR", "MNY"], numbers))
        result = await self.engine.request(
            "simulate",
            profile=profile,
            seed=session["seed"],
            indexes=session["indexes"],
            allocation=allocation,
        )
        inherit_session = {
            "phase": "inherit",
            "options": result["selected"],
        }
        await asyncio.to_thread(
            self.store.complete_run,
            group_id,
            user_id,
            result["profile"],
            inherit_session,
            session["seed"],
            {
                "selected": result["selected"],
                "allocation": result["allocation"],
                "points": result["points"],
                "replacements": result["replacements"],
                "engine": result["engine"],
            },
            result["summary"],
            result["trajectory"],
        )
        return {
            "summary_text": format_summary(
                result["summary"],
                session["seed"],
                {"selected": result["selected"], "allocation": result["allocation"]},
            ),
            "trajectory": result["trajectory"],
            "achievement_text": format_achievements(result["achievements"]),
            "inherit_text": self._inherit_prompt(result["selected"]),
        }

    async def _inherit(
        self,
        event: AstrMessageEvent,
        group_id: str,
        user_id: str,
        values: list[str],
    ):
        if len(values) != 1:
            return event.plain_result("请直接回复一个继承编号，例如：2")
        index = self._positive_int(values[0])
        session = await asyncio.to_thread(self.store.get_session, group_id, user_id)
        if not session or session.get("phase") != "inherit":
            return event.plain_result("当前没有等待继承的天赋。")
        options = session.get("options", [])
        if index > len(options):
            return event.plain_result(f"继承编号必须在 1～{len(options)} 之间。")
        talent = options[index - 1]
        profile = await asyncio.to_thread(self.store.get_profile, group_id, user_id)
        result = await self.engine.request(
            "inherit", profile=profile, talentId=talent["id"]
        )
        await asyncio.to_thread(
            self.store.save_profile_and_session,
            group_id,
            user_id,
            result["profile"],
            None,
        )
        return event.plain_result(
            f"已继承天赋【{talent['name']}】。再次发送 /月计人生 开始下一局。"
        )

    async def _skip_inherit(
        self, event: AstrMessageEvent, group_id: str, user_id: str
    ):
        session = await asyncio.to_thread(self.store.get_session, group_id, user_id)
        if not session or session.get("phase") != "inherit":
            return event.plain_result("当前没有等待继承的天赋。")
        profile = await asyncio.to_thread(self.store.get_profile, group_id, user_id)
        result = await self.engine.request("inherit", profile=profile, talentId=None)
        await asyncio.to_thread(
            self.store.save_profile_and_session,
            group_id,
            user_id,
            result["profile"],
            None,
        )
        return event.plain_result("已跳过天赋继承。再次发送 /月计人生 开始下一局。")

    async def _profile_text(self, group_id: str, user_id: str) -> str:
        profile = await asyncio.to_thread(self.store.get_profile, group_id, user_id)
        counts = profile_counts(profile)
        return (
            "📁 当前会话个人档案\n"
            f"重开次数：{counts['times']}\n"
            f"收集天赋：{counts['talents']}\n"
            f"经历事件：{counts['events']}\n"
            f"解锁成就：{counts['achievements']}\n"
            "群聊与私聊档案相互独立。"
        )

    def _forward_result(
        self, event: AstrMessageEvent, trajectory: list[dict[str, Any]]
    ):
        chunks = chunk_trajectory(trajectory, self.forward_chunk_chars)
        uin = self._node_uin(event)
        nodes = [
            Node(
                uin=uin,
                name="月计人生",
                content=[Plain(f"人生轨迹 {index}/{len(chunks)}\n{chunk}")],
            )
            for index, chunk in enumerate(chunks, 1)
        ]
        return event.chain_result(nodes)

    @staticmethod
    def _inherit_prompt(options: list[dict[str, Any]]) -> str:
        lines = ["请选择一个本局天赋继承到下一局："]
        for index, talent in enumerate(options, 1):
            lines.append(f"{index}. {talent['name']}：{talent['description']}")
        lines.extend(["", "直接回复编号，例如：1", "不继承请回复：跳过"])
        return "\n".join(lines)

    @staticmethod
    def _parse_args(event: AstrMessageEvent) -> list[str]:
        message = event.get_message_str().strip()
        for marker in ("月计人生", "pmlife", "pm人生"):
            index = message.lower().find(marker)
            if index >= 0:
                return message[index + len(marker) :].strip().split()
        return []

    @staticmethod
    def _is_command_message(message: str) -> bool:
        normalized = message.strip()
        if normalized.startswith(("/", "／")):
            normalized = normalized[1:].lstrip()
        lowered = normalized.lower()
        return any(
            lowered == name or lowered.startswith(f"{name} ")
            for name in ("月计人生", "pmlife", "pm人生")
        )

    @staticmethod
    def _positive_int(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise ValueError("编号必须是正整数") from exc
        if number < 1:
            raise ValueError("编号必须是正整数")
        return number

    @staticmethod
    def _node_uin(event: AstrMessageEvent) -> int:
        for value in (event.get_self_id(), event.get_sender_id()):
            try:
                return int(str(value))
            except (TypeError, ValueError):
                continue
        return 10000

    def _config_get(self, key: str, default: Any) -> Any:
        getter = getattr(self.config, "get", None)
        if callable(getter):
            return getter(key, default)
        return default

    def _config_int(
        self, key: str, default: int, minimum: int, maximum: int
    ) -> int:
        try:
            value = int(self._config_get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _help_text() -> str:
        return (
            "🌙 月计人生指令\n"
            "/月计人生 —— 开始或查看当前步骤\n"
            "如果中文命令未被框架识别，也可发送 /pmlife\n"
            "开局后直接回复数字即可继续，无需重复输入 /月计人生\n"
            "/月计人生 重开 —— 放弃当前步骤并重新抽取\n"
            "/月计人生 天赋 1 2 3 4 —— 选择四个天赋\n"
            "/月计人生 属性 5 5 5 5 —— 分配运气/智力/体质/家境\n"
            "/月计人生 继承 1 —— 继承结局天赋\n"
            "/月计人生 跳过 —— 不继承天赋\n"
            "/月计人生 档案 —— 查看当前会话个人档案\n"
            "/月计人生 记录 [序号] —— 查看最近人生，1 为最新\n"
            "/月计人生 放弃 —— 清除未完成步骤\n"
            "/月计人生 删除存档 确认 —— 永久删除当前会话存档\n\n"
            "游戏使用本地 JavaScript 规则引擎，不调用大模型、不消耗 Token。"
        )

    async def terminate(self) -> None:
        await self.engine.close()
