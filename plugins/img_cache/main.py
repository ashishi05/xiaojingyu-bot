"""群聊图片缓存：没 @ 的图片先存着，等被 @ 时再带给模型识别。

QQ 里 @ 完再发图，图片会单独成一条消息。AstrBot 默认只处理当前消息的图片，
所以这里做一层缓存：群聊收到图（没 @）先存下不回复；下次被 @ 时把图补进消息。

- 触发：群聊消息含 Image
- 没 @：缓存图片并静默（stop_event）
- @ 了但没图：把缓存的图塞回当前消息
- 缓存按会话，保留最近一次
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Image
from astrbot.api.star import Context, Star, register

# umo -> list[Image]
_CACHE: dict[str, list] = {}
_CACHE_MAX = 1  # 每个会话只留最近一组的图


@register("img_cache", "Local", "群聊图片缓存（@ 时补图）", "1.0.1")
class ImgCache(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_waiting_llm_request(priority=95)
    async def cache_or_inject(self, event: AstrMessageEvent):
        try:
            if event.is_private_chat():
                return

            msgs = event.get_messages() or []
            imgs = [m for m in msgs if isinstance(m, Image)]
            self_id = str(event.get_self_id() or "")
            at_self = any(isinstance(m, At) and str(m.qq) == self_id for m in msgs)

            umo = event.unified_msg_origin

            if at_self and imgs:
                # An explicit current image supersedes any unconsumed older image.
                _CACHE.pop(umo, None)
                return

            if imgs and not at_self:
                # 没 @ 的图：缓存，静默不回复
                _CACHE[umo] = imgs[-_CACHE_MAX:]
                logger.info(f"[img_cache] 缓存 {len(imgs)} 张图（未@）")
                event.stop_event()
                return

            if at_self and not imgs:
                # @ 了但没带图：补上刚才缓存的图
                cached = _CACHE.pop(umo, None)
                if cached:
                    try:
                        event.message_obj.message.extend(cached)
                        logger.info(f"[img_cache] 补入缓存图 {len(cached)} 张")
                    except Exception as e:
                        logger.warning(f"[img_cache] 补图失败: {e}")
                return
        except Exception as e:
            logger.warning(f"[img_cache] 处理失败: {e}")
