import re

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

MENU = """小鲸鱼 · 功能

• 聊天、写作
• 查资料、看图片
• 发送、收藏和整理表情
• 拍一拍、撤回消息、定时提醒
• 处理文件、文档和表格
• 电脑截图、自动操作

直接告诉我想做什么就好。
停止桌面操作：/桌面停止"""

# shortcut: static menu for this deployment; update when available features change.
TRIGGER = re.compile(r"/?(?:功能菜单|菜单|你有什么功能|你有哪些功能|(?:发|发个|发一下|给我发|给我发个|给我发一下|看看|查看|打开)(?:功能菜单|菜单))[？?！!。~～]*")


@register('function_menu', 'Local', '私聊功能菜单与用法', '1.0.0')
class FunctionMenu(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_waiting_llm_request(priority=100)
    async def show_menu(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() != 'aiocqhttp'
            or event.get_group_id()
            or str(event.get_sender_id()) not in {'10001', '10002'}
            or not TRIGGER.fullmatch((event.message_str or '').strip())
        ):
            return
        await event.send(event.plain_result(MENU))
        event.stop_event()
