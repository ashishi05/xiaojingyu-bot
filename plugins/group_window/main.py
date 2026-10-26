"""group_window —— 群聊三分钟连续对话窗口 + 群友回复限流

行为：
1. 群里默认必须 @ 机器人（或使用唤醒前缀）才会接话。
2. 一旦被 @，或者机器人在群里说过话，就开启一个 3 分钟的对话窗口。
3. 窗口内，群消息不再需要 @，机器人会继续接话（这就是「一直对话」）。
4. 窗口内只要还有人在说话，窗口就顺延 3 分钟；3 分钟没人说话自动关闭，
   回到「必须 @」的状态（= 自动睡眠）。
5. 非管理员群友：每人每 60 秒最多触发 3 次回复。一次回复里分成几条气泡
   也只算 1 次。

实现要点：
- AstrBot 的唤醒判断在 WakingCheckStage 里做，插件唯一能插进去的地方是
  handler 的 filter。这里注册一个 CustomFilter：窗口开着才返回 True。
  filter 通过只会让 is_wake=True，不会自动触发 LLM，所以 handler 里补一句
  event.is_at_or_wake_command = True，让后面的 ProcessStage 正常走 LLM。
- 窗口续期放在 on_waiting_llm_request：只要群里真的发起了一次 LLM 请求，
  就说明对话还在继续（覆盖「被 @ 时开窗」和「机器人说话后顺延」）。
"""

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.custom_filter import CustomFilter

ADMIN_IDS = {"10001", "10002"}

WINDOW_SECONDS = 180  # 被 @ 或说话后，连续对话窗口 3 分钟
REPLY_LIMIT = 3  # 非管理员群友每窗口最多几次回复
LIMIT_WINDOW_SECONDS = 60  # 限流统计窗口：1 分钟

# (platform_id, group_id) -> 最后一次对话时间
_windows: dict[tuple[str, str], float] = {}
# (platform_id, group_id, sender_id) -> [回复时间戳...]
_replies: dict[tuple[str, str, str], list[float]] = {}


def _group_key(event: AstrMessageEvent) -> tuple[str, str]:
    return (str(event.get_platform_id()), str(event.get_group_id()))


def _limit_key(event: AstrMessageEvent) -> tuple[str, str, str]:
    return (*_group_key(event), str(event.get_sender_id()))


def _is_admin(event: AstrMessageEvent) -> bool:
    return str(event.get_sender_id()) in ADMIN_IDS


def _is_self(event: AstrMessageEvent) -> bool:
    return str(event.get_sender_id()) == str(event.get_self_id())


def _window_open(key: tuple[str, str]) -> bool:
    last = _windows.get(key)
    return last is not None and (time.time() - last) <= WINDOW_SECONDS


def _touch_window(key: tuple[str, str]) -> None:
    _windows[key] = time.time()


def _recent_replies(key: tuple[str, str, str]) -> list[float]:
    now = time.time()
    stamps = [t for t in _replies.get(key, []) if now - t < LIMIT_WINDOW_SECONDS]
    if stamps:
        _replies[key] = stamps
    else:
        _replies.pop(key, None)
    return stamps


def _reached_limit(event: AstrMessageEvent) -> bool:
    return len(_recent_replies(_limit_key(event))) >= REPLY_LIMIT


def _count_reply(event: AstrMessageEvent) -> None:
    key = _limit_key(event)
    _recent_replies(key)  # 顺手清理过期记录
    _replies.setdefault(key, []).append(time.time())


class _FollowUpFilter(CustomFilter):
    """窗口期内放行群消息的过滤器。"""

    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        try:
            if not event.get_group_id():
                return False
            if _is_self(event):
                return False

            key = _group_key(event)
            if not _window_open(key):
                return False

            # 窗口内任何一条群消息都算「有人说话」，把窗口顺延 3 分钟。
            _touch_window(key)

            if not _is_admin(event) and _reached_limit(event):
                return False

            return bool((event.message_str or "").strip())
        except Exception as exc:  # 过滤器异常不该拖垮消息处理
            logger.warning(f"[group_window] 过滤器异常: {exc}")
            return False


@register("group_window", "Local", "群聊三分钟连续对话窗口与群友回复限流", "1.0.0")
class GroupWindow(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.custom_filter(_FollowUpFilter)
    async def follow_up(self, event: AstrMessageEvent):
        """窗口期内的群消息：放行给 LLM。

        filter 通过只会把 is_wake 置为 True，不会自动请求 LLM；
        这里补上 is_at_or_wake_command，ProcessStage 才会走正常对话流程。
        """
        event.is_at_or_wake_command = True
        event.is_wake = True

    @filter.on_waiting_llm_request(priority=100)
    async def guard(self, event: AstrMessageEvent):
        """群里每次真正要请求 LLM 时：续期窗口 + 非管理员限流。"""
        if not event.get_group_id() or _is_self(event):
            return

        key = _group_key(event)
        _touch_window(key)

        if _is_admin(event):
            return

        if _reached_limit(event):
            logger.info(
                f"[group_window] 群友 {event.get_sender_id()} 触发限流"
                f"（{REPLY_LIMIT} 次/{LIMIT_WINDOW_SECONDS}s），本条不回复"
            )
            event.stop_event()
            return

        _count_reply(event)
