import time

from astrbot.api import llm_tool, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register

_ALLOWED = {"10001", "10002"}
# 同一目标的最小间隔，防止连拍
_COOLDOWN = 30
_last_poke: dict[str, float] = {}


def _denied(event: AstrMessageEvent) -> str | None:
    try:
        sender = str(event.get_sender_id())
    except Exception:
        return "无法确认身份。"
    if sender not in _ALLOWED:
        return "只有老大能让我拍人。"
    return None


@register("poke_tool", "Local", "拍一拍：poke / send_poke", "1.0.0")
class PokeTool(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    def _find_bot(self):
        try:
            for inst in self.context.platform_manager.platform_insts:
                bot = getattr(inst, "bot", None)
                if bot is not None:
                    return bot
        except Exception as e:
            logger.error(f"[poke_tool] 获取平台实例失败: {e}")
        return None

    @llm_tool(name="poke")
    async def poke_tool(
        self, event: AstrMessageEvent, target: str = "", times: int = 1
    ) -> str:
        """拍一拍某人。target 留空表示拍当前对话的人，也可以填 QQ 号；times 是次数（1-3）。"""
        denied = _denied(event)
        if denied:
            return denied

        bot = self._find_bot()
        if bot is None:
            return "当前平台不支持拍一拍。"

        try:
            sender = str(event.get_sender_id())
        except Exception:
            return "拿不到对方账号。"
        user_id = target.strip() or sender
        try:
            user_id_int = int(user_id)
        except ValueError:
            return f"target 不是有效 QQ 号：{user_id}"

        n = max(1, min(int(times or 1), 3))

        now = time.time()
        key = f"{event.unified_msg_origin}:{user_id_int}"
        if now - _last_poke.get(key, 0) < _COOLDOWN:
            return "刚拍过，缓一会儿再拍。"

        group_id = ""
        try:
            group_id = getattr(event.message_obj, "group_id", "") or ""
        except Exception:
            pass

        ok = 0
        for _ in range(n):
            try:
                if group_id:
                    await bot.call_action(
                        action="send_poke",
                        user_id=user_id_int,
                        group_id=int(group_id),
                    )
                else:
                    await bot.call_action(action="send_poke", user_id=user_id_int)
                ok += 1
                if n > 1:
                    import asyncio

                    await asyncio.sleep(1.2)
            except Exception as e:
                logger.warning(f"[poke_tool] 拍 {user_id_int} 失败: {e}")
                break

        if ok:
            _last_poke[key] = now
            return f"拍了拍（{ok} 次）"
        return "拍失败了，可能对方设置了不可拍或权限不足。"
