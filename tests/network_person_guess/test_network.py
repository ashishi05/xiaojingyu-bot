import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "AstrBot"), str(ROOT / "tests/famous_person_guess")]
import test_people as support  # noqa: E402

from data.plugins.emoji_guess import game, lookup  # noqa: E402
from data.plugins.network_person_guess import main as network  # noqa: E402


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    event = support.PeopleTests.event

    async def asyncSetUp(self):
        await support.PeopleTests.asyncSetUp(self)
        with patch.object(
            network.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.network = network.NetworkPersonGuess(self.context)
        self.stars["network_person_guess"] = SimpleNamespace(
            activated=True, star_cls=self.network
        )
        self.bank = self.network.manager.bank["network_person"]

    async def asyncTearDown(self):
        await self.network.terminate()
        await support.PeopleTests.asyncTearDown(self)

    async def start(self, room="g"):
        with patch.object(game.random, "choice", side_effect=lambda pool: pool[0]):
            await self.network.game_command(self.event("/猜网络人物", group=room))
        return self.network.manager.sessions[f"qqbot:GroupMessage:{room}"]

    async def route(self, text, **kwargs):
        event = self.event(text, **kwargs)
        self.assertTrue(network.NetworkPersonAnswerFilter().filter(event, {}))
        await self.network.answer(event)
        return event

    async def test_all_five_games_continue_with_same_pool_and_five_new_questions(self):
        from data.plugins.function_menu import main as menu

        controller = menu.FunctionMenu.__new__(menu.FunctionMenu)
        controller.context = self.context
        games = [
            (self.characters, "猜角色", "lol+hsr"),
            (self.countries, "猜国家", "country"),
            (self.games, "猜游戏", "videogame"),
            (self.people, "猜知名人物", "famous_person"),
            (self.network, "猜网络人物", "network_person"),
        ]
        for index, (plugin, command, mode) in enumerate(games):
            room = f"continue{index}"
            scope = f"qqbot:GroupMessage:{room}"
            await plugin.manager.start(scope, "owner", mode)
            match = plugin.manager.sessions[scope]
            self.assertEqual(len(match.questions), 5)
            ignored = self.event("继续", group=room)
            await controller.continue_game(ignored)
            self.assertFalse(ignored.stopped)
            await controller.continue_game(self.event("继续", group=room, slash=True))
            self.assertIs(plugin.manager.sessions[scope], match)
            old_ids = {q["id"] for q in match.questions}
            for question_index in range(5):
                async with asyncio.timeout(1):
                    while match.index != question_index or match.phase != "answering":  # noqa: ASYNC110
                        await asyncio.sleep(0)
                await plugin.manager.guess(scope, "u", "User", match.question["answer"])
            await asyncio.wait_for(match.task, 1)
            self.assertIn("/继续：再来一轮", self.sent[-1][1])
            self.assertNotIn(scope, plugin.manager.sessions)
            self.assertEqual(game.LAST_GAMES[scope], (plugin.manager, mode))
            elsewhere = self.event("继续", group=f"unrelated{index}", slash=True)
            await controller.continue_game(elsewhere)
            self.assertTrue(elsewhere.stopped)
            self.assertIn("小鲸鱼 · 猜猜杯比赛", self.sent[-1][1])
            await asyncio.gather(
                *(
                    controller.continue_game(
                        self.event("继续", group=room, user="next", slash=True)
                    )
                    for _ in range(2)
                )
            )
            fresh = plugin.manager.sessions[scope]
            self.assertEqual(fresh.mode, mode)
            self.assertEqual(fresh.owner, "next")
            self.assertEqual(len(fresh.questions), 5)
            self.assertTrue(old_ids.isdisjoint(q["id"] for q in fresh.questions))
            self.assertEqual(fresh.scores, {})
            self.assertIn("15 分", plugin.manager.leaderboard(scope))
            self.assertNotIn(scope, game.LAST_GAMES)
            await plugin.game_command(
                self.event("结束", group=room, user="owner", slash=True), "结束"
            )
            self.assertNotIn(scope, plugin.manager.sessions)
            await controller.continue_game(self.event("继续", group=room, slash=True))
            self.assertEqual(plugin.manager.sessions[scope].mode, mode)
            await plugin.manager.close()
            self.assertNotIn(scope, game.LAST_GAMES)

    async def test_slash_answers_and_end_always_report_score_and_other_games(self):
        import time

        from astrbot.api.message_components import At, Plain
        from astrbot.core.star.filter.command import CommandFilter
        from astrbot.core.star.star_handler import EventType, star_handlers_registry
        from data.plugins.function_menu import main as menu

        controller = menu.FunctionMenu.__new__(menu.FunctionMenu)
        controller.context = self.context
        handler = next(
            h
            for h in star_handlers_registry.get_handlers_by_event_type(
                EventType.AdapterMessageEvent
            )
            if h.handler_module_path == menu.__name__ and h.handler_name == "end_game"
        )
        self.assertGreater(handler.extras_configs["priority"], 200004)
        command_filter = next(
            f for f in handler.event_filters if isinstance(f, CommandFilter)
        )
        for index, (name, plugin, mode) in enumerate(
            [
                ("emoji_guess", self.characters, "lol+hsr"),
                ("country_guess", self.countries, "country"),
                ("videogame_guess", self.games, "videogame"),
                ("famous_person_guess", self.people, "famous_person"),
                ("network_person_guess", self.network, "network_person"),
            ]
        ):
            room = f"slash-end{index}"
            scope = f"qqbot:GroupMessage:{room}"
            await plugin.manager.start(scope, "u", mode)
            match = plugin.manager.sessions[scope]
            old_style = self.event(
                "结束", group=room, parts=[At(qq="bot"), Plain(text="结束")]
            )
            await controller.end_game(old_style)
            self.assertFalse(old_style.stopped)
            self.assertIs(plugin.manager.sessions[scope], match)
            answer = match.question["answer"]
            event = self.event(answer, group=room, parts=[Plain(text="/" + answer)])
            event.set_extra(name + "_answer", (scope, answer, time.perf_counter()))
            await plugin.answer(event)
            self.assertEqual(match.scores["u"][1], 3)
            async with asyncio.timeout(1):
                while match.phase != "answering":  # noqa: ASYNC110
                    await asyncio.sleep(0)
            ending = self.event("结束", group=room, parts=[Plain(text="/结束")])
            ending.is_at_or_wake_command = True
            ending.get_message_str = lambda: "结束"
            self.assertTrue(command_filter.filter(ending, {}))
            before = len(self.sent)
            await controller.end_game(ending)
            self.assertTrue(ending.stopped)
            self.assertNotIn(scope, plugin.manager.sessions)
            result = "\n".join(text for _, text in self.sent[before:])
            self.assertIn("本场已结束", result)
            self.assertIn("3 分", result)
            self.assertIn("/继续", result)
            self.assertNotIn("醒了", result)
            self.assertTrue(
                all("• /" + command in result for _, command in game.GUESS_GAMES)
            )
            next_game = self.network if plugin is not self.network else self.countries
            command = "猜网络人物" if next_game is self.network else "猜国家"
            await next_game.game_command(self.event("/" + command, group=room))
            self.assertIn(scope, next_game.manager.sessions)
            await next_game.manager.cancel(scope)
        empty = self.event("/结束", group="no-game")
        await controller.end_game(empty)
        self.assertTrue(empty.stopped)
        self.assertIn("小鲸鱼 · 猜猜杯比赛", self.sent[-1][1])

    async def test_review_fixes_in_all_games(self):
        import time

        from astrbot.core.star.filter.command import CommandFilter
        from data.plugins.emoji_guess import main as character

        foreign = SimpleNamespace(
            event_filters=[CommandFilter("工具检查", alias={"tc"})]
        )
        for index, (name, plugin, mode) in enumerate(
            [
                ("emoji_guess", self.characters, "lol"),
                ("country_guess", self.countries, "country"),
                ("videogame_guess", self.games, "videogame"),
                ("famous_person_guess", self.people, "famous_person"),
                ("network_person_guess", self.network, "network_person"),
            ]
        ):
            room = f"review-fixes{index}"
            scope = f"qqbot:GroupMessage:{room}"
            manager = plugin.manager
            manager.resolve_alias = AsyncMock(return_value=None)
            await manager.start(scope, "u", mode)
            match = manager.sessions[scope]

            async def route(text):
                event = self.event(text, group=room)
                event.set_extra(name + "_answer", (scope, text, time.perf_counter()))
                await plugin.answer(event)

            with patch.object(
                character.star_handlers_registry,
                "get_handlers_by_event_type",
                return_value=[foreign],
            ):
                for text in (
                    "/菜单",
                    "/发送文件 demo.txt",
                    "/桌面截图",
                    "/工具检查 1",
                    "/tc",
                ):
                    await route(text)
                    self.assertEqual(
                        self.sent[-1][1], "游戏中，请先 /结束 再使用其他功能"
                    )
                    self.assertEqual(match.attempts, set())
                manager.resolve_alias.assert_not_awaited()
                await route("/待核实名字")
                manager.resolve_alias.assert_awaited_once_with(scope, "待核实名字")
                self.assertEqual(match.attempts, set())
                wrong = next(
                    q["answer"]
                    for q in manager.bank[mode]
                    if game.normalize(q["answer"])
                    not in manager.question_answers[match.question["id"]]
                )
                await route("/" + wrong)
                self.assertEqual(match.scores["u"][1], 0)
                started_at = match.started_at
                await route("/" + wrong)
                self.assertEqual(
                    self.sent[-1][1], "本阶段机会已用完，请等下一阶段或下一题"
                )
                self.assertEqual(match.started_at, started_at)
                self.assertEqual(match.attempts, {"u"})
                self.assertEqual(match.scores["u"][1], 0)
            for question_index in range(5):
                async with asyncio.timeout(1):
                    while match.index != question_index or match.phase != "answering":  # noqa: ASYNC110
                        await asyncio.sleep(0)
                await manager.guess(
                    scope,
                    f"p{question_index}",
                    f"Player{question_index}",
                    match.question["answer"],
                )
            await asyncio.wait_for(match.task, 1)
            summary = self.sent[-1][1]
            for player in range(5):
                self.assertIn(f"Player{player} · 3 分", summary)
            self.assertNotIn("User · 0 分", summary)
            self.assertIn("直接发送上方指令开始新游戏", summary)
            self.assertNotIn("切换游戏：/结束", summary)
            self.assertIn("/继续", summary)
            await manager.start(scope, "u", mode)
            stopped = manager.sessions[scope]
            stopped.scores = {str(n): [f"Player{n}", 3, 1] for n in range(5)}
            await manager.stop(scope, "u")
            self.assertIn("Player4 · 3 分", self.sent[-1][1])
            self.assertIn("直接发送上方指令开始新游戏", self.sent[-1][1])

    async def test_model_judgment_without_web_and_uncertain_results_stay_unchanged(
        self,
    ):
        for plugin, entity_type in (
            (self.characters, "character"),
            (self.countries, "country"),
            (self.games, "videogame"),
            (self.people, "person"),
            (self.network, "product"),
        ):
            resolver = plugin.lookup
            target = next(iter(resolver.names))
            provider = SimpleNamespace(text_chat=AsyncMock())
            resolver.context = SimpleNamespace(
                get_config=lambda **kwargs: {
                    "provider_settings": {"web_search": False}
                },
                get_using_provider_async=AsyncMock(return_value=provider),
            )
            answer = {
                "certain": True,
                "ids": [target],
                "entity_type": entity_type,
                "relation": "same_entity",
                "reason": "明确同一实体的常用别称",
            }
            with patch.object(
                lookup.DeepSeekWebSearchTool, "call", new_callable=AsyncMock
            ) as search:
                for index, changes in enumerate(
                    (
                        {"certain": False},
                        {"ids": ["nonexistent-id"]},
                        {"relation": "related_entity"},
                        {"reason": ""},
                        {"ids": [target, target]},
                        {"certain": "true"},
                    )
                ):
                    alias = f"待判断别称{index}"
                    provider.text_chat.return_value = SimpleNamespace(
                        completion_text=json.dumps(answer | changes)
                    )
                    self.assertIsNone(await resolver.resolve("scope", alias))
                    self.assertNotIn(game.normalize(alias), resolver.cache)
                alias = "明确别称"
                provider.text_chat.return_value = SimpleNamespace(
                    completion_text="```json\n" + json.dumps(answer) + "\n```"
                )
                self.assertEqual(await resolver.resolve("scope", alias), {target})
                calls = provider.text_chat.await_count
                self.assertEqual(await resolver.resolve("scope", alias), {target})
                self.assertEqual(provider.text_chat.await_count, calls)
                search.assert_not_awaited()
            request = provider.text_chat.call_args.kwargs
            self.assertEqual(set(json.loads(request["prompt"])), {"alias", "roster"})
            self.assertEqual(request["contexts"], [])
            self.assertIsNone(request["func_tool"])
            self.assertIn("不确定", request["system_prompt"])
            self.assertIn("不改题库", request["system_prompt"])

    async def test_clear_other_entities_are_wrong_but_uncertain_names_are_free(self):
        for index, (plugin, mode) in enumerate(
            (
                (self.characters, "lol"),
                (self.countries, "country"),
                (self.games, "videogame"),
                (self.people, "famous_person"),
                (self.network, "network_person"),
            )
        ):
            provider = SimpleNamespace(text_chat=AsyncMock())
            plugin.lookup.context = SimpleNamespace(
                get_config=lambda **kwargs: {
                    "provider_settings": {"web_search": False}
                },
                get_using_provider_async=AsyncMock(return_value=provider),
            )
            scope = f"qqbot:GroupMessage:verdict{index}"
            await plugin.manager.start(scope, "u", mode)
            match = plugin.manager.sessions[scope]
            provider.text_chat.return_value = SimpleNamespace(
                completion_text=json.dumps(
                    {
                        "certain": True,
                        "ids": [],
                        "entity_type": "other",
                        "relation": "different_entity",
                        "identity": "橙子",
                        "reason": "明确指柑橘类水果，不是名单里的任何实体",
                    }
                )
            )
            self.assertFalse(
                await plugin.manager.guess(scope, "wrong", "Wrong", "明确其他东西")
            )
            self.assertEqual(match.attempts, {"wrong"})
            self.assertEqual(match.scores["wrong"][1], 0)
            self.assertIn("猜错", self.sent[-1][1])
            self.assertNotIn("不扣分", self.sent[-1][1])
            self.assertEqual(plugin.lookup.cache[game.normalize("明确其他东西")], set())
            calls = provider.text_chat.await_count
            self.assertEqual(await plugin.lookup.resolve(scope, "明确其他东西"), set())
            self.assertEqual(provider.text_chat.await_count, calls)
            provider.text_chat.return_value = SimpleNamespace(
                completion_text=json.dumps(
                    {
                        "certain": False,
                        "ids": [],
                        "entity_type": "other",
                        "relation": "unknown",
                        "identity": "",
                        "reason": "不知道这个名字指什么",
                    }
                )
            )
            self.assertFalse(
                await plugin.manager.guess(scope, "unsure", "Unsure", "无法确认的名称")
            )
            self.assertNotIn("unsure", match.attempts)
            self.assertNotIn("unsure", match.scores)
            self.assertNotIn(game.normalize("无法确认的名称"), plugin.lookup.cache)
            self.assertIn("暂未确认", self.sent[-1][1])

    async def test_cup_accumulates_across_rounds_and_types_and_end_resets_only_that_cup(
        self,
    ):
        from data.plugins.function_menu import main as menu

        controller = menu.FunctionMenu.__new__(menu.FunctionMenu)
        controller.context = self.context
        room = "shared-cup"
        scope = f"qqbot:GroupMessage:{room}"
        for plugin, mode, expected in (
            (self.characters, "lol+hsr", 15),
            (self.countries, "country", 30),
        ):
            await plugin.manager.start(scope, "u", mode)
            match = plugin.manager.sessions[scope]
            for index in range(5):
                async with asyncio.timeout(1):
                    while match.index != index or match.phase != "answering":  # noqa: ASYNC110
                        await asyncio.sleep(0)
                await plugin.manager.guess(scope, "u", "User", match.question["answer"])
            await asyncio.wait_for(match.task, 1)
            self.assertIn(f"{expected} 分", self.sent[-1][1])
            for instance in (
                self.characters,
                self.countries,
                self.games,
                self.people,
                self.network,
            ):
                self.assertIn(f"{expected} 分", instance.manager.leaderboard(scope))
        await controller.cup_score(self.event("/积分", group=room))
        self.assertIn("30 分", self.sent[-1][1])
        await controller.end_game(self.event("/结束", group=room, user="other"))
        self.assertIn("开局者", self.sent[-1][1])
        self.assertIn("30 分", self.games.manager.leaderboard(scope))
        # Continuing and another room must not overwrite the existing total.
        await controller.continue_game(self.event("/继续", group=room))
        match = self.countries.manager.sessions[scope]
        await self.countries.manager.guess(scope, "u", "User", match.question["answer"])
        other_scope = "qqbot:GroupMessage:separate-cup"
        await self.network.manager.start(other_scope, "u", "network_person")
        other = self.network.manager.sessions[other_scope]
        await self.network.manager.guess(
            other_scope, "u", "User", other.question["answer"]
        )
        await controller.end_game(self.event("/结束", group=room))
        summary = self.sent[-1][1]
        self.assertIn("本场已结束", summary)
        self.assertIn("33 分", summary)
        self.assertIn("本场积分已清零", summary)
        for instance in (
            self.characters,
            self.countries,
            self.games,
            self.people,
            self.network,
        ):
            self.assertIn("本场积分为 0", instance.manager.leaderboard(scope))
            self.assertIn("3 分", instance.manager.leaderboard(other_scope))
        self.assertEqual(
            self.characters.manager.db.execute(
                "SELECT points FROM scores WHERE scope=?", (scope,)
            ).fetchone()[0],
            15,
        )
        self.assertEqual(
            self.countries.manager.db.execute(
                "SELECT points FROM scores WHERE scope=?", (scope,)
            ).fetchone()[0],
            18,
        )
        await controller.continue_game(self.event("/继续", group=room))
        fresh = self.countries.manager.sessions[scope]
        await self.countries.manager.guess(scope, "u", "User", fresh.question["answer"])
        self.assertIn("3 分", self.people.manager.leaderboard(scope))
        # A completed five-question round still has a cup that /结束 can settle.
        idle = "qqbot:GroupMessage:idle-cup"
        await self.games.manager.start(idle, "u", "videogame")
        await self.games.manager.guess(
            idle, "u", "User", self.games.manager.sessions[idle].question["answer"]
        )
        await self.games.manager.cancel(idle)
        await controller.end_game(self.event("/结束", group="idle-cup"))
        self.assertIn("3 分", self.sent[-1][1])
        self.assertIn("本场积分为 0", self.games.manager.leaderboard(idle))

    async def test_bank_and_shared_aliases(self):
        self.assertEqual(len(self.bank), 55)
        self.assertEqual(len({q["id"] for q in self.bank}), 55)
        self.assertEqual(len({q["emoji"] for q in self.bank}), 55)
        self.assertTrue(all(len(q["emoji"].split()) == 3 for q in self.bank))
        by_name = {q["answer"]: q for q in self.bank}
        aliases = self.network.manager.aliases["network_person"]
        self.assertEqual(
            aliases["马老师"], {by_name[n]["id"] for n in ("大司马", "马保国")}
        )
        self.assertEqual(aliases["大肥鱼"], {by_name["DeepSeek"]["id"]})
        self.assertNotIn(by_name["梁文锋"]["id"], aliases["deepseek"])
        for alias in (
            "jkl",
            "clearlove",
            "载物",
            "康康",
            "大胃袋",
            "菜菜子",
            "曾卓君",
            "爱酱",
        ):
            self.assertIn(alias, aliases)
        self.assertEqual(sum(q["answer"] == "Faker" for q in self.bank), 1)
        for name in (
            "老番茄",
            "中国BOY",
            "s1mple",
            "樊振东",
            "姚明",
            "刘翔",
            "苏炳添",
            "林丹",
            "沈腾",
            "雨姐",
            "豆包",
        ):
            self.assertNotIn(name, by_name)
        self.assertEqual({k for k, v in aliases.items() if len(v) > 1}, {"马老师"})

    async def test_five_rounds_shared_alias_scoring_and_storage(self):
        manager = self.network.manager
        first = ["大司马", "马保国", "DeepSeek"]
        self.bank.sort(
            key=lambda q: first.index(q["answer"]) if q["answer"] in first else 3
        )
        match = await self.start()
        self.assertEqual(len({q["id"] for q in match.questions}), 5)
        self.assertIn("/网络人物名字：每人每阶段一次", self.sent[-1][1])
        manager.resolve_alias = AsyncMock(return_value=None)
        await manager.guess(match.scope, "unknown", "Unknown", "没有核实的别名")
        self.assertNotIn("unknown", match.attempts)
        for index in range(5):
            async with asyncio.timeout(1):
                while match.index != index or match.phase != "answering":  # noqa: ASYNC110
                    await asyncio.sleep(0)
            question = match.question
            wrong = "DeepSeek" if index < 2 else "马老师"
            await manager.guess(match.scope, "bad", "Bad", wrong)
            before = match.scores["bad"][1]
            await manager.guess(match.scope, "bad", "Bad", wrong)
            self.assertEqual(match.scores["bad"][1], before)
            for _ in range(index % 3):
                await manager.hint(match.scope)
            answer = "马老师" if index < 2 else question["answer"]
            self.assertTrue(
                await manager.guess(match.scope, "winner", "Winner", answer)
            )
            self.assertNotIn(question["explanation"], self.sent[-1][1])
        async with asyncio.timeout(1):
            while match.scope in manager.sessions:  # noqa: ASYNC110
                await asyncio.sleep(0)
        self.assertEqual(match.scores["winner"][1:], [11, 5])
        self.assertEqual(match.scores["bad"][1], 0)
        for plugin in (self.characters, self.countries, self.games, self.people):
            self.assertEqual(
                plugin.manager.db.execute("SELECT COUNT(*) FROM scores").fetchone()[0],
                0,
            )
            self.assertEqual(
                plugin.manager.db.execute("SELECT COUNT(*) FROM recent").fetchone()[0],
                0,
            )
        await self.start("unfinished")
        await self.network.terminate()
        with patch.object(
            network.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.network = network.NetworkPersonGuess(self.context)
        self.assertFalse(self.network.manager.sessions)
        self.assertIn("11 分", self.network.manager.leaderboard(match.scope))

    async def test_routing_reveal_menu_and_five_game_exclusion(self):
        await self.characters.game_command(self.event("/猜角色", group="pending"))
        await self.network.game_command(self.event("/猜网络人物", group="pending"))
        self.assertNotIn("qqbot:GroupMessage:pending", self.network.manager.sessions)
        match = await self.start()
        await self.route(match.question["answer"])
        self.assertEqual(match.attempts, set())
        await self.route("揭秘", slash=True)
        self.assertEqual(match.phase, "answering")
        await self.route("/猜网络人物 提示")
        await self.route("提示", slash=True)
        await self.route("马老师", slash=True, user="bad")
        attempts = match.attempts.copy()
        await self.route("提示", slash=True)
        self.assertEqual(self.sent[-1][1], "可揭秘或继续答题")
        self.assertEqual(match.attempts, attempts)
        await self.route("/猜网络人物 结束", user="other")
        self.assertIn(match.scope, self.network.manager.sessions)
        event = self.event("闲聊")
        await self.network.guard_chat(event)
        await self.network.guard_reply(event)
        self.assertTrue(event.stopped)
        self.assertTrue(event.get_extra("cleared"))
        other = self.event("闲聊", group="elsewhere")
        await self.network.guard_chat(other)
        self.assertFalse(other.stopped)
        await self.route("揭秘", slash=True)
        self.assertIn("揭秘", self.sent[-1][1])
        await self.route("结束", slash=True)
        self.assertNotIn(match.scope, self.network.manager.sessions)
        self.assertIn("• /猜网络人物", self.sent[-1][1])
        all_games = [
            (self.characters, "猜角色"),
            (self.countries, "猜国家"),
            (self.games, "猜游戏"),
            (self.people, "猜知名人物"),
            (self.network, "猜网络人物"),
        ]
        for index in range(5):
            room = f"race{index}"
            starters = [
                instance.game_command(self.event("/" + command, group=room))
                for instance, command in all_games
            ]
            await asyncio.gather(*(starters[index:] + starters[:index]))
            scope = f"qqbot:GroupMessage:{room}"
            self.assertEqual(
                sum(
                    scope in instance.manager.sessions
                    or scope in getattr(instance, "pending", {})
                    for instance, _ in all_games
                ),
                1,
            )

    async def test_lookup_supports_product_identity_but_rejects_related_entities(self):
        resolver = self.network.lookup
        target = next(q for q in self.bank if q["answer"] == "DeepSeek")
        other = next(q for q in self.bank if q["answer"] == "梁文锋")
        url = "https://example.com/alias"
        answer = {
            "ids": [target["id"]],
            "sources": [url],
            "entity_type": "product",
            "relation": "founder_of",
        }
        provider = SimpleNamespace(text_chat=AsyncMock())
        resolver.context = SimpleNamespace(
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
                    {
                        "url": url,
                        "title": "测试旧称是DeepSeek的别名，梁文锋是创始人",
                        "snippet": "",
                    }
                ]
            }
        )
        with patch.object(
            lookup.DeepSeekWebSearchTool,
            "call",
            new_callable=AsyncMock,
            return_value=result,
        ) as search:
            for relation, ids, expected in [
                ("founder_of", [target["id"]], None),
                ("same_entity", [target["id"], other["id"]], None),
                ("same_entity", [target["id"]], {target["id"]}),
            ]:
                answer.update(relation=relation, ids=ids)
                provider.text_chat.return_value = SimpleNamespace(
                    completion_text=json.dumps(answer)
                )
                self.assertEqual(await resolver.resolve("scope", "测试旧称"), expected)
        self.assertIn("AI产品", search.call_args.kwargs["query"])
        request = provider.text_chat.call_args.kwargs
        payload = json.loads(request["prompt"])
        self.assertEqual(set(payload), {"alias", "roster", "web_results"})
        self.assertEqual(len(payload["roster"]), 55)
        self.assertEqual(request["contexts"], [])
        self.assertIsNone(request["func_tool"])


if __name__ == "__main__":
    unittest.main()
