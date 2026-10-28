"""Three-choice trivia rounds integrated with the shared guessing cup."""

import json
import time
import unicodedata
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register
from data.plugins.emoji_guess.game import GUESS_GAMES, GameManager, occupied_game
from data.plugins.emoji_guess.main import is_other_command, slash_text

HELP = """猜假冷知识 · 三条陈述中有两真一假
/猜假冷知识：开局，每轮5题
/1、/2、/3：选出假的一条，每人每题一次
答对 +3 分；答错不扣分
/揭秘：公布答案并进入下一题
/积分：查看猜猜杯本场总分
/继续：再来一轮，积分累计
/换个猜：选择其他玩法
/结束：本场开局者或管理员结算整场并清零"""

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


class TriviaAnswerFilter(filter.CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        if _plugin is None or event.get_platform_name() != "aiocqhttp":
            return False
        scope = native_scope(event)
        if scope not in _plugin.manager.sessions:
            return False
        event.set_extra(
            "trivia_guess_answer",
            (scope, (event.message_str or "").strip(), time.perf_counter()),
        )
        return True


@register(
    "trivia_guess", "Local", "生活趣闻与反直觉知识，五题一轮，共享猜猜杯积分", "1.1.0"
)
class TriviaGuess(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        global _plugin
        questions = json.loads(
            (Path(__file__).parent / "questions.json").read_text("utf-8")
        )
        self.manager = GameManager(
            questions,
            StarTools.get_data_dir("trivia_guess"),
            self._send,
            pools={"trivia": "真假冷知识"},
            title="猜假冷知识",
            show_explanation=True,
        )
        _plugin = self
        logger.info("Trivia pool loaded: %s questions", len(questions))

    async def _send(self, scope: str, text: str):
        """Append brief notes only after a choice answer has been revealed.

        Args:
            scope: Native QQ destination.
            text: Game output prepared by the shared manager.

        Returns:
            The transport's delivery result.
        """
        match = self.manager.sessions.get(scope)
        if match and text.startswith(("✅", "揭秘 ·")):
            notes = "\n".join(
                f"{index}. {option['explanation']}"
                for index, option in enumerate(match.question["options"], 1)
                if option.get("explanation")
            )
            if notes:
                text += "\n\n小知识：\n" + notes
        return await self.context.send_message(scope, MessageChain().message(text))

    @filter.command("猜假冷知识", priority=600)
    async def game_command(self, event: AstrMessageEvent, action: str = ""):
        """Start or control a trivia match without a pool selection menu.

        Args:
            event: Incoming QQ command.
            action: Optional help, score or gameplay control.
        """
        if slash_text(event) is None:
            return
        event.stop_event()
        event.set_extra("trivia_guess_gameplay", True)
        scope = native_scope(event)
        action = action.strip().casefold()
        try:
            if not action:
                other_title = occupied_game(self.context, scope, "trivia_guess")
                if other_title:
                    await event.send(
                        event.plain_result(
                            f"本会话正在{other_title}，本轮结束后可换玩法；/结束 会结算整场。目标玩法：/猜假冷知识"
                        )
                    )
                    return
                await self.manager.start(scope, str(event.get_sender_id()), "trivia")
            elif action == "提示":
                await event.send(
                    event.plain_result(
                        "本玩法没有额外提示，用 /1、/2、/3 答题，或 /揭秘 公布答案"
                    )
                )
            elif action == "揭秘":
                if not await self.manager.reveal(scope):
                    await event.send(event.plain_result("当前没有可揭秘的题目"))
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
                    await event.send(event.plain_result("当前没有进行中的猜假冷知识"))
            elif action == "积分":
                await event.send(event.plain_result(self.manager.leaderboard(scope)))
            else:
                await event.send(event.plain_result(HELP))
        except (ValueError, PermissionError) as exc:
            await event.send(event.plain_result(str(exc)))
        except Exception as exc:  # noqa: BLE001 - the engine cancels failed matches.
            logger.exception("Trivia command failed: %s", exc)
            await event.send(event.plain_result("猜假冷知识暂时出错，请稍后重试"))

    @filter.custom_filter(TriviaAnswerFilter, priority=200006)
    async def answer(self, event: AstrMessageEvent):
        event.stop_event()
        event.set_extra("trivia_guess_gameplay", True)
        payload = event.get_extra("trivia_guess_answer")
        if payload is None:
            return
        scope, _, received_at = payload
        text = slash_text(event)
        if not text:
            return
        command = text.split(maxsplit=1)
        if command and command[0] == "猜假冷知识":
            await self.game_command(event, command[1] if len(command) > 1 else "")
            return
        if command and command[0] in {name for _, name in GUESS_GAMES}:
            await event.send(
                event.plain_result(
                    f"本会话正在猜假冷知识，本轮结束后可换玩法；/结束 会结算整场。目标玩法：/{command[0]}"
                )
            )
            return
        if text in ("提示", "揭秘", "结束", "积分", "帮助"):
            await self.game_command(event, text)
            return
        if is_other_command(text):
            await event.send(event.plain_result("游戏中，请先 /结束 再使用其他功能"))
            return
        candidate = unicodedata.normalize("NFKC", text).strip()
        if candidate not in {"1", "2", "3"}:
            await event.send(
                event.plain_result("请用 /1、/2、/3 选择假的一条；每人每题只能答一次")
            )
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
            logger.exception("Trivia guess failed: %s", exc)

    @filter.on_waiting_llm_request(priority=200006)
    async def guard_chat(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() == "aiocqhttp"
            and native_scope(event) in self.manager.sessions
        ):
            event.stop_event()

    @filter.on_decorating_result(priority=200006)
    async def guard_reply(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() == "aiocqhttp"
            and native_scope(event) in self.manager.sessions
            and not event.get_extra("trivia_guess_gameplay")
        ):
            event.clear_result()
            event.stop_event()

    async def terminate(self):
        global _plugin
        if _plugin is self:
            _plugin = None
        await self.manager.close()
