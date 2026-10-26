from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@register('owner_session', 'Local', '两个自用 QQ 账号共享私聊上下文', '1.0.0')
class OwnerSession(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=100)
    async def merge_owner_session(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() == 'aiocqhttp'
            and event.platform_meta.id == 'qqbot'
            and not event.get_group_id()
            and str(event.get_sender_id()) in {'10001', '10002'}
        ):
            # 只合并会话标识；原始发送者保持不变，回复仍回到本次发消息的 QQ。
            event.session_id = '10001'
