from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

NOTICE = "刚才那段被截断了，本鱼可以分几条接着说，想听就回一句「继续」"


@register("token_guard", "Local", "检测回复被截断时提示用户", "1.0.0")
class TokenGuard(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_llm_response(priority=-100)
    async def detect_truncation(self, event: AstrMessageEvent, response):
        try:
            raw = getattr(response, "raw_completion", None)
            choices = getattr(raw, "choices", None) if raw is not None else None
            if not choices:
                return
            finish_reason = getattr(choices[0], "finish_reason", None)
            if finish_reason != "length":
                return
            logger.info("[token_guard] 检测到回复被截断（finish_reason=length）")
            await event.send(event.plain_result(NOTICE))
        except Exception as e:
            logger.warning(f"[token_guard] 截断检测失败: {e}")
