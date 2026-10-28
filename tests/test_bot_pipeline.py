import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / "AstrBot"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from astrbot.api.message_components import At, File, Image, Plain, Reply

PLUGINS = Path(os.environ.get("BOT_PIPELINE_PLUGIN_ROOT", ROOT / "data/plugins"))


def load(name):
    spec = importlib.util.spec_from_file_location(
        "pipeline_test_" + name, PLUGINS / name / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PipelineRegression(unittest.IsolatedAsyncioTestCase):
    def test_nontext_components_bypass_merge(self):
        module = load("msg_merge")
        for component in [File(name="a.txt", file="file:///a.txt"), Reply(id="1")]:
            with self.subTest(component=type(component).__name__):
                event = SimpleNamespace(
                    get_messages=lambda item=component: [Plain(text="分析"), item]
                )
                self.assertTrue(module._has_non_text(event))
        self.assertFalse(
            module._has_non_text(
                SimpleNamespace(get_messages=lambda: [At(qq="bot"), Plain(text="你好")])
            )
        )

    async def test_explicit_image_discards_older_cached_image(self):
        module = load("img_cache")
        plugin = module.ImgCache(SimpleNamespace())

        def event(parts):
            obj = SimpleNamespace(message=parts)
            return SimpleNamespace(
                message_obj=obj,
                unified_msg_origin="fake-group",
                get_messages=lambda: obj.message,
                is_private_chat=lambda: False,
                get_self_id=lambda: "bot",
                stop_event=Mock(),
            )

        old = Image(file="https://example.invalid/old.jpg")
        new = Image(file="https://example.invalid/new.jpg")
        await plugin.cache_or_inject(event([old]))
        await plugin.cache_or_inject(event([At(qq="bot"), new]))
        followup = event([At(qq="bot"), Plain(text="再说一遍")])
        await plugin.cache_or_inject(followup)
        self.assertNotIn(old, followup.get_messages())
        await plugin.cache_or_inject(event([new]))
        latest = event([At(qq="bot"), Plain(text="看图")])
        await plugin.cache_or_inject(latest)
        self.assertIn(new, latest.get_messages())

    def test_code_and_quoted_literals_are_preserved(self):
        module = load("deai_clean")
        for text in [
            '```json\n{"message":"首先，检查配置"}\n```',
            "请输出“作为一个AI”这段原文",
            "`首先，` 是待处理字符串",
            '{"message":"首先，检查配置"}',
        ]:
            with self.subTest(text=text):
                self.assertEqual(module.clean_text(text), text)
        self.assertEqual(
            module.clean_text("这是个好问题，你可以检查配置"), "你可以检查配置"
        )

    async def test_deterministic_plugin_output_is_preserved(self):
        module = load("deai_clean")
        plugin = module.DeaiClean(SimpleNamespace())
        result = SimpleNamespace(
            chain=[Plain(text="首先，保留这段原文")], is_model_result=lambda: False
        )
        await plugin.clean_reply(SimpleNamespace(get_result=lambda: result))
        self.assertEqual(result.chain[0].text, "首先，保留这段原文")


if __name__ == "__main__":
    unittest.main()
