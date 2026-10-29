import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / "AstrBot")
sys.path.insert(0, str(ROOT / "AstrBot"))
spec = importlib.util.spec_from_file_location(
    "group_sync_under_test", ROOT / "AstrBot/data/plugins/group_autojoin/main.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfigWriteTests(unittest.TestCase):
    def test_write_failure_preserves_config_and_success_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            original = {
                "platform_settings": {"id_whitelist": ["old"]},
                "other": {"keep": True},
            }
            config.write_text(json.dumps(original), encoding="utf-8")
            before = config.read_bytes()
            with patch.object(module, "CONFIG", str(config)):
                with patch.object(
                    module.json, "dump", side_effect=OSError("simulated disk failure")
                ):
                    self.assertFalse(module._save_whitelist(["new"]))
                self.assertEqual(config.read_bytes(), before)
                self.assertTrue(module._save_whitelist(["new"]))
                current = json.loads(config.read_text(encoding="utf-8"))
                self.assertEqual(current["platform_settings"]["id_whitelist"], ["new"])
                self.assertEqual(current["other"], original["other"])
                self.assertEqual(
                    Path(str(config) + ".autojoin.bak").read_bytes(), before
                )
                self.assertFalse(list(Path(folder).glob("*.tmp")))


class GroupExclusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_sync_skips_moderation_only_group(self):
        from types import SimpleNamespace

        bot = SimpleNamespace(
            call_action=AsyncMock(
                return_value=[{"group_id": 100000001}, {"group_id": 123456}]
            )
        )
        plugin = module.GroupAutoJoin(SimpleNamespace())
        event = SimpleNamespace(
            get_sender_id=lambda: "10001",
            get_platform_name=lambda: "aiocqhttp",
            get_group_id=lambda: "",
            message_str="更新群库",
            send=AsyncMock(),
            plain_result=lambda text: text,
            stop_event=lambda: None,
        )
        with (
            patch.object(module, "_find_bot", return_value=bot),
            patch.object(module, "_read_whitelist", return_value=[]),
            patch.object(module, "_save_whitelist", return_value=True) as save,
            patch.object(module, "_patch_runtime") as runtime,
        ):
            await plugin.manual_sync(event)
        save.assert_called_once_with(["qqbot:GroupMessage:123456"])
        runtime.assert_called_once_with("123456")


if __name__ == "__main__":
    unittest.main()
