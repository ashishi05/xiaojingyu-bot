from astrbot.api.event import filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from data.plugins.emoji_guess.game import occupied_game
from data.plugins.emoji_guess.main import native_scope


class PokeproPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AiocqhttpMessageEvent):
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict) or raw.get("post_type") != "notice" or raw.get("notice_type") != "notify" or raw.get("sub_type") != "poke":
            return
        self_id = str(event.get_self_id() or "")
        if not self_id or str(raw.get("target_id") or "") != self_id or str(raw.get("user_id") or "") == self_id:
            return
        if occupied_game(self.context, native_scope(event), ""):
            return
        text = "（对方拍了拍你）"
        event.message_obj.message = [At(qq=self_id), Plain(text)]
        event.message_obj.message_str = text
        event.message_obj.message_id = ""
        event.message_str = text
        event.is_at_or_wake_command = True
        event.is_wake = True
