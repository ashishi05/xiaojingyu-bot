import argparse
import hashlib
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from datetime import datetime

import psutil
import requests

ROOT = Path(__file__).resolve().parent
def deployment():
    path = ROOT / 'config.json'
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}

DEPLOY = deployment()
def local_path(key, default):
    return ROOT / DEPLOY.get(key, default)

CONFIG = local_path('astrbot_dir', 'AstrBot') / 'data/cmd_config.json'
DPORT = int(DEPLOY.get('dashboard_port', 6185))
NPORT = int(DEPLOY.get('napcat_port', 6099))
QPORT = int(DEPLOY.get('qq_port', 6199))
URL = f'http://127.0.0.1:{DPORT}'
NAPCAT_URL = f'http://127.0.0.1:{NPORT}'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def port(number):
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1', number)) == 0


def api():
    session = requests.Session()
    session.trust_env = False
    token_path = ROOT / 'runtime/launcher-auth.dpapi'
    if token_path.exists():
        try:
            token = crypt_token(token_path.read_bytes(), False).decode()
            session.headers['Authorization'] = 'Bearer ' + token
            probe = session.get(URL + '/api/platform/stats', timeout=5)
            if probe.status_code == 200 and probe.json().get('status') == 'ok':
                return session
        except Exception:
            pass
    result = session.post(URL + '/api/auth/login', json=json.loads(crypt_token((ROOT / 'runtime/launcher-dashboard-login.dpapi').read_bytes(), False)), timeout=10).json()
    if result.get('status') != 'ok':
        raise RuntimeError('管理服务登录失败，请检查本机管理凭据。')
    session.headers['Authorization'] = 'Bearer ' + result['data']['token']
    token_path.write_bytes(crypt_token(result['data']['token'].encode(), True))
    return session


def crypt_token(data, encrypt):
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    output = Blob()
    function = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def bots():
    config = read(CONFIG)
    mapping = {}
    for bot in config.get('platform', []):
        kind = 'official' if bot.get('type') in {'qq_official', 'qq_official_webhook'} else 'personal' if bot.get('type') == 'aiocqhttp' else None
        if kind:
            if kind in mapping:
                raise RuntimeError('同类型机器人有多个配置，请先指定要控制的实例。')
            mapping[kind] = bot
    return config, mapping


def login_state():
    if not port(NPORT):
        return False
    config = read(local_path('napcat_dir', 'NapCat') / 'napcat/config/webui.json')
    session = requests.Session()
    session.trust_env = False
    cache = ROOT / 'runtime/launcher-napcat-auth.dpapi'
    if cache.exists():
        try:
            session.headers['Authorization'] = 'Bearer ' + crypt_token(cache.read_bytes(), False).decode()
            result = session.post(NAPCAT_URL + '/api/QQLogin/CheckLoginStatus', json={}, timeout=2).json().get('data')
            if isinstance(result, dict) and 'isLogin' in result:
                return bool(result.get('isLogin') and result.get('coreReady'))
        except Exception:
            pass
    hashed = hashlib.sha256((config['token'] + '.napcat').encode()).hexdigest()
    auth = session.post(NAPCAT_URL + '/api/auth/login', json={'hash': hashed}, timeout=2).json()
    credential = auth['data']['Credential']
    session.headers['Authorization'] = 'Bearer ' + credential
    cache.write_bytes(crypt_token(credential.encode(), True))
    result = session.post(NAPCAT_URL + '/api/QQLogin/CheckLoginStatus', json={}, timeout=2).json()['data']
    return bool(result.get('isLogin') and result.get('coreReady'))


def status():
    _, mapping = bots()
    online = port(DPORT)
    stats = {}
    if online:
        session = api()
        result = session.get(URL + '/api/platform/stats', timeout=5).json()
        data = result.get('data', {})
        for item in data.get('platforms', []):
            stats[item['id']] = item
    monitor_path = ROOT / 'runtime/launcher-monitor.json'
    monitor = read(monitor_path) if monitor_path.exists() else {}
    fresh = time.time() - monitor.get('updated', 0) < 12
    out = {'core': online, 'tasks': monitor.get('tasks', []) if online and fresh else [], 'monitor_fresh': fresh and online}
    prefs = ROOT / 'runtime/launcher-settings.json'
    out['settings'] = read(prefs) if prefs.exists() else dict(official=True, personal=True, tray=True, reconnect=False)
    history = ROOT / 'runtime/launcher-history.json'
    out['history'] = read(history) if history.exists() else []
    out['jobs'] = monitor.get('jobs', []) if fresh and online else []
    if online:
        try:
            jobs_result = session.get(URL + '/api/cron/jobs', timeout=5).json()
            if jobs_result.get('status') == 'ok':
                for job in jobs_result.get('data', []):
                    out['jobs'].append({k: job.get(k) for k in ('job_id','id','name','note','enabled','next_run_time','last_run_at')})
        except requests.RequestException:
            out['jobs_error'] = True
    for kind in ('official', 'personal'):
        bot = mapping.get(kind)
        enabled = bool(bot and bot.get('enable'))
        actual = stats.get(bot['id'], {}) if bot else {}
        state = '未配置' if not bot else '已停止' if not online or not enabled else '连接异常' if actual.get('status') == 'error' else '连接已启用' if actual.get('status') == 'running' else '连接启动中'
        if kind == 'personal' and online and enabled:
            try:
                state = 'QQ 已登录' if login_state() else '等待 QQ 登录'
            except Exception:
                state = 'QQ 登录状态未确认'
        light = 'red' if not online or not enabled else 'yellow'
        connection = monitor.get('connections', {}).get(bot['id'], {}) if bot else {}
        if enabled and online and actual.get('status') == 'running' and ((kind == 'official' and fresh and connection.get('ready')) or state == 'QQ 已登录'):
            light = 'green'
        seconds = 0
        if actual.get('started_at') and online and enabled:
            try:
                started = datetime.fromisoformat(actual['started_at'])
                seconds = max(0, int((datetime.now(started.tzinfo) - started).total_seconds()))
            except (TypeError, ValueError):
                pass
        if kind == 'official' and light == 'green':
            state = 'QQ 已连接'
            seconds = max(0, int(time.time() - connection['since']))
        if actual.get('status') == 'error' or (kind == 'official' and fresh and connection.get('had_ready') and not connection.get('ready')):
            light = 'red'
            state = '连接异常'
        waiting_seconds = seconds
        if kind == 'personal':
            ready_path = ROOT / 'runtime/launcher-personal-ready.json'
            previous = read(ready_path) if ready_path.exists() else {}
            ready = light == 'green'
            since = previous.get('since', time.time()) if ready and previous.get('ready') and previous.get('instance') == actual.get('started_at') else time.time()
            write(ready_path, dict(ready=ready, since=since, instance=actual.get('started_at')))
            seconds = max(0, int(time.time() - since)) if ready else 0
        out[kind] = {'enabled': enabled and online, 'text': state, 'light': light, 'running_seconds': seconds, 'waiting_seconds': waiting_seconds}
    return out


def set_enabled(session, bot, enabled):
    data = dict(bot, enable=enabled)
    result = session.post(URL + '/api/config/platform/update', json={'id': bot['id'], 'config': data}, timeout=35).json()
    if result.get('status') != 'ok':
        raise RuntimeError('连接设置未生效：' + str(result.get('message') or '请查看日志'))
    if enabled:
        # These local plugins bind adapter instances at initialization.
        for name in ('ad_guard', 'group_autojoin'):
            refreshed = session.post(URL + '/api/plugin/reload', json={'name': name}, timeout=35).json()
            if refreshed.get('status') != 'ok':
                raise RuntimeError('连接已启用，但群管理重新绑定失败，请查看日志。')


def service(name):
    result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'launcher-service.ps1'), '-Service', name], creationflags=FLAGS, timeout=60, capture_output=True)
    if result.returncode:
        raise RuntimeError('服务启动失败，请查看 logs 中的启动器日志。')


def stop_owned(ports):
    targets = set()
    for conn in psutil.net_connections(kind='tcp'):
        if conn.status == psutil.CONN_LISTEN and conn.laddr.port in ports and conn.pid:
            process = psutil.Process(conn.pid)
            if not Path(process.exe()).resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError('端口由其他程序占用，拒绝关闭。')
            targets.add(process.pid)
    for pid in targets:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in children:
            if Path(child.exe()).resolve().is_relative_to(ROOT.resolve()):
                child.terminate()
        process.terminate()
        try:
            process.wait(timeout=10)
        except psutil.TimeoutExpired:
            process.kill()


def operate(action):
    if action == 'autostart':
        prefs = read(ROOT / 'runtime/launcher-settings.json')
        for kind in ('official', 'personal'):
            if prefs.get(kind):
                operate(kind + '-start')
        return status()
    if action == 'status':
        return status()
    if action == 'all-stop':
        if port(DPORT):
            session = api()
            _, mapping = bots()
            for bot in mapping.values():
                if bot.get('enable'):
                    set_enabled(session, bot, False)
        else:
            config, mapping = bots()
            for bot in mapping.values():
                bot['enable'] = False
            write(CONFIG, config)
        stop_owned({NPORT, DPORT, QPORT})
        return status()
    if action.endswith('-restart'):
        kind = action.split('-')[0]
        operate(kind + '-stop')
        return operate(kind + '-start')
    kind, verb = action.split('-')
    _, mapping = bots()
    if kind not in mapping:
        raise RuntimeError('没有找到对应机器人配置。')
    enabled = verb == 'start'
    if enabled and not port(DPORT):
        # A cold single-bot start must not silently enable the other bot.
        config, mapping = bots()
        for key, bot in mapping.items():
            bot['enable'] = key == kind
        backup = ROOT / 'runtime/launcher-config-before-start.json'
        write(backup, read(CONFIG))
        write(CONFIG, config)
        service('core')
        for _ in range(50):
            if port(DPORT):
                break
            time.sleep(.5)
        else:
            raise RuntimeError('公共服务未就绪，请查看启动日志。')
    if port(DPORT):
        session = api()
        _, mapping = bots()
        if bool(mapping[kind].get('enable')) != enabled:
            set_enabled(session, mapping[kind], enabled)
    if kind == 'personal':
        if enabled:
            if not port(NPORT):
                service('personal')
        else:
            stop_owned({NPORT})
    if not enabled:
        _, current = bots()
        if not any(bot.get('enable') for bot in current.values()):
            stop_owned({DPORT, QPORT})
    return status()



def daily_change(scope, enabled):
    import uuid
    key = uuid.uuid4().hex
    command = ROOT / 'runtime/launcher-command.json'
    if command.exists():
        raise RuntimeError('已有设置正在处理，请稍后重试')
    ack = ROOT / ('runtime/launcher-ack-' + key + '.json')
    write(command, dict(id=key, scope=scope, enabled=enabled))
    for _ in range(40):
        if ack.exists():
            result = read(ack)
            ack.unlink()
            return dict(status='ok' if result.get('ok') else 'error')
        time.sleep(.25)
    if command.exists() and read(command).get('id') == key:
        command.unlink()
    raise RuntimeError('每日赛程未确认设置结果，请刷新检查')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job-id')
    parser.add_argument('action', choices=['autostart', 'job-pause', 'job-resume', 'status', 'official-start', 'official-stop', 'personal-start', 'personal-stop', 'official-restart', 'personal-restart', 'all-stop'])
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    if args.result.resolve().parent != (ROOT / 'runtime').resolve() or not args.result.name.startswith('launcher-'):
        raise SystemExit('Invalid result path')
    try:
        if args.action.startswith('job-'):
            from urllib.parse import quote
            if not args.job_id:
                raise ValueError('请选择定时任务')
            result = daily_change(args.job_id[6:], args.action == 'job-resume') if args.job_id.startswith('daily:') else api().patch(URL + '/api/cron/jobs/' + quote(args.job_id, safe=''), json={'enabled': args.action == 'job-resume'}, timeout=10).json()
            if result.get('status') != 'ok':
                raise RuntimeError('定时任务修改失败')
            state = status()
        else:
            state = operate(args.action)
        value = {'ok': True, 'state': state}
    except Exception as exc:
        value = {'ok': False, 'error': str(exc)}
    if args.action != 'status':
        history_path = ROOT / 'runtime/launcher-history.json'
        history = read(history_path) if history_path.exists() else []
        history.insert(0, dict(time=datetime.now().strftime('%m-%d %H:%M:%S'), action=args.action, ok=value['ok'], detail='操作已完成' if value['ok'] else value['error']))
        write(history_path, history[:100])
    write(args.result, value)
