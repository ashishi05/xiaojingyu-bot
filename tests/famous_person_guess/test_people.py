import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "AstrBot"),
    str(ROOT / "AstrBot"),
    str(ROOT / "tests/videogame_guess"),
]
import test_videogame as support  # noqa: E402

from data.plugins.emoji_guess import game, lookup  # noqa: E402
from data.plugins.famous_person_guess import main as people  # noqa: E402
from data.plugins.function_menu import main as menu  # noqa: E402


class PeopleTests(unittest.IsolatedAsyncioTestCase):
    event = support.VideogameTests.event

    async def asyncSetUp(self):
        await support.VideogameTests.asyncSetUp(self)
        with patch.object(
            people.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.people = people.FamousPersonGuess(self.context)
        self.stars["famous_person_guess"] = SimpleNamespace(
            activated=True, star_cls=self.people
        )

    async def asyncTearDown(self):
        await self.people.terminate()
        await support.VideogameTests.asyncTearDown(self)

    async def start(self, room="g"):
        with patch.object(game.random, "choice", side_effect=lambda pool: pool[0]):
            await self.people.game_command(self.event("/猜知名人物", group=room))
        return self.people.manager.sessions[f"qqbot:GroupMessage:{room}"]

    async def route(self, text, **kwargs):
        event = self.event(text, **kwargs)
        self.assertTrue(people.FamousPersonAnswerFilter().filter(event, {}))
        await self.people.answer(event)
        return event

    async def test_exact_bank_clues_and_unambiguous_aliases(self):
        bank = self.people.manager.bank["famous_person"]
        self.assertEqual(len(bank), 71)
        self.assertEqual(len({q["id"] for q in bank}), 71)
        self.assertEqual(len({q["emoji"] for q in bank}), 71)
        by_name = {q["answer"]: q for q in bank}
        for name, clue in {
            "苏轼": "✍️ 🍖 🐖",
            "金正恩": "☀️ ✍️ 🌸",
            "白求恩": "🇨🇦 ⛑️ 🇨🇳",
        }.items():
            self.assertEqual(by_name[name]["emoji"], clue)
        self.assertEqual(by_name["蒋介石"]["emoji"].split()[:2], ["📓", "🚚"])
        self.assertEqual(by_name["张作霖"]["emoji"].split()[:2], ["🚂", "💥"])
        aliases = {}
        for question in bank:
            self.assertEqual(len(question["emoji"].split()), 3)
            self.assertIn("clue_status", question)
            for alias in question["answers"]:
                key = game.normalize(alias)
                self.assertTrue(key)
                self.assertIn(aliases.get(key), (None, question["id"]))
                aliases[key] = question["id"]
        for alias, name in (
            ("苏东坡", "苏轼"),
            ("周树人", "鲁迅"),
            ("嬴政", "秦始皇"),
            ("Kim Jong-un", "金正恩"),
            ("MJ", "迈克尔·杰克逊"),
            ("Michael Jordan", "迈克尔·乔丹"),
        ):
            self.assertEqual(aliases[game.normalize(alias)], by_name[name]["id"])
        for word in ("张学良", "皇帝", "总统", "科学家", "球王", "我猜是秦始皇"):
            self.assertNotIn(game.normalize(word), aliases)

    async def test_representative_ten_rounds_attempts_scoring_and_persistence(self):
        manager = self.people.manager
        with patch.object(game, "GAP_SECONDS", 0.001):
            match = await self.start()
            self.assertEqual(len({q["id"] for q in match.questions}), 5)
            self.assertEqual(match.clue, "👑")
            self.assertIn("答对 +3 分", self.sent[-1][1])
            for index in range(5):
                async with asyncio.timeout(1):
                    while match.index != index or match.phase != "answering":  # noqa: ASYNC110 - observe production transitions.
                        await asyncio.sleep(0.001)
                if index == 0:
                    wins = await asyncio.gather(
                        *(
                            manager.guess(
                                match.scope, "u", "User", match.question["answer"]
                            )
                            for _ in range(4)
                        )
                    )
                    self.assertEqual(sum(wins), 1)
                    continue
                if index == 1:
                    await self.route("秦始皇", user="bad", slash=True)
                    self.assertEqual(match.scores["bad"][1], 0)
                    await self.route("秦始皇", user="bad", slash=True)
                    self.assertIn("机会", self.sent[-1][1])
                    self.assertEqual(match.scores["bad"][1], 0)
                    await manager.hint(match.scope)
                if index in (2, 3):
                    self.assertFalse(await manager.reveal(match.scope))
                    await manager.hint(match.scope)
                    await manager.hint(match.scope)
                    self.assertEqual(match.points(), 1)
                if index == 3:
                    self.assertTrue(await manager.reveal(match.scope))
                    self.assertEqual(match.scores["bad"][1], 0)
                    continue
                self.assertTrue(
                    await manager.guess(
                        match.scope, "u", "User", match.question["answer"]
                    )
                )
            await asyncio.wait_for(match.task, 1)
        self.assertEqual(match.scores["u"][1:], [9, 4])
        self.assertEqual(match.scores["bad"][1:], [0, 0])
        self.assertFalse(
            any(
                q["explanation"] in text
                for q in manager.bank["famous_person"]
                for _, text in self.sent
            )
        )
        for instance in (self.characters, self.countries, self.games):
            self.assertEqual(
                instance.manager.db.execute("SELECT COUNT(*) FROM scores").fetchone()[
                    0
                ],
                0,
            )
            self.assertEqual(
                instance.manager.db.execute("SELECT COUNT(*) FROM recent").fetchone()[
                    0
                ],
                0,
            )
        await self.start("unfinished")
        await self.people.terminate()
        with patch.object(
            people.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.people = people.FamousPersonGuess(self.context)
        self.assertEqual(self.people.manager.sessions, {})
        self.assertIn("9 分", self.people.manager.leaderboard(match.scope))

    async def test_slashs_permissions_menu_during_match_and_stage_limit(self):
        match = await self.start()
        before = len(self.sent)
        await self.route("嬴政")
        await self.route("提示")
        self.assertEqual(len(self.sent), before)
        self.assertEqual(match.attempts, set())
        await self.route("/猜知名人物 提示")
        await self.route("提示", slash=True)
        self.assertEqual(match.hint_count, 2)
        await self.route("刘邦", slash=True, user="bad")
        await self.route("/猜知名人物 提示")
        self.assertEqual(match.attempts, {"bad"})
        plugin = menu.FunctionMenu.__new__(menu.FunctionMenu)
        plugin.context = self.context
        await plugin.guess_menu(self.event("/猜菜单"))
        self.assertTrue(
            all(
                "/" + name in self.sent[-1][1]
                for name in ("猜角色", "猜国家", "猜游戏", "猜知名人物")
            )
        )
        self.assertEqual(match.hint_count, 2)
        await self.route("/猜知名人物 结束", user="other")
        self.assertIn(match.scope, self.people.manager.sessions)
        self.assertFalse(
            people.FamousPersonAnswerFilter().filter(
                self.event("普通聊天", group="other"), {}
            )
        )
        event = self.event("普通聊天")
        await self.people.guard_chat(event)
        await self.people.guard_reply(event)
        self.assertTrue(event.stopped)
        self.assertTrue(event.get_extra("cleared"))
        await self.route("结束", user="admin", slash=True, role="admin")
        self.assertNotIn(match.scope, self.people.manager.sessions)

    async def test_four_games_exclude_each_other_including_pending_and_races(self):
        old = (
            (self.characters, "猜角色"),
            (self.countries, "猜国家"),
            (self.games, "猜游戏"),
        )
        for index, (instance, command) in enumerate(old):
            room = f"old{index}"
            await instance.game_command(self.event("/" + command, group=room))
            await self.people.game_command(self.event("/猜知名人物", group=room))
            self.assertNotIn(f"qqbot:GroupMessage:{room}", self.people.manager.sessions)
        match = await self.start("people")
        for instance, command in old:
            await instance.game_command(self.event("/" + command, group="people"))
            self.assertNotIn(match.scope, instance.manager.sessions)
            await self.route("/" + command, group="people")
            self.assertIn("猜知名人物", self.sent[-1][1])
        self.assertNotIn(match.scope, self.characters.pending)
        for index in range(4):
            room = f"race{index}"
            starters = [
                instance.game_command(self.event("/" + command, group=room))
                for instance, command in (*old, (self.people, "猜知名人物"))
            ]
            starters = starters[index:] + starters[:index]
            await asyncio.gather(*starters)
            scope = f"qqbot:GroupMessage:{room}"
            self.assertEqual(
                sum(
                    (
                        scope in self.characters.pending,
                        scope in self.countries.manager.sessions,
                        scope in self.games.manager.sessions,
                        scope in self.people.manager.sessions,
                    )
                ),
                1,
            )

    async def test_lookup_requires_one_same_real_person_and_failed_lookup_is_free(self):
        match = await self.start()
        self.people.manager.resolve_alias = AsyncMock(return_value=None)
        await self.people.manager.guess(match.scope, "u", "User", "无法核实的名字")
        self.assertEqual(match.attempts, set())
        self.assertEqual(match.scores, {})
        resolver = self.people.lookup
        for word in (
            "皇帝",
            "主席",
            "科学家",
            "总统",
            "球王",
            "小胡子",
            "元首",
            "教员",
        ):
            self.assertIsNone(await resolver.resolve(match.scope, word))
        target = next(
            q
            for q in self.people.manager.bank["famous_person"]
            if q["answer"] == "苏轼"
        )
        other = next(
            q
            for q in self.people.manager.bank["famous_person"]
            if q["answer"] == "鲁迅"
        )
        url = "https://example.com/person-alias"
        answer = {
            "ids": [target["id"]],
            "sources": [url],
            "entity_type": "person",
            "relation": "related_person",
        }
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(completion_text=json.dumps(answer))
            )
        )
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
                        "title": "东坡旧称是苏轼的别名，鲁迅另有其人",
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
            self.assertIsNone(await resolver.resolve(match.scope, "东坡旧称"))
            answer.update(relation="same_person", ids=[target["id"], other["id"]])
            provider.text_chat.return_value.completion_text = json.dumps(answer)
            self.assertIsNone(await resolver.resolve(match.scope, "东坡旧称"))
            answer["ids"] = [target["id"]]
            provider.text_chat.return_value.completion_text = json.dumps(answer)
            self.assertEqual(
                await resolver.resolve(match.scope, "东坡旧称"), {target["id"]}
            )
        self.assertIn("真实人物", search.call_args.kwargs["query"])
        kwargs = provider.text_chat.call_args.kwargs
        self.assertIn("同一真实人物", kwargs["system_prompt"])
        payload = json.loads(kwargs["prompt"])
        self.assertEqual(len(payload["roster"]), 71)
        self.assertEqual(set(payload), {"alias", "roster", "web_results"})
        self.assertEqual(kwargs["contexts"], [])
        self.assertIsNone(kwargs["func_tool"])


if __name__ == "__main__":
    unittest.main()
