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
from unittest.mock import AsyncMock, patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'AstrBot'))

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from data.plugins.owner_session import main as module

def event_for(sender, group=''):
    message = SimpleNamespace(
        type=MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE,
        sender=SimpleNamespace(user_id=sender), group_id=group,
        raw_message=None, self_id='999999', message_id='1',
    )
    return AiocqhttpMessageEvent('hello', message, SimpleNamespace(id='qqbot', name='aiocqhttp'), group or sender, SimpleNamespace())

async def main():
    plugin = module.OwnerSession.__new__(module.OwnerSession)
    plugin.bind_memory = AsyncMock()
    origins = []
    for sender in ('10001', '10002'):
        event = event_for(sender)
        await plugin.merge_owner_session(event)
        origins.append(event.unified_msg_origin)
        assert event.get_sender_id() == sender
        with patch.object(AiocqhttpMessageEvent, 'send_message', new_callable=AsyncMock) as send:
            await event.send(MessageChain([Plain('test')]))
            assert send.call_args.kwargs['session_id'] == sender, 'reply must reach the actual sender'
    assert len(set(origins)) == 1, 'owner accounts must share history'
    for sender, group in (('123456789', ''), ('10001', '888888')):
        event = event_for(sender, group)
        before = event.unified_msg_origin
        await plugin.merge_owner_session(event)
        assert event.unified_msg_origin == before, 'other accounts and group sessions must remain separate'
    print('PASS: shared owner context, original reply targets, third-party and group isolation')

asyncio.run(main())
