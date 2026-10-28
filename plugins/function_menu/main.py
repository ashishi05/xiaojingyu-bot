import re

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from data.plugins.emoji_guess.game import (
    GUESS_GAMES,
    LAST_GAMES,
    occupied_game,
    send_guess_menu,
)
from data.plugins.emoji_guess.main import native_scope, slash_text

MENU = """小鲸鱼 · 功能

• 聊天、写作
• 查资料、看图片
• 发送、收藏和整理表情
• 拍一拍、撤回消息、定时提醒
• 处理文件、文档和表格
• 电脑截图、自动操作
• Emoji 猜角色（LOL／瓦／星铁）：/猜角色
• Emoji 猜国家（42 国）：/猜国家
• Emoji 猜游戏（55 题）：/猜游戏
• Emoji 猜知名人物（71 人）：/猜知名人物
• Emoji 猜网络人物（55 题）：/猜网络人物
• Emoji 猜成语（481 题）：/猜成语
• 猜假冷知识（三选一）：/猜假冷知识
• 猜猜杯总菜单：/猜（或 /猜菜单、/猜猜猜）

直接告诉我想做什么就好。
停止桌面操作：/桌面停止"""

# shortcut: static menu for this deployment; update when available features change.
TRIGGER = re.compile(
    r"/?(?:功能菜单|菜单|你有什么功能|你有哪些功能|(?:发|发个|发一下|给我发|给我发个|给我发一下|看看|查看|打开)(?:功能菜单|菜单))[？?！!。~～]*"
)


@register("function_menu", "Local", "私聊功能菜单与用法", "1.0.0")
class FunctionMenu(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("猜菜单", alias={"猜猜猜", "猜", "换个猜"}, priority=200010)
    async def guess_menu(self, event: AstrMessageEvent):
        """List enabled Emoji games, including during an active match.

        Args:
            event: Native QQ command event.
        """
        if slash_text(event) is not None:
            await send_guess_menu(self.context, event)

    @filter.command("继续", priority=200009)
    async def continue_game(self, event: AstrMessageEvent):
        """Start another match of the last finished game with a slash command.

        Args:
            event: Native QQ slash command.
        """
        if slash_text(event) != "继续":
            return
        scope = native_scope(event)
        active = occupied_game(self.context, scope, "")
        previous = LAST_GAMES.get(scope)
        event.stop_event()
        for name, _ in GUESS_GAMES:
            event.set_extra(name + "_gameplay", True)
        if active:
            await event.send(event.plain_result("本轮尚未结束；/结束 会结算整场并清零"))
            return
        if previous is None:
            await send_guess_menu(self.context, event)
            return
        manager, mode = previous
        try:
            await manager.start(scope, str(event.get_sender_id()), mode)
        except (ValueError, RuntimeError) as exc:
            await event.send(event.plain_result(str(exc)))

    @filter.command("结束", priority=200008)
    async def end_game(self, event: AstrMessageEvent):
        """Consume game endings before sleep or ordinary chat handling.

        Args:
            event: Native QQ slash command.
        """
        if slash_text(event) != "结束":
            return
        scope = native_scope(event)
        event.stop_event()
        for name, _ in GUESS_GAMES:
            event.set_extra(name + "_gameplay", True)
        for name, _ in GUESS_GAMES:
            metadata = self.context.get_registered_star(name)
            instance = metadata.star_cls if metadata and metadata.activated else None
            if instance and (
                scope in instance.manager.sessions
                or scope in getattr(instance, "pending", {})
            ):
                await instance.game_command(event, "结束")
                return
        raw = event.message_obj.raw_message
        role = raw.get("sender", {}).get("role") if isinstance(raw, dict) else None
        admin = event.is_admin() or role in ("admin", "owner")
        for name, _ in GUESS_GAMES:
            metadata = self.context.get_registered_star(name)
            if metadata and metadata.activated:
                try:
                    if await metadata.star_cls.manager.stop(
                        scope, str(event.get_sender_id()), admin
                    ):
                        return
                except PermissionError as exc:
                    await event.send(event.plain_result(str(exc)))
                    return
        await event.send(event.plain_result("当前没有进行中的猜猜杯"))
        await send_guess_menu(self.context, event)

    @filter.command("积分", priority=200007)
    async def cup_score(self, event: AstrMessageEvent):
        """Show the same cup total during play and between rounds.

        Args:
            event: Native QQ slash command.
        """
        if slash_text(event) != "积分":
            return
        event.stop_event()
        for name, _ in GUESS_GAMES:
            event.set_extra(name + "_gameplay", True)
        for name, _ in GUESS_GAMES:
            metadata = self.context.get_registered_star(name)
            if metadata and metadata.activated:
                await event.send(
                    event.plain_result(
                        metadata.star_cls.manager.leaderboard(native_scope(event))
                    )
                )
                return

    @filter.on_waiting_llm_request(priority=100)
    async def show_menu(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() != "aiocqhttp"
            or event.get_group_id()
            or str(event.get_sender_id()) not in {"10001", "10002"}
            or not TRIGGER.fullmatch((event.message_str or "").strip())
        ):
            return
        await event.send(event.plain_result(MENU))
        event.stop_event()
