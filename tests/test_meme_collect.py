import os, sys
from pathlib import Path
_DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(_DEPLOYMENT_ROOT / 'AstrBot')
sys.path.insert(0, str(_DEPLOYMENT_ROOT / 'maintenance'))

import sys, unittest, tempfile, io, asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = [str(_DEPLOYMENT_ROOT / 'AstrBot'), str(_DEPLOYMENT_ROOT / 'AstrBot' / 'data' / 'plugins')]
from astrbot.api.message_components import Image, Reply
from astrbot.core.message.message_event_result import MessageChain
from meme_admin.main import MemeAdmin
from astrbot.api import logger
logger.setLevel("CRITICAL")

class Event:
    def __init__(self, text='', images=(), sender='10001'):
        self.message_str = text
        self.message_obj = SimpleNamespace(message=list(images))
        self.session_id = 'shared'
        self.unified_msg_origin = 'qqbot:FriendMessage:shared'
        self.sender = sender
        self.sent = []
        self.stopped = False
    def get_sender_id(self): return self.sender
    def get_platform_name(self): return 'aiocqhttp'
    def get_group_id(self): return ''
    def plain_result(self, text): return MessageChain().message(text)
    async def send(self, result): self.sent.append(result.get_plain_text())
    def stop_event(self): self.stopped = True

class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pack = Path(self.tmp.name) / 'pack'
        self.pack.mkdir()
        self.paths = dict(pack_dir=self.pack, memes_dir=self.pack/'memes')
        self.manager = SimpleNamespace(upload_states={}, _resolve_runtime_pack_context=lambda **kw: dict(pack_id='pack', memes_dir=str(self.pack/'memes')))
        self.calls = []
        async def upload(event, category):
            self.manager.upload_states[f'{event.session_id}_{event.get_sender_id()}'] = dict(category=category)
            yield event.plain_result('请发图片')
        async def save(event):
            self.calls.append(list(event.message_obj.message))
            self.manager.upload_states.pop(f'{event.session_id}_{event.get_sender_id()}', None)
            yield event.plain_result(f'已收录 {len(event.message_obj.message)} 张')
        self.manager.upload_meme = upload
        self.manager._handle_upload_image_impl = save
        self.manager.semantic_task_manager = SimpleNamespace(begin_external_pack_operation=lambda *a: None, end_external_pack_operation=lambda *a: None)
        self.subject = MemeAdmin(SimpleNamespace(get_registered_star=lambda name: SimpleNamespace(star_cls=self.manager)))
        self.resolver = patch('meme_manager.backend.packs.resolver.get_pack_paths', return_value=self.paths)
        self.resolver.start()
        self.addCleanup(self.resolver.stop)
    async def observe(self, event):
        await self.subject.receive_collection_request(event)
    async def test_batch_is_direct_and_only_one_result(self):
        images = [Image.fromURL('https://example.com/1.png'), Image.fromURL('https://example.com/2.png')]
        event = Event('这几个图加进表情包库吧', images)
        await self.observe(event)
        self.assertEqual(self.calls, [images])
        self.assertEqual(len(event.sent), 1)
        self.assertTrue(event.stopped)
        self.assertEqual(event.message_obj.message, images)
    async def test_recent_images_are_sender_scoped_and_expire(self):
        image = Image.fromURL('https://example.com/a.png')
        await self.observe(Event(images=[image]))
        second = Event('把刚才的图片收进表情库', sender='10002')
        await self.observe(second)
        self.assertFalse(self.calls)
        first = Event('这张图收进表情库')
        await self.observe(first)
        self.assertEqual(self.calls, [[image]])
        with patch('meme_admin.main.time.monotonic', return_value=10**12):
            expired = Event('这张图收进表情库')
            await self.observe(expired)
        self.assertEqual(len(self.calls), 1)
    async def test_quote_takes_priority_and_empty_quote_never_falls_back(self):
        recent = Image.fromURL('https://example.com/recent.png')
        quoted = Image.fromURL('https://example.com/quoted.png')
        await self.observe(Event(images=[recent]))
        await self.observe(Event('收进表情库', [Reply(id='1', chain=[quoted])]))
        self.assertEqual(self.calls, [[quoted]])
        await self.observe(Event('收进表情库', [Reply(id='2', chain=[])]))
        self.assertEqual(len(self.calls), 1)
    async def test_denied_and_chitchat_do_not_collect(self):
        await self.observe(Event('这几个图加进表情库', [Image.fromURL('https://example.com/a.png')], sender='123'))
        await self.observe(Event('你觉得这个图要不要加进表情库？'))
        self.assertFalse(self.calls)
    async def test_tool_restores_manual_state_and_surfaces_error(self):
        event = Event(images=[Image.fromURL('https://example.com/a.png')])
        key = 'shared_10001'
        previous = dict(category='happy')
        self.manager.upload_states[key] = previous
        result = await self.subject.meme_collect_tool(event)
        self.assertIn('已收录', result)
        self.assertIs(self.manager.upload_states[key], previous)
        async def fail(event):
            raise OSError('test failure')
            yield
        self.manager._handle_upload_image_impl = fail
        result = await self.subject.meme_collect_tool(event)
        self.assertIn('失败', result)
        self.assertIs(self.manager.upload_states[key], previous)
    async def test_unsafe_category_rejected_before_save(self):
        result = await self.subject.meme_collect_tool(Event(images=[Image.fromURL('https://example.com/a.png')]), '../escape')
        self.assertFalse(self.calls)
        self.assertIn('失败', result)


class RealUploadTests(CollectionTests):
    def setUp(self):
        super().setUp()
        from types import MethodType
        from meme_manager.mixins.commands import CommandMixin
        from meme_manager.mixins.event_handlers import EventHandlerMixin
        from unittest.mock import AsyncMock
        self.manager.upload_meme = MethodType(CommandMixin.upload_meme, self.manager)
        self.manager._handle_upload_image_impl = MethodType(EventHandlerMixin._handle_upload_image_impl, self.manager)
        self.manager.reload_emotions = AsyncMock()
        self.manager.img_sync = None
        for name, value in [
            ('meme_manager.mixins.commands.get_pack_paths', self.paths),
            ('meme_manager.mixins.event_handlers.get_pack_paths', self.paths),
            ('meme_manager.mixins.commands.load_pack_category_mapping', {'happy':'开心'}),
            ('meme_manager.mixins.event_handlers.load_pack_category_mapping', {'happy':'开心'}),
        ]:
            item = patch(name, return_value=value)
            item.start()
            self.addCleanup(item.stop)
        item = patch('meme_manager.mixins.event_handlers.invalidate_semantic_metadata')
        item.start()
        self.addCleanup(item.stop)
    async def test_real_batch_preserves_gif_and_skips_duplicate(self):
        from PIL import Image as Pillow
        png, gif = self.pack/'input.png', self.pack/'input.gif'
        Pillow.new('RGB', (4,4), 'red').save(png)
        frames = [Pillow.new('RGB',(4,4), color) for color in ['red','blue']]
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=80, loop=0)
        event = Event('这几个图加进表情包库吧', [Image.fromFileSystem(str(png)), Image.fromFileSystem(str(gif)), Image.fromFileSystem(str(png))])
        await self.observe(event)
        self.assertTrue(event.stopped)
        self.assertEqual(len(event.sent), 1)
        self.assertIn('2 张新表情', event.sent[0])
        self.assertIn('1 张重复', event.sent[0])
        saved = list((self.pack/'memes'/'all').iterdir())
        self.assertEqual(len(saved), 2)
        saved_gif = next(p for p in saved if p.suffix == '.gif')
        self.assertEqual(saved_gif.read_bytes(), gif.read_bytes())
        self.assertFalse(self.manager.upload_states)
    async def test_real_invalid_image_reports_failure_without_files(self):
        bad = self.pack/'bad.png'
        bad.write_text('this is not an image')
        result = await self.subject.meme_collect_tool(Event(images=[Image.fromFileSystem(str(bad))]))
        self.assertIn('失败', result)
        self.assertEqual(list((self.pack/'memes'/'all').iterdir()), [])
    async def test_real_missing_category_does_not_succeed(self):
        result = await self.subject.meme_collect_tool(Event(images=[Image.fromURL('https://example.com/a.png')]), 'nonexistent')
        self.assertIn('无效', result)
        self.assertFalse((self.pack/'memes'/'nonexistent').exists())
    # These contract tests use a fake manager in the base class.
    test_batch_is_direct_and_only_one_result = None
    test_recent_images_are_sender_scoped_and_expire = None
    test_quote_takes_priority_and_empty_quote_never_falls_back = None
    test_denied_and_chitchat_do_not_collect = None
    test_tool_restores_manual_state_and_surfaces_error = None
    test_unsafe_category_rejected_before_save = None

if __name__ == '__main__': unittest.main()

