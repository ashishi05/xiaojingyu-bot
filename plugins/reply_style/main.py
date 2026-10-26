"""reply_style —— 回复不加 @，群聊用引用回复定位到具体消息

需求：
- 机器人任何回复都不要 @ 人（私聊、群聊都不 @）。
- 群聊里消息多的时候，用 QQ 的「回复」功能挂住它要回的那条消息，
  而不是发一条对不上号的话。
- 私聊不加引用（一对一不需要，越干净越好）。

实现：
- 配置里 reply_with_mention / reply_with_quote 都关掉，避免 AstrBot 自己插 @
  或引用；这里统一接管。
- on_decorating_result 优先级 -20000：比 chat_delivery(-10000) 更晚执行，
  保证它分完条之后，再把引用插到消息链最前面，并清掉所有 At 段。
"""

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, AtAll, Reply
from astrbot.api.star import Context, Star, register


@register("reply_style", "Local", "回复不@人，群聊使用引用回复定位消息", "1.0.0")
class ReplyStyle(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_decorating_result(priority=-20000)
    async def shape_reply(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.chain:
            return
        if not getattr(result, "is_model_result", lambda: False)():
            return

        # 1) 删掉任何 @ 段（包括 @全体）
        chain = [c for c in result.chain if not isinstance(c, (At, AtAll))]

        # 2) 群聊：挂一条引用回复，指向触发这次回复的那条消息
        if event.get_group_id() and not any(isinstance(c, Reply) for c in chain):
            message_id = getattr(event.message_obj, "message_id", None)
            if message_id:
                chain.insert(0, Reply(id=message_id))

        if chain:
            result.chain = chain
