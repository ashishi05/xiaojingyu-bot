import asyncio
import json
import time
import uuid
from pathlib import Path
from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Star, register

marker = Path(__file__).with_name('launcher_root.json')
ROOT = Path(json.loads(marker.read_text(encoding='utf-8-sig'))['root']) if marker.exists() else Path(__file__).resolve().parents[4]

@register('launcher_monitor', 'Local', '启动器任务与连接状态', '1.0.0')
class LauncherMonitor(Star):
    def __init__(self, context):
        super().__init__(context)
        self.rows = {}
        self.connections = {}
        self.jobs = []
        old_path = ROOT / 'runtime/launcher-monitor.json'
        if old_path.exists():
            try:
                for row in json.loads(old_path.read_text(encoding='utf-8')).get('tasks', []):
                    if not row.get('finished'):
                        row.update(phase='状态采集中断，结果未确认', finished=time.time())
                    self.rows[row['id']] = row
            except (ValueError, OSError, KeyError):
                logger.warning('启动器任务记录无法恢复')
        self.task = asyncio.create_task(self.watch())

    def save(self):
        path = ROOT / 'runtime/launcher-monitor.json'
        rows = sorted(self.rows.values(), key=lambda r: r['started'], reverse=True)[:100]
        self.rows = {r['id']: r for r in rows}
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({'updated': time.time(), 'tasks': rows, 'connections': self.connections, 'jobs': self.jobs}, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)

    def update(self, event, phase, done=False):
        key = event.get_extra('launcher_task_id')
        if not key:
            key = uuid.uuid4().hex
            event.set_extra('launcher_task_id', key)
            self.rows[key] = dict(id=key, kind='official' if event.get_platform_name().startswith('qq_official') else 'personal', started=time.time(), phase=phase, finished=None)
        if key in self.rows:
            row = self.rows[key]
            row['phase'] = phase
            if done:
                row['finished'] = time.time()
            self.save()

    @filter.on_waiting_llm_request()
    async def waiting(self, event):
        self.update(event, '排队等待')

    @filter.on_agent_begin()
    async def begin(self, event, run_context):
        self.update(event, '正在思考')

    @filter.on_using_llm_tool()
    async def tool(self, event, tool, tool_args):
        self.update(event, '正在调用工具')

    @filter.on_agent_done()
    async def done(self, event, run_context, response):
        self.update(event, '生成完成，等待发送')

    @filter.after_message_sent()
    async def sent(self, event):
        if event.get_extra('launcher_task_id'):
            self.update(event, '回复已发送', True)

    @filter.on_plugin_error()
    async def error(self, event, plugin_name, handler_name, error, traceback_text):
        self.update(event, '处理失败，请查看机器人日志', True)

    async def watch(self):
        while True:
            try:
                await self.snapshot()
            except Exception:
                logger.exception('启动器状态采集失败')
            await asyncio.sleep(2)

    async def snapshot(self):
            meta = self.context.get_registered_star('daily_schedule')
            daily = meta.star_cls if meta and meta.activated else None
            command_path = ROOT / 'runtime/launcher-command.json'
            if command_path.exists():
                command = json.loads(command_path.read_text(encoding='utf-8-sig'))
                command_path.unlink()
                result = {'ok': False, 'error': '每日赛程插件未就绪'}
                if daily:
                    async with daily.lock:
                        scope = command.get('scope')
                        current = daily.state.get(scope)
                        if current:
                            enabled = command.get('enabled') is True
                            if enabled and (not current.get('time') or not current.get('rules')):
                                result = {'ok': False, 'error': '请先在原会话设置推送时间与关注范围'}
                            else:
                                old = current.get('enabled', False)
                                try:
                                    current['enabled'] = enabled
                                    daily.save()
                                    result = {'ok': True}
                                except Exception:
                                    current['enabled'] = old
                                    result = {'ok': False, 'error': '每日赛程设置保存失败'}
                ack = ROOT / ('runtime/launcher-ack-' + command['id'] + '.json')
                ack.write_text(json.dumps(result), encoding='utf-8')
            self.jobs = [dict(id='daily:'+scope, name='每日赛程 · '+str(row.get('time') or '未设时间'), enabled=row.get('enabled', False), note='、'.join(r.get('name','') for r in row.get('rules',[])), next_run_time=None, last_run_at=row.get('last_day') or None) for scope,row in (daily.state.items() if daily else [])]
            for adapter in self.context.platform_manager.platform_insts:
                meta = adapter.meta()
                if meta.name not in ('qq_official', 'aiocqhttp'):
                    continue
                connected = False
                if meta.name == 'qq_official':
                    client = getattr(adapter, 'client', None)
                    # SDK ready is latched; require an open websocket as well.
                    sockets = getattr(client, '_active_websockets', ())
                    connected = any(getattr(s, '_conn', None) is not None and not s._conn.closed and getattr(s, '_session', {}).get('session_id') for s in sockets)
                previous = self.connections.get(meta.id, {})
                self.connections[meta.id] = dict(ready=connected, had_ready=connected or previous.get('had_ready', False), since=previous.get('since', time.time()) if connected and previous.get('ready') else time.time())
            self.save()

    async def terminate(self):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
