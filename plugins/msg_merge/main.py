"""消息合并：5 秒内的连续消息合成一条再回复。

- on_waiting_llm_request 拦截，先缓存不回复
- 5 秒内来的新消息追加到同一批
- 5 秒到，把合并后的文本塞回最后一条 event，重新入队
- 合并后的 event 打标记，避免二次合并

注意：只合并纯文本消息；带图片/文件的消息照常单独处理，免得丢内容。
"""

import asyncio
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register

MERGE_WINDOW_PRIVATE = 2.0  # 私聊：2 秒
MERGE_WINDOW_GROUP = 3.0  # 群聊：3 秒
MERGE_WINDOW = MERGE_WINDOW_GROUP  # 兼容旧引用

_MERGED_FLAG = "_msg_merge_done"

# umo -> {"texts": [...], "event": event, "ts": float}
_pending: dict[str, dict] = {}
# umo -> asyncio.Task
_timers: dict[str, asyncio.Task] = {}


def _reset_stop(event: AstrMessageEvent) -> None:
    """重新入队前清掉 stop 标记，否则事件还是被丢弃。"""
    try:
        event.clear_result()
    except Exception:
        pass
    try:
        event._force_stopped = False
    except Exception:
        pass


def _is_at_bot(event: AstrMessageEvent) -> bool:
    """消息里有没有 @ 机器人自己。"""
    try:
        self_id = str(event.get_self_id())
        for m in event.get_messages() or []:
            if isinstance(m, At) and str(getattr(m, "qq", "")) == self_id:
                return True
    except Exception:
        pass
    return False


def _has_non_text(event: AstrMessageEvent) -> bool:
    try:
        msgs = event.get_messages() or []
        for m in msgs:
            if not isinstance(m, (At, Plain)):
                return True
    except Exception:
        pass
    return False


@register("msg_merge", "Local", "5 秒内消息合并", "1.0.1")
class MsgMerge(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_waiting_llm_request(priority=20)
    async def merge(self, event: AstrMessageEvent):
        try:
            # 合并后的二次进入：跳过，交给正常流程
            if event.get_extra(_MERGED_FLAG):
                return

            text = (event.message_str or "").strip()
            if not text:
                return
            # Preserve attachments and reply context on their original events.
            if _has_non_text(event):
                return
            # @机器人的消息不合并：这是明确对话（海龟汤提问等），
            # 合并只会白白等 2~3 秒，还容易把问答拖慢
            if _is_at_bot(event):
                return
            # 斜杠命令不合并：/提示 /验证 /揭晓 这类要立刻执行
            if text.startswith("/"):
                return

            umo = event.unified_msg_origin
            now = time.time()
            window = (
                MERGE_WINDOW_PRIVATE if event.is_private_chat() else MERGE_WINDOW_GROUP
            )

            p = _pending.get(umo)
            if p and (now - p["ts"]) < p.get("window", window):
                p["texts"].append(text)
                p["event"] = event
                p["ts"] = now
                event.stop_event()
                logger.debug(f"[msg_merge] 追加第 {len(p['texts'])} 条")
                return

            # 新一批
            _pending[umo] = {
                "texts": [text],
                "event": event,
                "ts": now,
                "window": window,
            }
            event.stop_event()
            if umo not in _timers or _timers[umo].done():
                _timers[umo] = asyncio.create_task(self._flush_later(umo))
            logger.debug(f"[msg_merge] 新建一批，等 {window} 秒")
        except Exception as e:
            logger.warning(f"[msg_merge] 拦截失败: {e}")

    async def _flush_later(self, umo: str):
        p0 = _pending.get(umo)
        window = p0.get("window", MERGE_WINDOW_GROUP) if p0 else MERGE_WINDOW_GROUP
        try:
            await asyncio.sleep(window)
        except asyncio.CancelledError:
            return

        _timers.pop(umo, None)
        p = _pending.pop(umo, None)
        if not p:
            return

        texts = p["texts"]
        if len(texts) <= 1:
            # 只有一条，直接放行原样处理
            ev = p["event"]
            ev.set_extra(_MERGED_FLAG, True)
            _reset_stop(ev)
            logger.info("[msg_merge] 单条消息，放行")
            self.context.get_event_queue().put_nowait(ev)
            return

        merged = "\n".join(texts)
        ev = p["event"]
        try:
            ev.message_str = merged
            ev.set_extra(_MERGED_FLAG, True)
            _reset_stop(ev)
            logger.info(f"[msg_merge] 合并 {len(texts)} 条: {merged[:80]}")
            self.context.get_event_queue().put_nowait(ev)
        except Exception as e:
            logger.warning(f"[msg_merge] 重新入队失败: {e}")
