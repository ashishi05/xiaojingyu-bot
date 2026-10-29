"""AstrBot entry points for local Emoji games."""

import json
import re
import time
import unicodedata
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Plain, Reply
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.star_handler import EventType, star_handlers_registry

from .game import GameManager, occupied_game, send_guess_menu
from .lookup import AliasLookup

HELP = """猜角色 · 选池：1 英雄联盟 · 2 无畏契约 · 3 星穹铁道，可组合 1+2
/猜角色：开局，每局 5 题
答题：/名字，每人每阶段一次
答对得 3/2/1 分
/提示：追加 Emoji，重置答题次数
/揭秘：三个 Emoji 后公布答案
/结束：本场开局者或管理员结算整场并清零
/继续：沿用游戏和选池再开一轮，积分累计
/猜角色 积分：查看本场总积分（五种玩法通用）
名称无法确认时不占次数；不会自动提示或超时揭晓
每轮 5 题，换玩法不清零；/结束 才结算并清零，历史记录保留"""

POOL_MENU = """猜角色 · 选池
• 1 英雄联盟
• 2 无畏契约
• 3 星穹铁道
/选池 编号，可组合 /选池 1+2 或 /选池 1 2 3
/结束：结算整场并回到选游戏"""

_plugin = None


def native_scope(event: AstrMessageEvent) -> str:
    """Use the real destination instead of shared LLM-history session IDs.

    Args:
        event: Native OneBot message.

    Returns:
        Original platform/group/user message origin.
    """
    group = str(event.get_group_id() or "")
    return f"{event.get_platform_id()}:{'GroupMessage' if group else 'FriendMessage'}:{group or event.get_sender_id()}"


def allowed_input(event: AstrMessageEvent, require_mention: bool = False) -> bool:
    """Keep game input to actual text directed at this bot or the room.

    Args:
        event: Incoming message.
        require_mention: Require an actual bot At component for gameplay text.

    Returns:
        Whether the message may participate in game routing.
    """
    if event.get_platform_name() not in ("aiocqhttp", "qq_official", "qq_official_webhook") or str(event.get_sender_id()) == str(
        event.get_self_id()
    ):
        return False
    raw = event.message_obj.raw_message
    if isinstance(raw, dict) and raw.get("post_type", "message") != "message":
        return False
    parts = event.get_messages() or []
    if any(not isinstance(part, (Plain, At, Reply)) for part in parts):
        return False
    mentions = [str(part.qq) for part in parts if isinstance(part, At)]
    return str(event.get_self_id()) in mentions or (
        not require_mention and not mentions
    )


def slash_text(event: AstrMessageEvent) -> str | None:
    """Read slash input before wake processing removes its prefix.

    Args:
        event: Incoming QQ event with original message components.

    Returns:
        Command body, or None for ordinary chat and unsupported input.
    """
    if not allowed_input(event):
        return None
    text = "".join(
        part.text for part in event.get_messages() if isinstance(part, Plain)
    ).strip()
    return text[1:].strip() if text.startswith("/") else None


def is_other_command(text: str) -> bool:
    """Recognize installed commands before an input reaches alias lookup.

    Args:
        text: Slash command body from the original message.

    Returns:
        Whether the input belongs to another bot feature.
    """
    # These features use event/LLM hooks rather than registered command filters.
    if text.split(maxsplit=1)[0] in {
        "菜单",
        "功能菜单",
        "发送文件",
        "桌面停止",
        "桌面继续",
        "桌面截图",
        "桌面确认",
    }:
        return True
    for handler in star_handlers_registry.get_handlers_by_event_type(
        EventType.AdapterMessageEvent
    ):
        for command_filter in handler.event_filters:
            if isinstance(command_filter, (CommandFilter, CommandGroupFilter)) and any(
                text == name or text.startswith(name + " ")
                for name in command_filter.get_complete_command_names()
            ):
                return True
    return False


class GameAnswerFilter(filter.CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        if _plugin is None or event.get_platform_name() not in ("aiocqhttp", "qq_official", "qq_official_webhook"):
            return False
        scope = native_scope(event)
        if scope not in _plugin.manager.sessions and scope not in _plugin.pending:
            return False
        event.set_extra(
            "emoji_guess_answer",
            (scope, (event.message_str or "").strip(), time.perf_counter()),
        )
        return True


@register("emoji_guess", "Local", "Emoji 猜角色：LOL、无畏契约与星穹铁道抢答", "1.0.0")
class EmojiGuess(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        global _plugin
        questions = json.loads(
            (Path(__file__).parent / "questions.json").read_text("utf-8")
        )
        self.manager = GameManager(
            questions, StarTools.get_data_dir("emoji_guess"), self._send
        )
        self.pending = {}
        self.lookup = AliasLookup(context, questions)
        self.manager.resolve_alias = self.lookup.resolve
        _plugin = self
        logger.info(
            "Emoji game loaded: 173 LOL, 30 VALORANT and 93 Star Rail questions"
        )

    async def _send(self, scope: str, text: str):
        return await self.context.send_message(scope, MessageChain().message(text))

    @filter.command("猜角色", priority=600)
    async def game_command(self, event: AstrMessageEvent, action: str = ""):
        """Start or control an Emoji match in the current native conversation.

        Args:
            event: Command event.
            action: Game mode or a control subcommand.
        """
        if slash_text(event) is None:
            return
        event.stop_event()
        event.set_extra("emoji_guess_gameplay", True)
        scope = native_scope(event)
        action = action.strip().casefold()
        try:
            if not action:
                other_title = occupied_game(self.context, scope, "emoji_guess")
                if other_title:
                    await event.send(
                        event.plain_result(
                            f"本会话正在{other_title}，本轮结束后可换玩法；/结束 会结算整场。目标玩法：/猜角色"
                        )
                    )
                    return
                if scope in self.manager.sessions:
                    await event.send(
                        event.plain_result("本会话已有游戏，请先结束当前局")
                    )
                    return
                if scope in self.pending and self.pending[scope] != str(
                    event.get_sender_id()
                ):
                    await event.send(event.plain_result("请等待开局者选择角色池"))
                    return
                self.pending[scope] = str(event.get_sender_id())
                await event.send(event.plain_result(POOL_MENU))
            elif action == "提示":
                if not await self.manager.hint(scope):
                    match = self.manager.sessions.get(scope)
                    await event.send(
                        event.plain_result(
                            "可揭秘或继续答题"
                            if match
                            and match.phase == "answering"
                            and match.hint_count == 2
                            else "当前没有可追加的提示，等下一题吧"
                        )
                    )
            elif action == "揭秘":
                if not await self.manager.reveal(scope):
                    await event.send(
                        event.plain_result("需先揭晓三个 Emoji，才可以揭秘当前题")
                    )
            elif action == "结束":
                raw = event.message_obj.raw_message
                role = (
                    raw.get("sender", {}).get("role") if isinstance(raw, dict) else None
                )
                admin = event.is_admin() or role in ("admin", "owner")
                if scope in self.pending:
                    if self.pending[scope] != str(event.get_sender_id()) and not admin:
                        raise PermissionError("只有开局者或管理员能取消选池")
                    ended = await self.manager.stop(
                        scope, str(event.get_sender_id()), admin
                    )
                    self.pending.pop(scope)
                    if not ended:
                        await send_guess_menu(self.context, event)
                    return
                if not await self.manager.stop(
                    scope, str(event.get_sender_id()), admin
                ):
                    await event.send(event.plain_result("当前没有进行中的猜角色"))
            elif action == "积分":
                await event.send(event.plain_result(self.manager.leaderboard(scope)))
            else:
                await event.send(event.plain_result(HELP))
        except (ValueError, PermissionError) as exc:
            await event.send(event.plain_result(str(exc)))
        except Exception as exc:  # noqa: BLE001 - manager owns match cleanup.
            logger.exception("Emoji command failed: %s", exc)

    @filter.custom_filter(GameAnswerFilter, priority=200000)
    async def answer(self, event: AstrMessageEvent):
        event.stop_event()
        event.set_extra("emoji_guess_gameplay", True)
        payload = event.get_extra("emoji_guess_answer")
        if payload is None:
            return
        scope, _, received_at = payload
        text = slash_text(event)
        if not text:
            return
        command = text.split(maxsplit=1)
        if command and command[0] == "猜角色":
            await self.game_command(event, command[1] if len(command) > 1 else "")
            return
        if command and command[0] in (
            "猜假冷知识",
            "猜国家",
            "猜游戏",
            "猜知名人物",
            "猜网络人物",
            "猜成语",
        ):
            await event.send(
                event.plain_result(
                    f"本会话正在猜角色，本轮结束后可换玩法；/结束 会结算整场。目标玩法：/{command[0]}"
                )
            )
            return
        if text in ("提示", "揭秘", "结束", "积分", "帮助"):
            await self.game_command(event, text)
            return
        if is_other_command(text):
            await event.send(event.plain_result("游戏中，请先 /结束 再使用其他功能"))
            return
        if scope in self.pending:
            text = text[3:].strip() if text.startswith("选池 ") else text
            if self.pending[scope] != str(event.get_sender_id()):
                await event.send(event.plain_result("请由开局者选择角色池"))
                return
            choices = set(
                re.split(r"[+,，、;；\s]+", unicodedata.normalize("NFKC", text).strip())
            )
            if not choices or not choices <= {"1", "2", "3"}:
                await event.send(
                    event.plain_result(
                        "编号不对，请选 1、2、3 或组合，如 1+3、1+2+3；逗号和空格也可以"
                    )
                )
                return
            mode = (
                "mixed"
                if choices == {"1", "2"}
                else "+".join(
                    {"1": "lol", "2": "val", "3": "hsr"}[n] for n in sorted(choices)
                )
            )
            self.pending.pop(scope)
            try:
                await self.manager.start(scope, str(event.get_sender_id()), mode)
            except Exception as exc:  # noqa: BLE001 - manager owns match cleanup.
                logger.exception("Emoji pool selection failed: %s", exc)
                await event.send(event.plain_result("开局失败，请重新发送 /猜角色"))
            return
        candidate = text
        if not candidate or len(candidate) > 32 or candidate.startswith("/"):
            return
        try:
            await self.manager.guess(
                scope,
                str(event.get_sender_id()),
                event.get_sender_name(),
                candidate,
                received_at,
            )
        except Exception as exc:  # noqa: BLE001 - manager owns match cleanup.
            logger.exception("Emoji answer failed: %s", exc)

    @filter.on_waiting_llm_request(priority=200000)
    async def guard_chat(self, event: AstrMessageEvent):
        if event.get_platform_name() in ("aiocqhttp", "qq_official", "qq_official_webhook") and (
            native_scope(event) in self.manager.sessions
            or native_scope(event) in self.pending
        ):
            event.stop_event()

    @filter.on_decorating_result(priority=200000)
    async def guard_reply(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() in ("aiocqhttp", "qq_official", "qq_official_webhook")
            and (
                native_scope(event) in self.manager.sessions
                or native_scope(event) in self.pending
            )
            and not event.get_extra("emoji_guess_gameplay")
        ):
            event.clear_result()
            event.stop_event()

    async def terminate(self):
        global _plugin
        if _plugin is self:
            _plugin = None
        self.pending.clear()
        await self.manager.close()
