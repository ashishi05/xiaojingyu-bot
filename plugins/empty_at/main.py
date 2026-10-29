"""空艾特处理：有人只 @ 不说话时，读最近几条聊天记录当上下文。

- 上几条：拉最近 N 条消息（跳过机器人自己），拼进 system_prompt
- 下几条：AstrBot 内置 empty_mention_waiting 已经会等 60 秒，对方补发会被重新入队
- 同时把内置的「问他想要聊什么」换成「结合上下文自然接话」
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

_HISTORY_COUNT = 8


def _find_bot(context: Context):
    try:
        for inst in context.platform_manager.platform_insts:
            bot = getattr(inst, "bot", None)
            if bot is not None:
                return bot
    except Exception as e:
        logger.warning(f"[empty_at] 获取平台实例失败: {e}")
    return None


def _fmt_sender(sender: dict) -> str:
    if not sender:
        return "某人"
    return (
        sender.get("card")
        or sender.get("nickname")
        or sender.get("user_id")
        or "某人"
    )


@register("empty_at", "Local", "空艾特时自动读上下文", "1.0.0")
class EmptyAt(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def _pull_history(self, event: AstrMessageEvent, bot) -> list[str]:
        self_id = str(getattr(bot, "self_id", "") or "")
        try:
            if event.get_group_id():
                resp = await bot.call_action(
                    action="get_group_msg_history",
                    group_id=int(event.get_group_id()),
                    count=_HISTORY_COUNT,
                )
            else:
                resp = await bot.call_action(
                    action="get_friend_msg_history",
                    user_id=int(event.get_sender_id()),
                    count=_HISTORY_COUNT,
                )
        except Exception as e:
            logger.warning(f"[empty_at] 拉历史失败: {e}")
            return []

        if not isinstance(resp, dict):
            logger.info(f"[empty_at] 历史返回不是 dict: {type(resp).__name__}")
            return []
        messages = resp.get("messages") or []
        logger.info(
            f"[empty_at] 拉历史 resp_keys={list(resp.keys())} messages={len(messages)}"
        )

        lines: list[str] = []
        for m in messages:
            sender = m.get("sender") or {}
            uid = str(sender.get("user_id") or sender.get("uin") or "")
            if uid == self_id:
                continue
            parts = []
            for seg in (m.get("message") or []):
                if isinstance(seg, dict) and seg.get("type") == "text":
                    parts.append(str(seg.get("data", {}).get("text", "")))
            text = "".join(parts).strip()
            if not text:
                continue
            lines.append(f"{_fmt_sender(sender)}：{text}")
            if len(lines) >= _HISTORY_COUNT:
                break
        return lines

    @filter.on_llm_request(priority=-60)
    async def inject_context(self, event: AstrMessageEvent, req):
        try:
            if event.get_platform_name() != "aiocqhttp":
                return
            # 空艾特判定：唤醒来源是 @，但消息正文是空的
            if not getattr(event, "is_at_or_wake_command", False):
                return
            if (event.message_str or "").strip():
                return
            msgs = event.get_messages() or []
            if len(msgs) != 1:
                return

            bot = _find_bot(self.context)
            lines: list[str] = []
            if bot is not None:
                lines = await self._pull_history(event, bot)

            if lines:
                ctx = "\n".join(lines)
                # 历史直接放进 prompt（模型对 prompt 的注意力比 system_prompt 靠后追加更强）
                req.prompt = (
                    "（对方只@了你，没打字。下面是刚才的聊天记录，最新的在最后：\n"
                    f"{ctx}\n"
                    "结合上面这些内容，自然地接一句，或者问一句「怎么啦」。"
                    "如果他刚才说了什么值得回应的，就直接回那个，不要只问「怎么啦」。"
                    "不要复述上下文，不要提你看到了记录。）"
                )
                system_note = (
                    "\n[空艾特上下文] 有人只 @ 了你不说话。刚才的聊天记录在用户消息里，"
                    "优先顺着那个接话。\n"
                )
            else:
                system_note = (
                    "\n[空艾特上下文] 有人只 @ 了你，没打字，也拉不到聊天记录。"
                    "轻松问一句「怎么啦」「有事吗」就行，不要瞎猜。\n"
                )
            req.system_prompt = (getattr(req, "system_prompt", None) or "") + system_note
        except Exception as e:
            logger.warning(f"[empty_at] 注入上下文失败: {e}")
