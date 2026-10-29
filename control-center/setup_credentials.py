"""Run locally after installation; never put credentials in command arguments."""
import getpass
import importlib.util
import json
from pathlib import Path

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('launcher_control', root/'launcher-control.py')
control=importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
username=input('AstrBot 管理面板用户名: ').strip()
password=getpass.getpass('AstrBot 管理面板密码（不显示）: ')
if not username or not password:
    raise SystemExit('用户名和密码不能为空')
path=root/'runtime/launcher-dashboard-login.dpapi'
path.write_bytes(control.crypt_token(json.dumps({'username':username,'password':password}).encode(),True))
(root/'runtime/launcher-auth.dpapi').unlink(missing_ok=True)
print('凭据已在本机加密保存，仅当前 Windows 用户可解密。')
