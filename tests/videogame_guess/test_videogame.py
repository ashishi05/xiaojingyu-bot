import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "AstrBot"),
    str(ROOT / "AstrBot"),
    str(ROOT / "tests/country_guess"),
]
import test_country as support  # noqa: E402

from data.plugins.emoji_guess import game, lookup  # noqa: E402
from data.plugins.videogame_guess import main as video  # noqa: E402


class VideogameTests(unittest.IsolatedAsyncioTestCase):
    event = support.CountryTests.event

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []
        self.stars = {}

        async def send(scope, chain):
            self.sent.append((scope, chain.chain[0].text))
            return True

        self.context = SimpleNamespace(
            send_message=send, get_registered_star=lambda name: self.stars.get(name)
        )
        with patch.object(
            video.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.characters = support.character.EmojiGuess(self.context)
            self.countries = support.country.CountryGuess(self.context)
            self.games = video.VideogameGuess(self.context)
        for name, instance in (
            ("emoji_guess", self.characters),
            ("country_guess", self.countries),
            ("videogame_guess", self.games),
        ):
            self.stars[name] = SimpleNamespace(activated=True, star_cls=instance)

    async def asyncTearDown(self):
        await self.games.terminate()
        await self.countries.terminate()
        await self.characters.terminate()
        self.tmp.cleanup()

    async def start(self, room="g"):
        with patch.object(game.random, "choice", side_effect=lambda pool: pool[0]):
            await self.games.game_command(self.event("/猜游戏", group=room))
        return self.games.manager.sessions[f"qqbot:GroupMessage:{room}"]

    async def route(self, text, **kwargs):
        event = self.event(text, **kwargs)
        self.assertTrue(video.VideogameAnswerFilter().filter(event, {}))
        await self.games.answer(event)
        return event

    async def test_exact_55_questions_and_whole_name_aliases(self):
        bank = self.games.manager.bank["videogame"]
        self.assertEqual(len(bank), 55)
        self.assertEqual(len({q["id"] for q in bank}), 55)
        self.assertEqual(len({q["emoji"] for q in bank}), 55)
        self.assertTrue(all(len(q["emoji"].split()) == 3 for q in bank))
        owners = {}
        for question in bank:
            for alias in question["answers"]:
                key = game.normalize(alias)
                self.assertTrue(key)
                self.assertIn(owners.get(key), (None, question["id"]))
                owners[key] = question["id"]
        for name in (
            "CS:GO",
            "cs2",
            "都市天际线",
            "地平线5",
            "GTA V",
            "文明",
            "模拟人生4",
        ):
            self.assertIn(game.normalize(name), owners)
        for name in (
            "Among Us",
            "和平精英",
            "地平线：零之曙光",
            "吃鸡",
            "赛车",
            "塔防",
            "魔兽",
            "极限竞速",
            "我猜是我的世界",
        ):
            self.assertNotIn(game.normalize(name), owners)
        self.assertNotEqual(
            owners[game.normalize("极品飞车")], owners[game.normalize("地平线5")]
        )
        self.assertNotEqual(
            owners[game.normalize("王者荣耀")], owners[game.normalize("英雄联盟")]
        )

    async def test_five_rounds_scoring_reveal_hidden_explanations_and_persistence(self):
        manager = self.games.manager
        with patch.object(game, "GAP_SECONDS", 0.001):
            match = await self.start()
            self.assertEqual(len({q["id"] for q in match.questions}), 5)
            self.assertEqual(match.clue, "⛏️")
            self.assertIn("答对 +3 分", self.sent[-1][1])
            for index in range(5):
                async with asyncio.timeout(1):
                    while match.index != index or match.phase != "answering":  # noqa: ASYNC110 - observe production transitions.
                        await asyncio.sleep(0.001)
                if index == 1:
                    await manager.guess(match.scope, "bad", "Wrong", "我的世界")
                    self.assertEqual(match.scores["bad"][1], 0)
                    await manager.guess(match.scope, "bad", "Wrong", "我的世界")
                    self.assertEqual(match.scores["bad"][1], 0)
                    await manager.hint(match.scope)
                if index in (2, 3):
                    self.assertFalse(await manager.reveal(match.scope))
                    await manager.hint(match.scope)
                    await manager.hint(match.scope)
                    self.assertEqual(match.points(), 1)
                if index == 3:
                    self.assertTrue(await manager.reveal(match.scope))
                    continue
                self.assertTrue(
                    await manager.guess(
                        match.scope, "u", "User", match.question["answer"]
                    )
                )
            await asyncio.wait_for(match.task, 1)
        self.assertEqual(match.scores["u"][1:], [9, 4])
        self.assertEqual(match.scores["bad"][1:], [0, 0])
        for question in manager.bank["videogame"]:
            self.assertFalse(
                any(question["explanation"] in text for _, text in self.sent)
            )
        self.assertFalse(any("仅追加第二个 Emoji" in text for _, text in self.sent))
        for other in (self.characters, self.countries):
            self.assertEqual(
                other.manager.db.execute("SELECT COUNT(*) FROM scores").fetchone()[0], 0
            )
            self.assertEqual(
                other.manager.db.execute("SELECT COUNT(*) FROM recent").fetchone()[0], 0
            )
        await self.start("unfinished")
        await self.games.terminate()
        with patch.object(
            video.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.games = video.VideogameGuess(self.context)
        self.assertEqual(self.games.manager.sessions, {})
        self.assertIn("9 分", self.games.manager.leaderboard(match.scope))
        self.assertIn("猜猜杯", self.games.manager.leaderboard(match.scope))

    async def test_real_slashs_controls_and_scoped_chat_gate(self):
        match = await self.start()
        before = len(self.sent)
        await self.route("Minecraft")
        await self.route("提示")
        self.assertEqual(len(self.sent), before)
        self.assertEqual(match.attempts, set())
        await self.route("/猜游戏 提示")
        self.assertEqual(match.hint_count, 1)
        await self.route("Minecraft", slash=True)
        self.assertEqual(match.scores["u"][1], 2)
        event = self.event("普通聊天")
        await self.games.guard_chat(event)
        self.assertTrue(event.stopped)
        await self.games.guard_reply(event)
        self.assertTrue(event.get_extra("cleared"))
        self.assertFalse(
            video.VideogameAnswerFilter().filter(
                self.event("普通聊天", group="other"), {}
            )
        )
        await self.route("/猜游戏 结束", user="other")
        self.assertIn(match.scope, self.games.manager.sessions)
        await self.route("/猜游戏 结束", user="admin", role="admin")
        self.assertNotIn(match.scope, self.games.manager.sessions)

    async def test_three_game_exclusion_pending_routing_and_racing_starts(self):
        await self.characters.game_command(self.event("/猜角色"))
        await self.games.game_command(self.event("/猜游戏"))
        self.assertEqual(self.games.manager.sessions, {})
        await self.countries.game_command(self.event("/猜国家", group="country"))
        await self.games.game_command(self.event("/猜游戏", group="country"))
        self.assertNotIn("qqbot:GroupMessage:country", self.games.manager.sessions)
        match = await self.start("video")
        for other, command in ((self.characters, "猜角色"), (self.countries, "猜国家")):
            await other.game_command(self.event("/" + command, group="video"))
            self.assertNotIn(match.scope, other.manager.sessions)
            await self.route("/" + command, group="video")
            self.assertIn("猜游戏", self.sent[-1][1])
        self.assertNotIn(match.scope, self.characters.pending)
        for index in range(3):
            room = f"race{index}"
            starters = [
                self.characters.game_command(self.event("/猜角色", group=room)),
                self.countries.game_command(self.event("/猜国家", group=room)),
                self.games.game_command(self.event("/猜游戏", group=room)),
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
                    )
                ),
                1,
            )

    async def test_lookup_series_evidence_no_clues_and_unconfirmed_refund(self):
        match = await self.start()
        self.games.manager.resolve_alias = AsyncMock(return_value=None)
        await self.games.manager.guess(match.scope, "u", "User", "陌生别名")
        self.assertEqual(match.attempts, set())
        self.assertEqual(match.scores, {})
        resolver = self.games.lookup
        for name in (
            "地平线：零之曙光",
            "Horizon Forbidden West",
            "和平精英",
            "战舰世界闪击战",
            "赛车",
            "魔兽",
            "极限竞速",
        ):
            result = await resolver.resolve(match.scope, name)
            if name in {"赛车", "魔兽", "极限竞速"}:
                self.assertIsNone(result)
            else:
                self.assertEqual(result, set())
        target = next(
            q for q in self.games.manager.bank["videogame"] if "CS:GO" in q["answers"]
        )
        url = "https://example.com/game-series"
        response = {
            "ids": [target["id"]],
            "sources": [url],
            "entity_type": "videogame",
            "relation": "similar_game",
        }
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(completion_text=json.dumps(response))
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
        evidence = json.dumps(
            {
                "results": [
                    {"url": url, "title": "CS旧称是Counter-Strike的别名", "snippet": ""}
                ]
            }
        )
        with patch.object(
            lookup.DeepSeekWebSearchTool,
            "call",
            new_callable=AsyncMock,
            return_value=evidence,
        ) as search:
            self.assertIsNone(await resolver.resolve(match.scope, "CS旧称"))
            response["relation"] = "same_series"
            provider.text_chat.return_value.completion_text = json.dumps(response)
            self.assertEqual(
                await resolver.resolve(match.scope, "CS旧称"), {target["id"]}
            )
        self.assertIn("游戏作品", search.call_args.kwargs["query"])
        kwargs = provider.text_chat.call_args.kwargs
        payload = json.loads(kwargs["prompt"])
        self.assertEqual(len(payload["roster"]), 55)
        self.assertEqual(set(payload), {"alias", "roster", "web_results"})
        self.assertEqual(kwargs["contexts"], [])
        self.assertIsNone(kwargs["func_tool"])


if __name__ == "__main__":
    unittest.main()
