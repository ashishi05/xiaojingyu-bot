"""Independent network-persona games using the existing Emoji round engine."""

import json
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register
from data.plugins.emoji_guess.game import GameManager, occupied_game
from data.plugins.emoji_guess.lookup import AliasLookup
from data.plugins.emoji_guess.main import is_other_command, slash_text

HELP = """猜网络人物 · 55 位网络人物
/猜网络人物：开局，每局 5 题
答题：/名字，每人每阶段一次
答对得 3/2/1 分
/提示：追加 Emoji，重置答题次数
/揭秘：三个 Emoji 后公布答案
/结束：本场开局者或管理员结算整场并清零
/继续：沿用游戏和选池再开一轮，积分累计
/猜网络人物 积分：查看本场总积分（五种玩法通用）
名称无法确认时不占次数；不会自动提示或超时揭晓
每轮 5 题，换玩法不清零；/结束 才结算并清零，历史记录保留"""

_plugin = None


def native_scope(event: AstrMessageEvent) -> str:
    """Return the real QQ destination rather than shared LLM history.

    Args:
        event: Incoming native QQ event.

    Returns:
        Original platform/group/user origin.
    """
    group = str(event.get_group_id() or "")
    return f"{event.get_platform_id()}:{'GroupMessage' if group else 'FriendMessage'}:{group or event.get_sender_id()}"


class NetworkPersonAnswerFilter(filter.CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        if _plugin is None or event.get_platform_name() not in ("aiocqhttp", "qq_official", "qq_official_webhook"):
            return False
        scope = native_scope(event)
        if scope not in _plugin.manager.sessions:
            return False
        event.set_extra(
            "network_person_guess_answer",
            (scope, (event.message_str or "").strip(), time.perf_counter()),
        )
        return True


@register(
    "network_person_guess",
    "Local",
    "Emoji 猜网络人物：55 题，整场累计积分与手动线索",
    "1.0.0",
)
class NetworkPersonGuess(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        global _plugin
        questions = json.loads(
            (Path(__file__).parent / "questions.json").read_text("utf-8")
        )
        self.manager = GameManager(
            questions,
            StarTools.get_data_dir("network_person_guess"),
            self._send,
            pools={"network_person": "55 位网络人物"},
            title="猜网络人物",
            show_explanation=False,
        )
        self.lookup = AliasLookup(context, questions, network=True)
        self.manager.resolve_alias = self.lookup.resolve
        _plugin = self
        logger.info("NetworkPerson pool loaded: %s questions", len(questions))

    async def _send(self, scope: str, text: str):
        return await self.context.send_message(scope, MessageChain().message(text))

    @filter.command("猜网络人物", priority=600)
    async def game_command(self, event: AstrMessageEvent, action: str = ""):
        """Start or control a famous-person match without a pool selection menu.

        Args:
            event: Incoming QQ command.
            action: Optional help, score or gameplay control.
        """
        if slash_text(event) is None:
            return
        event.stop_event()
        event.set_extra("network_person_guess_gameplay", True)
        scope = native_scope(event)
        action = action.strip().casefold()
        try:
            if not action:
                other_title = occupied_game(self.context, scope, "network_person_guess")
                if other_title:
                    await event.send(
                        event.plain_result(
                            f"本会话正在{other_title}，本轮结束后可换玩法；/结束 会结算整场。目标玩法：/猜网络人物"
                        )
                    )
                    return
                await self.manager.start(
                    scope, str(event.get_sender_id()), "network_person"
                )
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
                if not await self.manager.stop(
                    scope,
                    str(event.get_sender_id()),
                    event.is_admin() or role in ("admin", "owner"),
                ):
                    await event.send(event.plain_result("当前没有进行中的猜网络人物"))
            elif action == "积分":
                await event.send(event.plain_result(self.manager.leaderboard(scope)))
            else:
                await event.send(event.plain_result(HELP))
        except (ValueError, PermissionError) as exc:
            await event.send(event.plain_result(str(exc)))
        except Exception as exc:  # noqa: BLE001 - the engine cancels failed matches.
            logger.exception("NetworkPerson command failed: %s", exc)
            await event.send(event.plain_result("猜网络人物暂时出错，请稍后重试"))

    @filter.custom_filter(NetworkPersonAnswerFilter, priority=200004)
    async def answer(self, event: AstrMessageEvent):
        event.stop_event()
        event.set_extra("network_person_guess_gameplay", True)
        payload = event.get_extra("network_person_guess_answer")
        if payload is None:
            return
        scope, _, received_at = payload
        text = slash_text(event)
        if not text:
            return
        command = text.split(maxsplit=1)
        if command and command[0] == "猜网络人物":
            await self.game_command(event, command[1] if len(command) > 1 else "")
            return
        if command and command[0] in (
            "猜假冷知识",
            "猜角色",
            "猜国家",
            "猜游戏",
            "猜知名人物",
            "猜成语",
        ):
            await event.send(
                event.plain_result(
                    f"本会话正在猜网络人物，本轮结束后可换玩法；/结束 会结算整场。目标玩法：/{command[0]}"
                )
            )
            return
        if text in ("提示", "揭秘", "结束", "积分", "帮助"):
            await self.game_command(event, text)
            return
        if is_other_command(text):
            await event.send(event.plain_result("游戏中，请先 /结束 再使用其他功能"))
            return
        candidate = text
        if not candidate or len(candidate) > 80 or candidate.startswith("/"):
            return
        try:
            await self.manager.guess(
                scope,
                str(event.get_sender_id()),
                event.get_sender_name(),
                candidate,
                received_at,
            )
        except Exception as exc:  # noqa: BLE001 - the engine cancels failed matches.
            logger.exception("NetworkPerson guess failed: %s", exc)

    @filter.on_waiting_llm_request(priority=200004)
    async def guard_chat(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() in ("aiocqhttp", "qq_official", "qq_official_webhook")
            and native_scope(event) in self.manager.sessions
        ):
            event.stop_event()

    @filter.on_decorating_result(priority=200004)
    async def guard_reply(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() in ("aiocqhttp", "qq_official", "qq_official_webhook")
            and native_scope(event) in self.manager.sessions
            and not event.get_extra("network_person_guess_gameplay")
        ):
            event.clear_result()
            event.stop_event()

    async def terminate(self):
        global _plugin
        if _plugin is self:
            _plugin = None
        await self.manager.close()
