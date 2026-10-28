import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2] / "AstrBot/data/plugins"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "AstrBot"))
from astrbot.api.message_components import At, Image, Plain  # noqa: E402 - installed API path above.
from astrbot.core.star.filter.command import CommandFilter  # noqa: E402
from astrbot.core.star.star_handler import EventType, star_handlers_registry  # noqa: E402

SPEC = importlib.util.find_spec("emoji_guess.main")
if SPEC:
    from emoji_guess import main
else:
    main = None


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(main, "The AstrBot adapter has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []

        async def send_message(scope, chain):
            self.sent.append((scope, chain.chain[0].text))
            return True

        context = SimpleNamespace(
            send_message=send_message, get_registered_star=lambda name: None
        )
        with patch.object(
            main.StarTools, "get_data_dir", return_value=Path(self.tmp.name)
        ):
            self.plugin = main.EmojiGuess(context)
        self.filter = main.GameAnswerFilter()

    async def asyncTearDown(self):
        if hasattr(self, "plugin"):
            await self.plugin.terminate()
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def event(
        self, text, user="u", group="g", role="member", components=None, slash=False
    ):
        extra = {}
        stopped = []

        async def send(result):
            self.sent.append(("event", result))

        return SimpleNamespace(
            message_str=text,
            get_message_str=lambda: text.lstrip("/"),
            is_at_or_wake_command=True,
            message_obj=SimpleNamespace(
                raw_message={"post_type": "message", "sender": {"role": role}}
            ),
            unified_msg_origin="qqbot:FriendMessage:10001",
            get_platform_name=lambda: "aiocqhttp",
            get_platform_id=lambda: "qqbot",
            get_group_id=lambda: group,
            get_sender_id=lambda: user,
            get_sender_name=lambda: "User",
            get_self_id=lambda: "bot",
            get_messages=lambda: (
                components
                or [
                    Plain(
                        text=(
                            "/" + text if slash and not text.startswith("/") else text
                        )
                    )
                ]
            ),
            is_admin=lambda: False,
            set_extra=lambda key, value: extra.__setitem__(key, value),
            get_extra=lambda key, default=None: extra.get(key, default),
            plain_result=lambda value: value,
            send=send,
            stop_event=lambda: stopped.append(True),
            stopped=stopped,
            clear_result=lambda: extra.__setitem__("cleared", True),
        )

    async def start_game(self, user="u", group="g"):
        await self.plugin.game_command(self.event("/猜角色", user=user, group=group))
        event = self.event("1+2", user=user, group=group, slash=True)
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)

    async def test_pool_selection_accepts_common_separators_and_guards_sender(self):
        cases = [
            ("1", "lol"),
            ("2", "val"),
            ("3", "hsr"),
            ("1+3", "lol+hsr"),
            ("3，2", "val+hsr"),
            ("３；１；２", "lol+val+hsr"),
            ("3+3", "hsr"),
            ("1+2", "mixed"),
            ("1，2", "mixed"),
            ("1,2", "mixed"),
            ("1 2", "mixed"),
            ("2 1", "mixed"),
            ("１＋２", "mixed"),
            ("1、2", "mixed"),
            ("1;2", "mixed"),
            ("1+1", "lol"),
        ]
        for index, (text, mode) in enumerate(cases):
            group = str(index)
            scope = "qqbot:GroupMessage:" + group
            await self.plugin.game_command(self.event("/猜角色", group=group))
            self.assertIn(scope, self.plugin.pending)
            self.assertNotIn(scope, self.plugin.manager.sessions)
            for value, user, slash in [
                (text, "u", False),
                (text, "other", True),
                ("1+4", "u", True),
            ]:
                event = self.event(value, user=user, group=group, slash=slash)
                self.assertTrue(self.filter.filter(event, {}))
                await self.plugin.answer(event)
                self.assertIn(scope, self.plugin.pending)
                self.assertNotIn(scope, self.plugin.manager.sessions)
            event = self.event(text, group=group, slash=True)
            self.assertTrue(self.filter.filter(event, {}))
            await self.plugin.answer(event)
            match = self.plugin.manager.sessions[scope]
            self.assertEqual(match.mode, mode)
            self.assertNotIn(scope, self.plugin.pending)
            if mode != "mixed":
                self.assertLessEqual(
                    {q["game"] for q in match.questions}, set(mode.split("+"))
                )
            await self.plugin.manager.stop(scope, "u")
        await self.plugin.game_command(self.event("/猜角色"))
        event = self.event("结束", slash=True)
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertEqual(self.plugin.pending, {})

    async def test_end_returns_menu_only_after_authorized_stop(self):
        scope = "qqbot:GroupMessage:g"
        await self.plugin.game_command(self.event("/猜角色"))
        await self.plugin.game_command(self.event("结束", slash=True), "结束")
        self.assertNotIn(scope, self.plugin.pending)
        self.assertIn("小鲸鱼 · 猜猜杯比赛", self.sent[-1][1])
        await self.start_game()
        await self.plugin.game_command(
            self.event("结束", user="other", slash=True), "结束"
        )
        self.assertIn(scope, self.plugin.manager.sessions)
        self.assertNotIn("猜猜杯比赛", self.sent[-1][1])
        await self.plugin.game_command(self.event("结束", slash=True), "结束")
        self.assertNotIn(scope, self.plugin.manager.sessions)
        self.assertIn("小鲸鱼 · 猜猜杯比赛", self.sent[-1][1])

    async def test_real_plugin_initializes_all_296_questions(self):
        self.assertEqual(sum(len(p) for p in self.plugin.manager.bank.values()), 296)

    async def test_hsr_unknown_alias_search_uses_roster_without_current_clues(self):
        import json

        target = next(
            q for q in self.plugin.manager.bank["hsr"] if q["answer"] == "银狼LV.999"
        )
        url = "https://example.com/hsr-alias"
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(
                    completion_text=json.dumps(
                        {"ids": [target["id"]], "sources": [url]}
                    )
                )
            )
        )
        self.plugin.lookup.context = SimpleNamespace(
            get_config=lambda **kwargs: {
                "provider_settings": {
                    "web_search": True,
                    "websearch_provider": "deepseek",
                }
            },
            get_using_provider_async=AsyncMock(return_value=provider),
        )
        result = json.dumps(
            {
                "results": [
                    {"url": url, "title": "满级鸭是银狼LV.999的别名", "snippet": ""}
                ]
            }
        )
        with patch(
            "emoji_guess.lookup.DeepSeekWebSearchTool.call",
            new_callable=AsyncMock,
            return_value=result,
        ) as search:
            self.assertEqual(
                await self.plugin.lookup.resolve("room", "满级鸭"), {target["id"]}
            )
        self.assertIn("星穹铁道", search.call_args.kwargs["query"])
        request = provider.text_chat.call_args.kwargs
        self.assertEqual(request["contexts"], [])
        self.assertIsNone(request["func_tool"])
        payload = json.loads(request["prompt"])
        self.assertEqual(set(payload), {"alias", "roster", "web_results"})
        self.assertEqual(payload["roster"][target["id"]], target["answer"])

    async def test_real_native_command_parser_selects_mode_and_default(self):
        handler = next(
            h
            for h in star_handlers_registry.get_handlers_by_event_type(
                EventType.AdapterMessageEvent
            )
            if h.handler_module_path == main.__name__
            and h.handler_name == "game_command"
        )
        command_filter = next(
            f for f in handler.event_filters if isinstance(f, CommandFilter)
        )
        self.assertEqual(handler.extras_configs["priority"], 600)
        for text in ("猜角色 lol", "猜角色 瓦", "猜角色 混合"):
            e = self.event(text)
            self.assertTrue(command_filter.filter(e, {}))
            await self.plugin.game_command(e, **e.get_extra("parsed_params"))
            self.assertEqual(self.plugin.manager.sessions, {})
        e = self.event("/猜角色")
        self.assertTrue(command_filter.filter(e, {}))
        await self.plugin.game_command(e, **e.get_extra("parsed_params"))
        self.assertIn("qqbot:GroupMessage:g", self.plugin.pending)
        self.assertNotIn("qqbot:GroupMessage:g", self.plugin.manager.sessions)
        self.assertNotIn("/猜角色 lol", main.HELP)

    async def test_private_native_targets_do_not_use_shared_owner_history(self):
        for uid in ("10001", "10002"):
            await self.start_game(user=uid, group="")
            self.assertIn(f"qqbot:FriendMessage:{uid}", self.plugin.manager.sessions)
        self.assertEqual(len(self.plugin.manager.sessions), 2)

    async def test_guess_requires_real_bot_slash_and_unslashed_chat_uses_no_attempt(
        self,
    ):
        await self.start_game()
        scope = "qqbot:GroupMessage:g"
        answer = self.plugin.manager.sessions[scope].question["answer"]
        e = self.event(answer)
        self.assertTrue(self.filter.filter(e, {}))
        await self.plugin.answer(e)
        self.assertTrue(e.stopped)
        self.assertNotIn("u", self.plugin.manager.sessions[scope].attempts)
        e = self.event(answer, slash=True)
        self.assertTrue(self.filter.filter(e, {}))
        await self.plugin.answer(e)
        self.assertTrue(e.stopped)
        self.assertIn("User", self.plugin.manager.leaderboard(scope))

    async def test_plain_hint_only_routes_during_active_game(self):
        self.assertFalse(self.filter.filter(self.event("提示"), {}))
        await self.start_game()
        scope = "qqbot:GroupMessage:g"
        event = self.event("提示")
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertEqual(self.plugin.manager.sessions[scope].hint_count, 0)
        for stage in (1, 2):
            event = self.event("提示", slash=True)
            self.assertTrue(self.filter.filter(event, {}))
            await self.plugin.answer(event)
            self.assertTrue(event.stopped)
            self.assertEqual(self.plugin.manager.sessions[scope].hint_count, stage)
        match = self.plugin.manager.sessions[scope]
        match.attempts.add("used")
        started_at = match.started_at
        event = self.event("提示", slash=True)
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertEqual(match.hint_count, 2)
        self.assertEqual(match.attempts, {"used"})
        self.assertEqual(match.started_at, started_at)
        self.assertEqual(self.sent[-1][1], "可揭秘或继续答题")
        event = self.event("提示一下今天怎么安排")
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertTrue(event.stopped)

    async def test_normal_chat_is_not_woken_or_consumed(self):
        self.assertFalse(self.filter.filter(self.event("阿狸"), {}))
        await self.start_game()
        for text in ("今天吃什么", "我觉得阿狸挺好", "阿狸、锤石", "洛克今天很有趣"):
            e = self.event(text)
            self.assertTrue(self.filter.filter(e, {}), text)
            await self.plugin.answer(e)
            self.assertTrue(e.stopped)

    async def test_slashs_to_others_media_and_self_messages_are_ignored(self):
        await self.start_game()
        answer = self.plugin.manager.sessions["qqbot:GroupMessage:g"].question["answer"]
        e = self.event(answer, components=[At(qq="someone"), Plain(text=answer)])
        self.assertTrue(self.filter.filter(e, {}))
        await self.plugin.answer(e)
        self.assertTrue(e.stopped)
        e = self.event(
            answer,
            components=[
                Image(file="https://example.invalid/a.png"),
                Plain(text=answer),
            ],
        )
        self.assertTrue(self.filter.filter(e, {}))
        await self.plugin.answer(e)
        self.assertTrue(e.stopped)
        event = self.event(answer, user="bot")
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertTrue(event.stopped)

    async def test_explicit_wrong_guess_replies_and_does_not_call_llm(self):
        await self.start_game()
        before = len(self.sent)
        match = self.plugin.manager.sessions["qqbot:GroupMessage:g"]
        wrong = next(
            q["answer"]
            for pool in self.plugin.manager.bank.values()
            for q in pool
            if q["id"] != match.question["id"]
        )
        e = self.event(wrong, slash=True)
        self.assertTrue(self.filter.filter(e, {}))
        await self.plugin.answer(e)
        self.assertTrue(e.stopped)
        self.assertEqual(len(self.sent), before + 1)
        self.assertIn("猜错", self.sent[-1][1])
        self.assertIn(
            "u", self.plugin.manager.sessions["qqbot:GroupMessage:g"].attempts
        )

    async def test_reveal_requires_slash_and_all_three_emoji(self):
        await self.start_game()
        scope = "qqbot:GroupMessage:g"
        event = self.event("揭秘")
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertTrue(event.stopped)
        event = self.event("揭秘", slash=True)
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertIn("三个", self.sent[-1][1])
        for _ in range(2):
            await self.plugin.manager.hint(scope)
        event = self.event("揭秘", slash=True)
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertIn("答案", self.sent[-1][1])
        self.assertEqual(self.plugin.manager.sessions[scope].phase, "gap")

    async def test_game_gate_blocks_other_commands_but_allows_game_controls(self):
        await self.start_game()
        scope = "qqbot:GroupMessage:g"
        for text in ("/菜单", "打错字了", "/发送文件", "看下赛程"):
            event = self.event(text)
            before = len(self.sent)
            self.assertTrue(self.filter.filter(event, {}))
            await self.plugin.answer(event)
            self.assertTrue(event.stopped)
            if not text.startswith("/"):
                self.assertEqual(len(self.sent), before)
            self.assertEqual(self.plugin.manager.sessions[scope].attempts, set())
        event = self.event("/猜角色 提示")
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertEqual(self.plugin.manager.sessions[scope].hint_count, 1)
        event = self.event("结束", slash=True)
        self.assertTrue(self.filter.filter(event, {}))
        await self.plugin.answer(event)
        self.assertNotIn(scope, self.plugin.manager.sessions)
        self.assertFalse(self.filter.filter(self.event("普通聊天", group="other"), {}))
        for handler in star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent
        ):
            if (
                handler.handler_module_path == main.__name__
                and handler.handler_name == "answer"
            ):
                self.assertGreater(handler.extras_configs["priority"], 99999)

    async def test_llm_guards_suppress_pending_non_game_response(self):
        await self.start_game()
        event = self.event("普通聊天")
        await self.plugin.guard_chat(event)
        self.assertTrue(event.stopped)
        event = self.event("已经在生成的聊天")
        await self.plugin.guard_reply(event)
        self.assertTrue(event.stopped)
        self.assertTrue(event.get_extra("cleared"))

    async def test_group_administrator_can_stop_but_other_members_cannot(self):
        await self.start_game(user="owner")
        await self.plugin.game_command(
            self.event("/猜角色 结束", user="stranger"), "结束"
        )
        self.assertIn("qqbot:GroupMessage:g", self.plugin.manager.sessions)
        await self.plugin.game_command(
            self.event("/猜角色 结束", user="moderator", role="admin"), "结束"
        )
        self.assertNotIn("qqbot:GroupMessage:g", self.plugin.manager.sessions)


if __name__ == "__main__":
    unittest.main()
