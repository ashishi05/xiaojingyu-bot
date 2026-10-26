import time

from astrbot.api import llm_tool, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register

_ALLOWED = {"10001", "10002"}

# 记录每个会话最近一次撤回的时间（防连点）
_LAST_RECALL: dict[str, float] = {}
_RECALL_COOLDOWN = 5.0


def _denied(event: AstrMessageEvent) -> str | None:
    try:
        sender = str(event.get_sender_id())
    except Exception:
        return "无法确认身份，拒绝操作。"
    if sender not in _ALLOWED:
        return "只有老大能撤回消息。"
    return None


@register("msg_recall", "Local", "消息撤回工具（含撤回机器人自己）", "1.1.0")
class MsgRecall(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    def _find_bot(self):
        try:
            insts = self.context.platform_manager.platform_insts
        except Exception as e:
            logger.error(f"[msg_recall] 获取平台实例失败: {e}")
            return None
        for inst in insts:
            bot = getattr(inst, "bot", None)
            if bot is not None:
                return bot
        return None

    def _self_id(self, bot) -> str:
        try:
            return str(getattr(bot, "self_id", "") or "")
        except Exception:
            return ""

    @llm_tool(name="recall_message")
    async def recall_message_tool(
        self, event: AstrMessageEvent, message_id: str = "", count: int = 1
    ) -> str:
        """撤回消息。message_id 留空时撤回老大刚发的这条；count 可指定撤回最近几条（1-10）。
        注意：这条只能撤别人发的消息，要撤小鲸鱼自己发的请用 recall_bot_message。"""
        denied = _denied(event)
        if denied:
            return denied

        bot = self._find_bot()
        if bot is None:
            return "当前平台没有可用的 OneBot 客户端，撤回不了。"

        targets: list[int] = []
        if message_id.strip():
            try:
                targets.append(int(message_id.strip()))
            except ValueError:
                return f"message_id 不是数字：{message_id}"
        else:
            mid = getattr(event.message_obj, "message_id", "")
            if mid:
                try:
                    targets.append(int(mid))
                except (TypeError, ValueError):
                    pass

        if not targets:
            return "没拿到可以撤回的消息 ID。"

        ok, fail = 0, 0
        for mid in targets:
            try:
                await bot.call_action(action="delete_msg", message_id=mid)
                ok += 1
            except Exception as e:
                fail += 1
                logger.warning(f"[msg_recall] 撤回 {mid} 失败: {e}")

        if ok and not fail:
            return f"撤回成功（{ok} 条）"
        if ok and fail:
            return f"撤回 {ok} 条，失败 {fail} 条（可能超过 2 分钟或没有权限）"
        return "撤回失败：可能超过 2 分钟时限，或当前是群聊且没有管理员权限。"

    @llm_tool(name="recall_bot_message")
    async def recall_bot_message_tool(
        self, event: AstrMessageEvent, count: int = 1
    ) -> str:
        """撤回小鲸鱼自己刚发的消息。count 指定最近几条（1-5），默认撤最近一条。
        只在老大（管理员）明确要求撤回时使用；其他情况不要主动撤回。"""
        denied = _denied(event)
        if denied:
            return denied

        now = time.monotonic()
        umo = event.unified_msg_origin
        if now - _LAST_RECALL.get(umo, 0) < _RECALL_COOLDOWN:
            return "刚撤过，缓一下再撤。"
        _LAST_RECALL[umo] = now

        bot = self._find_bot()
        if bot is None:
            return "当前平台没有可用的 OneBot 客户端，撤回不了。"

        count = max(1, min(int(count or 1), 5))
        self_id = self._self_id(bot)
        if not self_id:
            return "拿不到机器人自己的账号 ID，撤回不了。"

        messages: list[dict] = []
        try:
            if event.get_group_id():
                resp = await bot.call_action(
                    action="get_group_msg_history",
                    group_id=int(event.get_group_id()),
                    count=20,
                )
            else:
                resp = await bot.call_action(
                    action="get_friend_msg_history",
                    user_id=int(event.get_sender_id()),
                    count=20,
                )
            if isinstance(resp, dict):
                messages = resp.get("messages") or []
        except Exception as e:
            logger.warning(f"[msg_recall] 拉历史失败: {e}")
            return "拉不到聊天记录，撤回不了（可能接口不支持）。"

        mine: list[dict] = []
        for m in reversed(messages):
            sender = m.get("sender") or {}
            uid = str(sender.get("user_id") or sender.get("uin") or "")
            if uid == self_id:
                mine.append(m)

        if not mine:
            return "最近没找到我自己发的消息。"

        targets = mine[:count]
        ok, fail = 0, 0
        for m in targets:
            mid = m.get("message_id") or m.get("message_id_v2")
            if not mid:
                continue
            try:
                await bot.call_action(action="delete_msg", message_id=mid)
                ok += 1
            except Exception as e:
                fail += 1
                logger.warning(f"[msg_recall] 撤回自己消息 {mid} 失败: {e}")

        if ok:
            return f"撤回了 {ok} 条刚才说的话"
        return "撤回失败：可能超过 2 分钟时限，或没有权限。"
