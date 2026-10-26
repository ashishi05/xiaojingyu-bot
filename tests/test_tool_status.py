import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / 'AstrBot')
sys.path.insert(0, str(ROOT / 'AstrBot'))
from astrbot.core import astr_agent_run_util as util
from astrbot.core.agent.response import AgentResponse
from astrbot.core.message.components import Json
from astrbot.core.message.message_event_result import MessageChain

_REAL_SLEEP = asyncio.sleep


class StatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.waits = []
        async def controlled_sleep(seconds):
            if seconds != 5.0:
                return await _REAL_SLEEP(seconds)
            gate = asyncio.Event()
            self.waits.append(gate)
            await gate.wait()
        patched = patch.object(util.asyncio, 'sleep', side_effect=controlled_sleep)
        patched.start()
        self.addCleanup(patched.stop)

    async def asyncTearDown(self):
        tasks = list(util._TOOL_STATUS_TASKS.values())
        for key in list(util._TOOL_STATUS_TASKS):
            util._cancel_tool_status(key)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def event(self, session):
        sent = []
        async def send(chain):
            sent.append(chain.get_plain_text())
        return SimpleNamespace(
            unified_msg_origin=session, send=send, sent=sent,
            is_stopped=lambda: False, get_extra=lambda key: None,
            get_platform_name=lambda: 'aiocqhttp', get_platform_id=lambda: 'qqbot',
            trace=SimpleNamespace(record=lambda *a, **kw: None),
            set_result=lambda result: None, clear_result=lambda: None,
        )

    async def test_all_tools_share_one_delayed_notice(self):
        event = self.event('owner')
        for name in ['search', 'python', 'meme_collect']:
            await util._send_tool_call_status(event, {'name': name})
        self.assertEqual(event.sent, [])
        await _REAL_SLEEP(0)
        self.assertEqual(len(self.waits), 1)
        self.waits[0].set()
        await _REAL_SLEEP(0)
        self.assertEqual(event.sent, ['正在进行…'])
        await util._send_tool_call_status(event, {'name': 'another_tool'})
        await _REAL_SLEEP(0)
        self.assertEqual(len(self.waits), 2)
        self.assertEqual(event.sent, ['正在进行…'])
        self.waits[1].set()
        await _REAL_SLEEP(0)
        self.assertEqual(event.sent, ['正在进行…'] * 2)

    async def test_sessions_are_independent(self):
        events = [self.event('one'), self.event('two')]
        for event in events:
            await util._send_tool_call_status(event, None)
        await _REAL_SLEEP(0)
        self.assertEqual(len(self.waits), 2)
        for gate in self.waits:
            gate.set()
        await _REAL_SLEEP(0)
        for event in events:
            self.assertEqual(event.sent, ['正在进行…'])

    async def test_completion_cancels_pending_notice(self):
        event = self.event('owner')
        await util._send_tool_call_status(event, None)
        await _REAL_SLEEP(0)
        util._cancel_tool_status('owner')
        self.waits[0].set()
        await _REAL_SLEEP(0)
        self.assertEqual(event.sent, [])
        self.assertNotIn('owner', util._TOOL_STATUS_TASKS)

    async def test_failed_delivery_allows_later_notice(self):
        event = self.event('owner')
        async def fail(chain):
            raise RuntimeError('test delivery failure')
        event.send = fail
        await util._send_tool_call_status(event, None)
        await _REAL_SLEEP(0)
        self.waits[0].set()
        await _REAL_SLEEP(0)
        self.assertNotIn('owner', util._TOOL_STATUS_TASKS)
        retry = self.event('owner')
        await util._send_tool_call_status(retry, None)
        await _REAL_SLEEP(0)
        self.waits[1].set()
        await _REAL_SLEEP(0)
        self.assertEqual(retry.sent, ['正在进行…'])

    async def check_loop(self, detailed=False, enabled=True):
        event = self.event('loop')
        class Runner:
            streaming = False
            req = None
            finished = False
            run_context = SimpleNamespace(context=SimpleNamespace(event=event))
            async def step(self):
                yield AgentResponse(type='llm_result', data={'chain': MessageChain().message('我先找找目录')})
                for i, name in enumerate(['search', 'shell', 'python']):
                    yield AgentResponse(type='tool_call', data={'chain': MessageChain(chain=[Json(data={'name': name, 'id': str(i)})])})
                    yield AgentResponse(type='tool_call_result', data={'chain': MessageChain(chain=[Json(data={'id': str(i), 'result': 'INTERNAL DETAIL'})])})
                self.finished = True
                yield AgentResponse(type='llm_result', data={'chain': MessageChain().message('任务完成')})
            def done(self):
                return self.finished
        output = [c.get_plain_text() async for c in util.run_agent(Runner(), show_tool_use=enabled, show_tool_call_result=detailed) if c]
        self.assertEqual(output, ['任务完成'])
        self.assertEqual(event.sent, [])
        self.assertNotIn('loop', util._TOOL_STATUS_TASKS)

    async def test_short_task_only_sends_final(self):
        await self.check_loop()

    async def test_tool_details_are_hidden(self):
        await self.check_loop(detailed=True)

    async def test_disabled_progress_stays_disabled(self):
        await self.check_loop(enabled=False)


if __name__ == '__main__':
    unittest.main()
