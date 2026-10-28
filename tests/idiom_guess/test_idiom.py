import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "AstrBot"), str(ROOT / "tests/network_person_guess")]
import test_network as support  # noqa: E402

from data.plugins.emoji_guess import game, lookup  # noqa: E402
from data.plugins.function_menu import main as menu  # noqa: E402
from data.plugins.idiom_guess import main as idiom  # noqa: E402


class IdiomTests(unittest.IsolatedAsyncioTestCase):
    event = support.NetworkTests.event

    async def asyncSetUp(self):
        await support.NetworkTests.asyncSetUp(self)
        with patch.object(
            idiom.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.idioms = idiom.IdiomGuess(self.context)
        self.stars["idiom_guess"] = SimpleNamespace(
            activated=True, star_cls=self.idioms
        )

    async def asyncTearDown(self):
        await self.idioms.terminate()
        await support.NetworkTests.asyncTearDown(self)

    async def route(self, text, **kwargs):
        event = self.event(text, **kwargs)
        self.assertTrue(idiom.IdiomAnswerFilter().filter(event, {}))
        await self.idioms.answer(event)
        return event

    async def test_curated_four_clues_five_questions_and_existing_cup_total(self):
        manager = self.idioms.manager
        bank = manager.bank["idiom"]
        self.assertEqual(len(bank), 481)
        self.assertEqual(len({q["id"] for q in bank}), 481)
        self.assertEqual(len({q["emoji"] for q in bank}), 481)
        self.assertTrue(
            all(len(q["emoji"].split()) == 4 and len(q["answer"]) == 4 for q in bank)
        )
        scope = "qqbot:GroupMessage:g"
        await self.countries.manager.start(scope, "u", "country")
        await self.countries.manager.guess(
            scope,
            "u",
            "User",
            self.countries.manager.sessions[scope].question["answer"],
        )
        await self.countries.manager.cancel(scope)
        with patch.object(game.random, "choice", side_effect=lambda pool: pool[0]):
            await self.idioms.game_command(self.event("/猜成语"))
        match = manager.sessions[scope]
        self.assertEqual(match.clue, "🧍 🌳")
        self.assertNotIn(match.question["answer"], self.sent[-1][1])
        self.assertIn("4 个 Emoji", self.sent[-1][1])
        self.assertIn("3 分", manager.leaderboard(scope))
        await self.route(match.question["answer"])
        self.assertEqual(match.attempts, set())
        await self.route("/揭秘")
        self.assertEqual(match.phase, "answering")
        self.assertIn("四个", self.sent[-1][1])
        for index in range(5):
            async with asyncio.timeout(1):
                while match.index != index or match.phase != "answering":  # noqa: ASYNC110
                    await asyncio.sleep(0)
            for _ in range(index % 3):
                await self.route("/提示")
            self.assertEqual(len(match.clue.split()), 2 + index % 3)
            if index == 3:
                await self.route("/提示")
                await self.route("/提示")
                await self.route("/揭秘")
            else:
                await self.route("/" + match.question["answer"])
        await asyncio.wait_for(match.task, 1)
        self.assertIn("11 分", self.sent[-1][1])
        self.assertIn("/换个猜", self.sent[-1][1])
        self.assertIn("• /猜成语", self.sent[-1][1])
        self.assertEqual(match.scores["u"][1:], [8, 4])
        controller = menu.FunctionMenu.__new__(menu.FunctionMenu)
        controller.context = self.context
        await controller.end_game(self.event("/结束"))
        self.assertIn("11 分", self.sent[-1][1])
        self.assertIn("本场积分已清零", self.sent[-1][1])
        self.assertIn("本场积分为 0", self.countries.manager.leaderboard(scope))
        self.assertEqual(
            manager.db.execute(
                "SELECT points FROM scores WHERE scope=?", (scope,)
            ).fetchone()[0],
            8,
        )

    async def test_six_games_exclude_each_other_and_menu_does_not_reset_stage(self):
        all_games = [
            (self.characters, "猜角色"),
            (self.countries, "猜国家"),
            (self.games, "猜游戏"),
            (self.people, "猜知名人物"),
            (self.network, "猜网络人物"),
            (self.idioms, "猜成语"),
        ]
        for index in range(6):
            room = f"race{index}"
            calls = [
                plugin.game_command(self.event("/" + command, group=room))
                for plugin, command in all_games
            ]
            await asyncio.gather(*(calls[index:] + calls[:index]))
            scope = f"qqbot:GroupMessage:{room}"
            self.assertEqual(
                sum(
                    scope in plugin.manager.sessions
                    or scope in getattr(plugin, "pending", {})
                    for plugin, _ in all_games
                ),
                1,
            )
        room = "menu"
        scope = f"qqbot:GroupMessage:{room}"
        await self.idioms.game_command(self.event("/猜成语", group=room))
        await self.route("/提示", group=room)
        match = self.idioms.manager.sessions[scope]
        controller = menu.FunctionMenu.__new__(menu.FunctionMenu)
        controller.context = self.context
        await controller.guess_menu(self.event("/换个猜", group=room))
        self.assertTrue(
            all("/" + command in self.sent[-1][1] for _, command in all_games)
        )
        self.assertEqual(match.hint_count, 1)
        await self.route("/提示", group=room)
        await self.route("/提示", group=room)
        self.assertEqual(self.sent[-1][1], "可揭秘或继续答题")
        self.assertEqual(len(match.clue.split()), 4)

    async def test_model_alias_and_known_other_idiom_remain_distinct(self):
        resolver = self.idioms.lookup
        target = next(iter(resolver.names))
        provider = SimpleNamespace(text_chat=AsyncMock())
        resolver.context = SimpleNamespace(
            get_config=lambda **kwargs: {"provider_settings": {"web_search": False}},
            get_using_provider_async=AsyncMock(return_value=provider),
        )
        with patch.object(
            lookup.DeepSeekWebSearchTool, "call", new_callable=AsyncMock
        ) as search:
            answer = {
                "certain": True,
                "ids": [target],
                "entity_type": "idiom",
                "relation": "same_entity",
                "reason": "同一成语的字形变体",
            }
            provider.text_chat.return_value = SimpleNamespace(
                completion_text=json.dumps(answer)
            )
            self.assertEqual(await resolver.resolve("scope", "守株待兎"), {target})
            answer.update(
                ids=[],
                relation="different_entity",
                identity="画蛇添足",
                reason="另一个独立成语，不能作为近义答案替换",
            )
            provider.text_chat.return_value = SimpleNamespace(
                completion_text=json.dumps(answer)
            )
            self.assertEqual(await resolver.resolve("scope", "画蛇添足"), set())
            search.assert_not_awaited()
        self.assertIn(
            "近义但不同", provider.text_chat.call_args.kwargs["system_prompt"]
        )


if __name__ == "__main__":
    unittest.main()
