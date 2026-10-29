"""Isolated checks; never connect to QQ or operate live services."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'control-center'


class ControlCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='whale-launcher-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'runtime').mkdir()
        (self.root / 'custom-core/data').mkdir(parents=True)
        self.config = dict(astrbot_dir='custom-core', napcat_dir='custom-napcat', python='custom-core/python.exe', dashboard_port=16185, napcat_port=16099, qq_port=16199)
        (self.root / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        shutil.copyfile(SOURCE / 'launcher-control.py', self.root / 'launcher-control.py')
        spec = importlib.util.spec_from_file_location('control_fixture', self.root / 'launcher-control.py')
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.m.write(self.m.CONFIG, {'platform': [dict(id='o',type='qq_official',enable=True),dict(id='p',type='aiocqhttp',enable=True)], 'preserve': 'example'})

    def test_configurable_paths_and_ports(self):
        self.assertEqual(self.m.CONFIG, self.root / 'custom-core/data/cmd_config.json')
        self.assertEqual(self.m.URL, 'http://127.0.0.1:16185')
        self.assertEqual(self.m.NAPCAT_URL, 'http://127.0.0.1:16099')

    def test_stop_preserves_startup_preferences_and_other_config(self):
        prefs = dict(official=True, personal=False, tray=True)
        self.m.write(self.root/'runtime/launcher-settings.json', prefs)
        with patch.object(self.m,'port',return_value=False), patch.object(self.m,'stop_owned') as stop:
            state = self.m.operate('all-stop')
        self.assertEqual(self.m.read(self.root/'runtime/launcher-settings.json'), prefs)
        self.assertEqual(self.m.read(self.m.CONFIG)['preserve'], 'example')
        self.assertEqual(state['official']['light'], 'red')
        stop.assert_called_once_with({16099,16185,16199})

    def test_official_readiness_requires_live_monitor_and_session(self):
        class Result:
            def json(self):
                return {'status':'ok','data':{'platforms':[dict(id='o',status='running')]} }
        class Session:
            def get(self, url, **kwargs):
                if '/cron/' in url:
                    return type('R', (), {'json':lambda self: {'status':'ok','data':[]}})()
                return Result()
        path = self.root/'runtime/launcher-monitor.json'
        self.m.write(path, dict(updated=time.time(), connections={'o':dict(ready=True,since=time.time()-20)},tasks=[]))
        with patch.object(self.m,'port',return_value=True), patch.object(self.m,'api',return_value=Session()), patch.object(self.m,'login_state',return_value=False):
            self.assertEqual(self.m.status()['official']['light'], 'green')
            self.assertEqual(self.m.status()['personal']['light'], 'yellow')
            self.m.write(path, dict(updated=0,connections={'o':dict(ready=True)},tasks=[]))
            self.assertNotEqual(self.m.status()['official']['light'], 'green')

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_dpapi_roundtrip(self):
        encrypted = self.m.crypt_token(b'unit-test-only',True)
        self.assertNotIn(b'unit-test-only',encrypted)
        self.assertEqual(self.m.crypt_token(encrypted,False),b'unit-test-only')

    @unittest.skipUnless(os.name == 'nt', 'Windows installer')
    def test_install_backs_up_entries_and_preserves_preferences(self):
        import sys
        shutil.copytree(SOURCE, self.root/'control-center')
        shutil.copyfile(REPO/'_lib.ps1',self.root/'_lib.ps1')
        for entry in ('launcher.ps1','tray.ps1'):
            (self.root/entry).write_text('# original',encoding='utf-8')
        self.config['python'] = sys.executable
        (self.root/'config.json').write_text(json.dumps(self.config),encoding='utf-8')
        prefs = dict(official=True,personal=False,boot=False,tray=True,reconnect=False)
        self.m.write(self.root/'runtime/launcher-settings.json',prefs)
        (self.root/'runtime/launcher-dashboard-login.dpapi').write_bytes(b'fixture-not-a-real-credential')
        shell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(shell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'control-center/install.ps1')],capture_output=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        backups=list((self.root/'backups').iterdir())
        self.assertEqual((backups[0]/'launcher.ps1').read_text(encoding='utf-8-sig'),'# original')
        self.assertEqual(self.m.read(self.root/'runtime/launcher-settings.json'),prefs)
        marker=self.m.read(self.root/'custom-core/data/plugins/launcher_monitor/launcher_root.json')
        self.assertEqual(Path(marker['root']),self.root)


if __name__ == '__main__':
    unittest.main()
