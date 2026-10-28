import os, sys
from pathlib import Path
_DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(_DEPLOYMENT_ROOT / 'AstrBot')
sys.path.insert(0, str(_DEPLOYMENT_ROOT / 'maintenance'))

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'AstrBot'))
spec = importlib.util.spec_from_file_location('function_menu_test', root / 'AstrBot/data/plugins/function_menu/main.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

async def check(text, sender='10001', group='', platform='aiocqhttp', expected=True):
    sent = []
    stopped = []
    async def send(result):
        sent.append(result)
    event = SimpleNamespace(
        message_str=text, get_sender_id=lambda: sender,
        get_group_id=lambda: group, get_platform_name=lambda: platform,
        plain_result=lambda value: value, send=send,
        stop_event=lambda: stopped.append(True),
    )
    plugin = module.FunctionMenu.__new__(module.FunctionMenu)
    await plugin.show_menu(event)
    assert sent == ([module.MENU] if expected else []), (text, sender, group)
    assert bool(stopped) == expected

async def main():
    assert "Emoji 猜角色（LOL／瓦／星铁）：/猜角色" in module.MENU
    assert "Emoji 猜国家（42 国）：/猜国家" in module.MENU
    assert "Emoji 猜游戏（55 题）：/猜游戏" in module.MENU
    assert "Emoji 猜知名人物（71 人）：/猜知名人物" in module.MENU
    assert "Emoji 猜网络人物（55 题）：/猜网络人物" in module.MENU
    for text in ['菜单', ' 功能菜单 ', '/菜单', '你有什么功能', '发一下菜单', '看看菜单', '发个菜单']:
        await check(text)
    await check('菜单', sender='10002')
    await check('菜单', sender='999', expected=False)
    await check('菜单', group='888', expected=False)
    await check('菜单', platform='webchat', expected=False)
    await check('今天吃什么', expected=False)
    await check('这个菜单设计得不错', expected=False)
    print('PASS: menu requests, both owners, private-only access, unrelated chat preserved')

asyncio.run(main())
