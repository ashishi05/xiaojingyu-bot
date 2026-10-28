import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "AstrBot"), str(ROOT / "AstrBot")]
from astrbot.api.message_components import At, Image, Plain  # noqa: E402
from data.plugins.country_guess import main as country  # noqa: E402
from data.plugins.emoji_guess import game, lookup  # noqa: E402
from data.plugins.emoji_guess import main as character  # noqa: E402


class CountryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []
        self.stars = {}

        async def send(scope, chain):
            self.sent.append((scope, chain.chain[0].text))
            return True

        self.context = SimpleNamespace(
            send_message=send,
            get_registered_star=lambda name: self.stars.get(name),
        )
        with patch.object(
            country.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.characters = character.EmojiGuess(self.context)
            self.countries = country.CountryGuess(self.context)
        self.stars.update(
            {
                "emoji_guess": SimpleNamespace(
                    activated=True, star_cls=self.characters
                ),
                "country_guess": SimpleNamespace(
                    activated=True, star_cls=self.countries
                ),
            }
        )

    async def asyncTearDown(self):
        await self.countries.terminate()
        await self.characters.terminate()
        self.tmp.cleanup()

    def event(self, text, group="g", user="u", slash=False, role="member", parts=None):
        extra = {}
        stopped = []

        async def send(result):
            self.sent.append(("event", result))

        return SimpleNamespace(
            message_str=text,
            get_platform_name=lambda: "aiocqhttp",
            get_platform_id=lambda: "qqbot",
            get_group_id=lambda: group,
            get_sender_id=lambda: user,
            get_sender_name=lambda: "User",
            get_self_id=lambda: "bot",
            get_messages=lambda: (
                parts
                if parts is not None
                else (
                    [
                        Plain(
                            text=(
                                "/" + text
                                if slash and not text.startswith("/")
                                else text
                            )
                        )
                    ]
                )
            ),
            message_obj=SimpleNamespace(
                raw_message={"post_type": "message", "sender": {"role": role}}
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

    async def start(self, group="g"):
        with patch.object(game.random, "choice", side_effect=lambda pool: pool[0]):
            await self.countries.game_command(self.event("/猜国家", group=group))
        return self.countries.manager.sessions[f"qqbot:GroupMessage:{group}"]

    async def route(self, text, **kwargs):
        event = self.event(text, **kwargs)
        self.assertTrue(country.CountryAnswerFilter().filter(event, {}))
        await self.countries.answer(event)
        return event

    async def test_fixed_42_questions_aliases_and_no_city_synonyms(self):
        bank = self.countries.manager.bank["country"]
        self.assertEqual(len(bank), 42)
        self.assertEqual(len({q["id"] for q in bank}), 42)
        self.assertEqual(len({q["answer"] for q in bank}), 42)
        by_name = {q["answer"]: q for q in bank}
        self.assertEqual(by_name["朝鲜"]["emoji"], "☀️ ✍️ 🌸")
        self.assertEqual(by_name["印度"]["emoji"], "🪷 🧘 🍛")
        self.assertNotIn("巴基斯坦", by_name)
        self.assertTrue(all(len(q["emoji"].split()) == 3 for q in bank))
        for word in ("China", "中国", "中华人民共和国", "UK", "USA", "阿联酋", "UAE"):
            self.assertIn(game.normalize(word), self.countries.manager.known_answers)
        for word in ("迪拜", "Dubai", "北京", "Paris", "阿狸"):
            self.assertNotIn(game.normalize(word), self.countries.manager.known_answers)

    async def test_stages_wrong_attempts_reveal_and_concurrent_winner(self):
        match = await self.start()
        opening = self.sent[-1][1]
        self.assertIn("猜国家", opening)
        self.assertIn("/国家名字", opening)
        self.assertIn("每人每阶段一次", opening)
        self.assertIn("答对 +3 分", opening)
        self.assertIn("🍵", opening)
        self.assertNotIn("🧱", opening)
        self.assertNotIn("中国", opening)
        self.assertEqual(len({q["id"] for q in match.questions}), 5)
        manager = self.countries.manager
        scope = match.scope
        self.assertFalse(await manager.guess(scope, "u", "User", "Japan"))
        self.assertEqual(match.scores["u"][1], 0)
        self.assertFalse(await manager.guess(scope, "u", "User", "China"))
        self.assertFalse(await manager.reveal(scope))
        await manager.hint(scope)
        winners = await asyncio.gather(
            *(manager.guess(scope, str(i), "Player", "China") for i in range(5))
        )
        self.assertEqual(sum(winners), 1)
        self.assertEqual(sum(row[1] for row in match.scores.values()), 2)
        await manager.cancel(scope)
        match = await self.start("reveal")
        await manager.hint(match.scope)
        await manager.hint(match.scope)
        self.assertEqual(match.points(), 1)
        results = await asyncio.gather(*(manager.reveal(match.scope) for _ in range(5)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(match.scores, {})
        await manager.cancel(match.scope)
        await asyncio.sleep(0.01)
        self.assertNotIn(match.scope, manager.sessions)

    async def test_slashs_permissions_and_chat_gate_are_scoped(self):
        match = await self.start()
        await self.route("China")
        self.assertEqual(match.attempts, set())
        await self.route("提示")
        self.assertEqual(match.hint_count, 0)
        await self.route("/猜国家 提示")
        self.assertEqual(match.hint_count, 1)
        await self.route("提示", slash=True)
        self.assertEqual(match.hint_count, 2)
        await self.route("结束", user="other", slash=True)
        self.assertIn(match.scope, self.countries.manager.sessions)
        for parts in (
            [At(qq="other"), Plain(text="China")],
            [At(qq="bot"), Image(file="x")],
        ):
            await self.route("China", parts=parts)
            self.assertEqual(match.attempts, set())
        self.assertFalse(
            country.CountryAnswerFilter().filter(self.event("China", group="other"), {})
        )
        event = self.event("普通聊天")
        await self.countries.guard_chat(event)
        self.assertTrue(event.stopped)
        event = self.event("已生成的普通回复")
        await self.countries.guard_reply(event)
        self.assertTrue(event.get_extra("cleared"))
        await self.route("结束", user="admin", slash=True, role="admin")
        self.assertNotIn(match.scope, self.countries.manager.sessions)
        self.assertFalse(
            country.CountryAnswerFilter().filter(self.event("普通聊天"), {})
        )

    async def test_cross_game_exclusion_including_pending_and_racing_starts(self):
        await self.characters.game_command(self.event("/猜角色"))
        await self.countries.game_command(self.event("/猜国家"))
        self.assertEqual(self.countries.manager.sessions, {})
        self.assertIn("qqbot:GroupMessage:g", self.characters.pending)
        await self.start("other")
        await self.characters.game_command(self.event("/猜角色", group="other"))
        self.assertNotIn("qqbot:GroupMessage:other", self.characters.pending)
        await self.route("/猜角色", group="other")
        self.assertIn("猜国家", self.sent[-1][1])
        for index in range(4):
            room = f"race{index}"
            pair = [
                self.characters.game_command(self.event("/猜角色", group=room)),
                self.countries.game_command(self.event("/猜国家", group=room)),
            ]
            if index % 2:
                pair.reverse()
            await asyncio.gather(*pair)
            scope = f"qqbot:GroupMessage:{room}"
            self.assertEqual(
                int(scope in self.characters.pending)
                + int(scope in self.countries.manager.sessions),
                1,
            )

    async def test_five_rounds_score_persistence_and_independent_storage(self):
        manager = self.countries.manager
        with patch.object(game, "GAP_SECONDS", 0.001):
            match = await self.start()
            for index in range(5):
                async with asyncio.timeout(1):
                    while match.index != index or match.phase != "answering":  # noqa: ASYNC110 - observe round transitions.
                        await asyncio.sleep(0.001)
                await manager.guess(match.scope, "u", "User", match.question["answer"])
            await asyncio.wait_for(match.task, 1)
        self.assertIn("15 分", manager.leaderboard(match.scope))
        self.assertIn("猜猜杯", manager.leaderboard(match.scope))
        self.assertIn("15 分", self.characters.manager.leaderboard(match.scope))
        await self.start("unfinished")
        await self.countries.terminate()
        with patch.object(
            country.StarTools,
            "get_data_dir",
            side_effect=lambda name: Path(self.tmp.name) / name,
        ):
            self.countries = country.CountryGuess(self.context)
        self.assertEqual(self.countries.manager.sessions, {})
        self.assertIn("15 分", self.countries.manager.leaderboard(match.scope))

    async def test_unknown_alias_is_free_and_country_lookup_rejects_cities(self):
        match = await self.start()
        self.countries.lookup.context = SimpleNamespace()
        self.assertFalse(
            await self.countries.manager.guess(match.scope, "u", "User", "Dubai")
        )
        self.assertEqual(match.attempts, {"u"})
        self.assertEqual(match.scores["u"][1], 0)
        country_id = match.question["id"]
        url = "https://example.com/country-alias"
        answer = {
            "ids": [country_id],
            "sources": [url],
            "entity_type": "city",
            "relation": "part_of",
        }
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(completion_text=json.dumps(answer))
            )
        )
        self.countries.lookup.context = SimpleNamespace(
            get_config=lambda **kwargs: {
                "provider_settings": {
                    "web_search": True,
                    "websearch_provider": "deepseek",
                }
            },
            get_using_provider_async=AsyncMock(return_value=provider),
        )
        evidence = json.dumps(
            {"results": [{"url": url, "title": "测试别称和中国", "snippet": ""}]}
        )
        with patch.object(
            lookup.DeepSeekWebSearchTool,
            "call",
            new_callable=AsyncMock,
            return_value=evidence,
        ) as search:
            self.assertIsNone(
                await self.countries.lookup.resolve(match.scope, "测试别称")
            )
            answer.update(entity_type="country", relation="same_entity")
            provider.text_chat.return_value.completion_text = json.dumps(answer)
            self.assertEqual(
                await self.countries.lookup.resolve(match.scope, "测试别称"),
                {country_id},
            )
        self.assertIn("国家", search.call_args.kwargs["query"])
        kwargs = provider.text_chat.call_args.kwargs
        self.assertEqual(kwargs["contexts"], [])
        self.assertIsNone(kwargs["func_tool"])
        self.assertEqual(
            set(json.loads(kwargs["prompt"])), {"alias", "roster", "web_results"}
        )


if __name__ == "__main__":
    unittest.main()
