import asyncio
import importlib.util
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / "AstrBot/data/plugins"
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.find_spec("emoji_guess.game")
if SPEC:
    from emoji_guess import game
else:
    game = None


class GameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(game, "The approved game engine has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []

        async def send(scope, text):
            self.sent.append((scope, text))

        self.bank = json.loads((ROOT / "emoji_guess/questions.json").read_text("utf-8"))
        self.manager = game.GameManager(self.bank, Path(self.tmp.name), send)

    async def asyncTearDown(self):
        if hasattr(self, "manager"):
            await self.manager.close()
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    async def test_immediate_next_question_and_compact_output(self):
        self.assertEqual(game.GAP_SECONDS, 0)
        await self.manager.start("instant", "u", "lol")
        match = self.manager.sessions["instant"]
        question = match.question
        await self.manager.guess("instant", "u", "User", question["answer"])
        for _ in range(10):
            await asyncio.sleep(0)
            if match.index == 1:
                break
        self.assertEqual(match.index, 1)
        self.assertEqual(match.phase, "answering")
        self.assertNotIn("每人每阶段", self.sent[-1][1])
        self.assertNotIn(question["explanation"], self.sent[-2][1])
        self.assertIn("答对 +3 分", self.sent[-1][1])

    async def test_bank_contains_all_296_roles_and_shared_form_aliases(self):
        self.assertEqual(sum(q["game"] == "lol" for q in self.bank), 173)
        self.assertEqual(sum(q["game"] == "val" for q in self.bank), 30)
        self.assertEqual(len({q["id"] for q in self.bank}), 296)
        self.assertEqual(sum(q["game"] == "hsr" for q in self.bank), 93)
        self.assertTrue(all(len(q["emoji"].split()) == 3 for q in self.bank))

    async def test_normalization_is_exact_not_substring_or_multiple_names(self):
        self.assertEqual(game.normalize("  KAY/O！ "), "kayo")
        self.assertIn(game.normalize("洛"), self.manager.known_answers)
        self.assertNotEqual(game.normalize("洛克"), game.normalize("洛"))
        self.assertNotIn(game.normalize("阿狸、锤石"), self.manager.known_answers)
        self.assertNotIn(game.normalize("我觉得阿狸不错"), self.manager.known_answers)

    async def test_one_session_per_scope_and_mixed_uses_combined_pool_without_repeats(
        self,
    ):
        with patch.object(
            game.random, "choice", side_effect=lambda pool: pool[0]
        ) as choice:
            await self.manager.start("group-a", "owner", "mixed")
        self.assertEqual(len(choice.call_args_list[0].args[0]), 203)
        match = self.manager.sessions["group-a"]
        self.assertEqual(len({q["id"] for q in match.questions}), 5)
        self.assertEqual({q["game"] for q in match.questions}, {"lol"})
        self.assertEqual(self.sent[-1][1].splitlines()[0], "🎮 猜角色 · 第 1/5 题")
        self.assertIn("/角色名字：每人每阶段一次", self.sent[-1][1])
        self.assertNotIn("角色池：", self.sent[-1][1])
        with self.assertRaisesRegex(ValueError, "已经"):
            await self.manager.start("group-a", "other", "lol")

    async def test_stage_score_and_first_winner_only(self):
        for stage in range(3):
            scope = str(stage)
            await self.manager.start(scope, "owner", "lol")
            match = self.manager.sessions[scope]
            for _ in range(stage):
                await self.manager.hint(scope)
            match.started_at -= 3600
            self.assertTrue(
                await self.manager.guess(scope, "u", "User", match.question["answer"])
            )
            self.assertEqual(match.scores["u"][1], 3 - stage)
            self.assertFalse(
                await self.manager.guess(scope, "v", "Other", match.question["answer"])
            )

    async def test_simultaneous_correct_answers_award_once(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        answer = match.question["answer"]
        results = await asyncio.gather(
            *(self.manager.guess("a", str(i), str(i), answer) for i in range(15))
        )
        self.assertEqual(sum(results), 1)
        self.assertEqual(sum(row[1] for row in match.scores.values()), 3)

    async def test_manual_hints_lower_score_and_do_not_leak_next_answer(self):
        await self.manager.start("a", "owner", "val")
        match = self.manager.sessions["a"]
        parts = match.question["emoji"].split()
        self.assertEqual(len(parts), 3)
        self.assertIn("\n\n" + parts[0] + "\n\n", self.sent[-1][1])
        self.assertNotIn(parts[1], self.sent[-1][1])
        self.assertNotIn(parts[2], self.sent[-1][1])
        self.assertTrue(await self.manager.hint("a"))
        self.assertTrue(await self.manager.hint("a"))
        self.assertFalse(await self.manager.hint("a"))
        self.assertEqual(match.hint_count, 2)
        self.assertTrue(self.sent[-2][1].startswith(" ".join(parts[:2]) + "\n"))
        self.assertTrue(self.sent[-1][1].startswith(" ".join(parts) + "\n"))
        for hint in match.question["hints"]:
            self.assertNotIn(hint, "\n".join(text for _, text in self.sent))
        self.assertTrue(
            await self.manager.guess("a", "u", "User", match.question["answer"])
        )
        self.assertEqual(match.scores["u"][1], 1)

    async def test_each_player_gets_one_guess_per_stage_and_hint_resets_attempts(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        wrong = next(
            q["answer"]
            for q in self.bank
            if q["game"] == "lol" and q["id"] != match.question["id"]
        )
        before = len(self.sent)
        self.assertFalse(await self.manager.guess("a", "u", "User", wrong))
        self.assertEqual(len(self.sent), before + 1)
        self.assertIn("猜错", self.sent[-1][1])
        self.assertNotIn("不扣分", self.sent[-1][1])
        self.assertFalse(
            await self.manager.guess("a", "u", "User", match.question["answer"])
        )
        match.started_at -= 3600
        self.assertFalse(
            await self.manager.guess("a", "u", "User", match.question["answer"])
        )
        self.assertTrue(await self.manager.hint("a"))
        self.assertTrue(
            await self.manager.guess("a", "u", "User", match.question["answer"])
        )

    async def test_native_scopes_scores_and_stop_permissions_are_isolated(self):
        await self.manager.start("group-a", "owner", "lol")
        await self.manager.start("group-b", "owner", "val")
        match = self.manager.sessions["group-a"]
        await self.manager.guess("group-a", "u", "User", match.question["answer"])
        self.assertIn("User", self.manager.leaderboard("group-a"))
        self.assertNotIn("User", self.manager.leaderboard("group-b"))
        with self.assertRaises(PermissionError):
            await self.manager.stop("group-b", "stranger")
        self.assertTrue(await self.manager.stop("group-b", "moderator", admin=True))
        self.assertIn("group-a", self.manager.sessions)

    async def test_attempt_limit_applies_to_all_three_stages_and_is_per_player(self):
        await self.manager.start("a", "owner", "val")
        match = self.manager.sessions["a"]
        for stage in range(3):
            self.assertFalse(
                await self.manager.guess(
                    "a",
                    "u",
                    "User",
                    next(
                        q["answer"]
                        for q in self.bank
                        if q["id"] != match.question["id"]
                    ),
                )
            )
            self.assertFalse(
                await self.manager.guess("a", "u", "User", match.question["answer"])
            )
            if stage < 2:
                self.assertTrue(await self.manager.hint("a"))
        self.assertFalse(await self.manager.hint("a"))
        self.assertFalse(
            await self.manager.guess("a", "u", "User", match.question["answer"])
        )
        self.assertTrue(
            await self.manager.guess("a", "v", "Other", match.question["answer"])
        )
        self.assertEqual(match.scores["v"][1], 1)
        self.assertEqual(match.scores["u"][1], 0)
        self.assertNotIn("User · 0 分", self.manager.leaderboard("a"))

    async def test_scores_and_recent_questions_survive_reload(self):
        await self.manager.start("a", "owner", "val")
        first = self.manager.sessions["a"].question
        await self.manager.guess("a", "u", "User", first["answer"])
        await self.manager.close()
        self.manager = game.GameManager(
            self.bank, Path(self.tmp.name), lambda scope, text: asyncio.sleep(0)
        )
        self.assertEqual(self.manager.sessions, {})
        self.assertIn("User", self.manager.leaderboard("a"))
        await self.manager.start("a", "owner", "val")
        self.assertNotIn(
            first["id"], {q["id"] for q in self.manager.sessions["a"].questions}
        )

    async def test_no_automatic_reveal_and_stop_cancels_waiting_match(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        count = len(self.sent)
        match.started_at -= 3600
        await asyncio.sleep(0.08)
        self.assertEqual(len(self.sent), count)
        self.assertEqual(match.hint_count, 0)
        self.assertEqual(match.phase, "answering")
        await self.manager.stop("a", "owner")
        count = len(self.sent)
        await asyncio.sleep(0.02)
        self.assertEqual(len(self.sent), count)
        self.assertTrue(match.task.done())

    async def test_old_stage_answer_does_not_consume_new_stage_attempt(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        arrived = time.perf_counter()
        await self.manager.hint("a")
        self.assertFalse(
            await self.manager.guess(
                "a", "u", "User", match.question["answer"], arrived
            )
        )
        self.assertTrue(
            await self.manager.guess("a", "u", "User", match.question["answer"])
        )
        self.assertEqual(match.scores["u"][1], 2)

    async def test_send_failure_cleans_session_and_tasks(self):
        async def broken(scope, text):
            raise OSError("simulated transport failure")

        await self.manager.close()
        self.manager = game.GameManager(self.bank, Path(self.tmp.name), broken)
        with (
            self.assertLogs("emoji_guess.game", level="ERROR"),
            self.assertRaises(RuntimeError),
        ):
            await self.manager.start("a", "owner", "lol")
        self.assertNotIn("a", self.manager.sessions)

    async def test_winner_delivery_failure_aborts_the_rest_of_the_match(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]

        async def broken(scope, text):
            raise OSError("simulated winner-message failure")

        self.manager._send_callback = broken
        with self.assertRaises(OSError):
            await self.manager.guess("a", "u", "User", match.question["answer"])
        self.assertNotIn("a", self.manager.sessions)
        self.assertTrue(match.task.done())

    async def test_reveal_only_after_all_clues_advances_without_score(self):
        with patch.object(game, "GAP_SECONDS", 0.002):
            await self.manager.start("a", "owner", "mixed")
            match = self.manager.sessions["a"]
            for stage in range(2):
                self.assertFalse(await self.manager.reveal("a"))
                self.assertEqual(match.phase, "answering")
                await self.manager.hint("a")
            answer = match.question["answer"]
            results = await asyncio.gather(
                *(self.manager.reveal("a") for _ in range(8))
            )
            self.assertEqual(sum(results), 1)
            self.assertEqual(
                sum(answer in text and "揭秘" in text for _, text in self.sent), 1
            )
            self.assertEqual(match.scores, {})
            self.assertEqual(
                self.manager.db.execute("SELECT COUNT(*) FROM scores").fetchone()[0], 0
            )
            async with asyncio.timeout(1):
                while match.index != 1 or match.phase != "answering":  # noqa: ASYNC110 - observe production round transitions.
                    await asyncio.sleep(0.001)
            self.assertEqual(match.hint_count, 0)
            self.assertEqual(match.attempts, set())

    async def test_unknown_alias_resolves_before_scoring_and_failed_lookup_is_free(
        self,
    ):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        calls = []

        async def resolve(scope, text):
            calls.append(text)
            return None if text == "unverified" else {match.question["id"]}

        self.manager.resolve_alias = resolve
        self.assertFalse(await self.manager.guess("a", "u", "User", "unverified"))
        self.assertNotIn("u", match.attempts)
        self.assertEqual(match.scores, {})
        self.assertTrue(await self.manager.guess("a", "u", "User", "alternate-name"))
        self.assertEqual(match.scores["u"][1], 3)
        self.assertEqual(calls, ["unverified", "alternate-name"])

    async def test_hint_while_alias_lookup_pending_discards_old_stage_result(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        pending, release = asyncio.Event(), asyncio.Event()

        async def resolve(scope, text):
            pending.set()
            await release.wait()
            return {match.question["id"]}

        self.manager.resolve_alias = resolve
        guess = asyncio.create_task(
            self.manager.guess("a", "u", "User", "alternate-name")
        )
        try:
            await asyncio.wait_for(pending.wait(), 1)
            await asyncio.wait_for(self.manager.hint("a"), 1)
            release.set()
            self.assertFalse(await guess)
            self.assertEqual(match.scores, {})
            self.assertNotIn("u", match.attempts)
            self.assertTrue(
                await self.manager.guess("a", "u", "User", match.question["answer"])
            )
        finally:
            release.set()
            await asyncio.gather(guess, return_exceptions=True)

    async def test_old_stop_delivery_failure_preserves_replacement_match(self):
        await self.manager.start("a", "owner", "lol")
        pending = asyncio.Event()
        release = asyncio.Event()

        async def delayed(scope, text):
            if text.startswith("本场已结束"):
                pending.set()
                await release.wait()
                raise OSError("Old stop delivery failed")

        self.manager._send_callback = delayed
        stopped = asyncio.create_task(self.manager.stop("a", "owner"))
        try:
            await asyncio.wait_for(pending.wait(), 1)
            await self.manager.start("a", "owner", "val")
            replacement = self.manager.sessions["a"]
            release.set()
            with self.assertRaises(OSError):
                await stopped
            self.assertIs(self.manager.sessions.get("a"), replacement)
            self.assertFalse(replacement.task.done())
        finally:
            release.set()
            await asyncio.gather(stopped, return_exceptions=True)

    async def test_database_failure_cancels_without_awarding(self):
        await self.manager.start("a", "owner", "lol")
        match = self.manager.sessions["a"]
        self.manager.db.close()
        with self.assertRaises(sqlite3.Error):
            await self.manager.guess("a", "u", "User", match.question["answer"])
        self.assertNotIn("a", self.manager.sessions)
        self.assertEqual(match.scores, {})
        self.assertTrue(match.task.done())

    async def test_five_correct_answers_finish_and_preserve_total_score(self):
        with patch.object(game, "GAP_SECONDS", 0.002):
            await self.manager.start("a", "owner", "mixed")
            match = self.manager.sessions["a"]
            for index in range(5):
                async with asyncio.timeout(1):
                    while match.index != index or match.phase != "answering":  # noqa: ASYNC110 - observe production round transitions.
                        await asyncio.sleep(0.001)
                self.assertTrue(
                    await self.manager.guess("a", "u", "User", match.question["answer"])
                )
            await asyncio.wait_for(match.task, 1)
        self.assertNotIn("a", self.manager.sessions)
        self.assertEqual(match.scores["u"][1:], [15, 5])
        self.assertIn("15 分", self.manager.leaderboard("a"))

    async def test_hsr_shared_aliases_and_specific_forms(self):
        by_name = {q["answer"]: q for q in self.bank if q["game"] == "hsr"}
        self.assertEqual(len(by_name), 93)
        groups = [
            (["毁灭主", "存护主", "同谐主", "记忆主", "欢愉主"], "开拓者"),
            (["丹恒", "丹恒·饮月", "丹恒·腾荒"], "SP丹恒"),
            (["刃", "千冶·刃"], "应星"),
            (["姬子", "姬子·启行"], "Himeko"),
            (["黑塔", "大黑塔"], "Herta"),
            (["银狼", "银狼LV.999"], "Silver Wolf"),
            (["知更鸟", "知更鸟·晴歌"], "Robin"),
            (["砂金", "砂金·戏浪"], "小孔雀"),
            (["三月七（存护）", "三月七（巡猎）", "长夜月"], "March 7th"),
            (["停云", "忘归人"], "Tingyun"),
        ]
        await self.manager.start("hsr", "owner", "hsr")
        match = self.manager.sessions["hsr"]
        for names, alias in groups:
            for name in names:
                match.questions[0] = by_name[name]
                match.phase = "answering"
                match.attempts.clear()
                self.assertTrue(
                    await self.manager.guess("hsr", "u", "User", alias), name
                )
        for target, alias in [
            ("刃", "SP刃"),
            ("丹恒", "饮月"),
            ("花火", "火花"),
            ("火花", "花火"),
        ]:
            match.questions[0] = by_name[target]
            match.phase = "answering"
            match.attempts.clear()
            self.assertFalse(
                await self.manager.guess("hsr", "u", "User", alias), target
            )
        self.assertEqual(
            game.normalize("银狼ＬＶ．９９９"), game.normalize("银狼LV.999")
        )

    async def test_selected_hsr_combinations_draw_only_selected_pools(self):
        for mode, games, count in [
            ("hsr", {"hsr"}, 93),
            ("lol+hsr", {"lol", "hsr"}, 266),
            ("val+hsr", {"val", "hsr"}, 123),
            ("lol+val+hsr", {"lol", "val", "hsr"}, 296),
        ]:
            with patch.object(
                game.random, "choice", side_effect=lambda pool: pool[-1]
            ) as choice:
                await self.manager.start(mode, "owner", mode)
            self.assertEqual(len(choice.call_args_list[0].args[0]), count)
            self.assertTrue(
                {q["game"] for q in self.manager.sessions[mode].questions} <= games
            )
            opening = self.sent[-1][1]
            self.assertIn("/角色名字", opening)
            self.assertEqual(self.manager.sessions[mode].mode, mode)
            self.assertNotIn("角色池：", opening)
            await self.manager.cancel(mode)


if __name__ == "__main__":
    unittest.main()
