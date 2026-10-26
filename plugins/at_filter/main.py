"""只 @ 别人时别插嘴：群里消息里如果有 At 段，但没 At 机器人，就不回复。

AstrBot 的 waking_check 只看第一个消息段；@ 在中间或带引用时会误唤醒，
所以这里再兜一层：只要 @ 的对象里没有机器人自己，就静默。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star, register


@register("at_filter", "Local", "只 @ 别人时不回复", "1.0.0")
class AtFilter(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_waiting_llm_request(priority=30)
    async def only_others(self, event: AstrMessageEvent):
        try:
            if event.is_private_chat():
                return
            msgs = event.get_messages() or []
            ats = [m for m in msgs if isinstance(m, At)]
            if not ats:
                return  # 没有 @，交给正常流程

            self_id = str(event.get_self_id() or "")
            at_self = any(str(a.qq) == self_id for a in ats)
            if at_self:
                return  # @ 了机器人，正常回复

            # 只 @ 了别人
            logger.info(f"[at_filter] 只 @ 了别人（{len(ats)} 个），不回复")
            event.stop_event()
        except Exception as e:
            logger.warning(f"[at_filter] 判断失败: {e}")
