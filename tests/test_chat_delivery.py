import os, sys
from pathlib import Path
_DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(_DEPLOYMENT_ROOT / 'AstrBot')
sys.path.insert(0, str(_DEPLOYMENT_ROOT / 'maintenance'))

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'AstrBot'))
from astrbot.api.message_components import Plain

spec = importlib.util.spec_from_file_location('chat_delivery_test', root / 'AstrBot/data/plugins/chat_delivery/main.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def check(text, group, pending, expected, platform='aiocqhttp'):
    result = SimpleNamespace(chain=[Plain(text)], is_model_result=lambda: True)
    event = SimpleNamespace(
        get_result=lambda: result, get_platform_name=lambda: platform,
        get_group_id=lambda: '8888' if group else '',
        get_extra=lambda key: pending if key == 'meme_manager_pending_images' else None,
    )
    module.prepare_reply(event)
    assert [c.text for c in result.chain] == expected

check('嘿嘿[split]被你发现了[split]只给你看[split]别说出去', False, [object()], ['嘿嘿', '被你发现了', '只给你看', '别说出去'])
check('第一句[split]第二句[split]第三句', True, [object()], ['第一句', '第二句', '第三句'])
check('一[split]二[split]三', True, [], ['一', '二', '三'])
check('第一步\n第二步\n第三步', False, [], ['第一步\n第二步\n第三步'])
check('[split]你好[split][split]回来啦[split]', False, [], ['你好', '回来啦'])
check('嘿嘿[split]给你挑张表情', False, [], ['嘿嘿', '给你挑张表情'], platform='webchat')
check('一[split]二[split]三[split]四[split]五', False, [], ['一', '二', '三', '四', '五'])
check('一\n\n二\n\n三\n\n四', False, [], ['一', '二', '三', '四'])
check('一[split]二[split]三[split]四[split]五', True, [object()], ['一二', '三四', '五'])
print('PASS: private bubbles uncapped, group sticker budget, no text loss, blank-line splitting')
