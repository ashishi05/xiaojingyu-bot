"""临时调试：打印收到的消息组件结构，定位群聊图片丢失。"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@register("img_debug", "Local", "图片组件调试", "1.1.0")
class ImgDebug(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_waiting_llm_request(priority=200)
    async def dump_images(self, event: AstrMessageEvent):
        try:
            where = "群聊" if event.get_group_id() else "私聊"
            msgs = event.get_messages() or []
            types = [type(m).__name__ for m in msgs]

            # 原始 message 对象
            raw = getattr(event.message_obj, "message", None)
            raw_types = [type(m).__name__ for m in (raw or [])]

            # Component types suffice for diagnosis; omit message text and signed URLs.
            logger.debug(f"[IMG-DBG] {where} components={types} raw={raw_types}")
        except Exception as e:
            logger.warning(f"[IMG-DBG] dump 失败: {e}")
