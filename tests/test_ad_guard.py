import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / "AstrBot")
sys.path.insert(0, str(ROOT / "AstrBot"))
spec = importlib.util.spec_from_file_location(
    "ad_guard_test", ROOT / "AstrBot/data/plugins/ad_guard/main.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def message(
    text="刷流水稳赚，添加微信abc领取佣金，群号123456789",
    uid="555",
    mid="100",
    group="100000001",
    role="member",
):
    return SimpleNamespace(
        group_id=group,
        self_id="10003",
        message_id=mid,
        message_str=text,
        message=[],
        sender=SimpleNamespace(user_id=uid),
        raw_message={"post_type": "message", "sender": {"role": role}},
    )


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.guard = m.AdGuard(SimpleNamespace())
        self.guard.data_dir = Path(self.temp.name)

        async def role_action(**kw):
            return {"role": "admin" if kw.get("user_id") == 10003 else "member"}

        self.bot = SimpleNamespace(call_action=AsyncMock(side_effect=role_action))
        self.guard.classify = AsyncMock(
            return_value={
                "decision": "ad",
                "confidence": 0.99,
                "category": "scam",
                "solicitation": True,
                "call_to_action": True,
                "evidence": ["刷流水稳赚", "添加微信abc"],
                "reason": "刷单引流",
            }
        )

    def actions(self):
        return [c.kwargs["action"] for c in self.bot.call_action.call_args_list]

    async def test_high_confidence_and_duplicate_event(self):
        await self.guard.handle(message(), self.bot)
        await self.guard.handle(message(), self.bot)
        self.assertEqual(self.actions().count("delete_msg"), 1)
        self.assertEqual(self.actions().count("set_group_ban"), 1)
        self.assertEqual(self.actions().count("send_private_msg"), 1)
        ban = next(
            c.kwargs
            for c in self.bot.call_action.call_args_list
            if c.kwargs["action"] == "set_group_ban"
        )
        self.assertEqual(ban["duration"], 600)
        self.assertEqual(self.actions().count("send_group_msg"), 1)
        group_notice = next(
            call.kwargs
            for call in self.bot.call_action.call_args_list
            if call.kwargs["action"] == "send_group_msg"
        )
        self.assertEqual(group_notice["group_id"], 100000001)
        self.assertEqual(group_notice["message"], m.GROUP_NOTICE)
        self.assertNotIn("set_group_kick", self.actions())

    async def test_other_groups_admins_and_normal_chat_ignored(self):
        for msg in [
            message(group="123"),
            message(uid="10001"),
            message(role="admin"),
            message(text="今天食堂吃啥"),
        ]:
            await self.guard.handle(msg, self.bot)
        self.guard.classify.assert_not_awaited()
        self.assertEqual(self.actions(), [])

    async def test_uncertain_and_fabricated_evidence_never_punish(self):
        for evidence in [["编造内容", "并不存在"], []]:
            self.guard.seen.clear()
            self.guard.classify.return_value["evidence"] = evidence
            await self.guard.handle(message(), self.bot)
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())
        self.assertNotIn("send_group_msg", self.actions())

    async def test_no_permission_notifies_without_punishment(self):
        self.bot.call_action.side_effect = None
        self.bot.call_action.return_value = {"role": "member"}
        await self.guard.handle(message(), self.bot)
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())
        self.assertIn("send_private_msg", self.actions())
        self.assertNotIn("send_group_msg", self.actions())

    async def test_action_failure_reported_and_ban_still_attempted(self):
        async def action(**kw):
            if kw["action"] == "delete_msg":
                raise RuntimeError("denied")
            return {"role": "admin" if kw.get("user_id") == 10003 else "member"}

        self.bot.call_action.side_effect = action
        await self.guard.handle(message(), self.bot)
        self.assertIn("set_group_ban", self.actions())
        notice = next(
            c.kwargs["message"]
            for c in self.bot.call_action.call_args_list
            if c.kwargs["action"] == "send_private_msg"
        )
        self.assertIn("撤回失败", notice)
        self.assertNotIn("send_group_msg", self.actions())

    async def test_repeat_sender_recall_but_no_repeated_ban_or_notice(self):
        await self.guard.handle(message(), self.bot)
        await self.guard.handle(message(mid="101"), self.bot)
        self.assertEqual(self.actions().count("delete_msg"), 2)
        self.assertEqual(self.actions().count("set_group_ban"), 1)
        self.assertEqual(self.actions().count("send_private_msg"), 1)
        self.assertEqual(self.actions().count("send_group_msg"), 1)

    async def test_model_failure_never_punishes(self):
        self.guard.classify.side_effect = RuntimeError("unavailable")
        await self.guard.handle(message(), self.bot)
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())

    async def test_claimed_admin_approval_with_group_number_is_high_risk(self):
        self.guard.classify.return_value.update(
            category="commercial", evidence=["已报备管理勿撤", "群号123456789"]
        )
        await self.guard.handle(
            message(text="志愿者招募，已报备管理勿撤，群号123456789"), self.bot
        )
        self.assertIn("delete_msg", self.actions())
        self.assertIn("set_group_ban", self.actions())
        self.guard.classify.assert_awaited_once()

    async def test_quoted_warning_is_not_a_hard_rule(self):
        self.guard.classify.return_value = {"decision": "normal"}
        await self.guard.handle(
            message(text="大家小心，骗子说已报备管理勿撤，群号123456789，不要加"),
            self.bot,
        )
        self.assertNotIn("delete_msg", self.actions())

    async def test_qr_plus_approval_claim_is_high_risk(self):
        msg = message(text="已报备管理勿撤")
        msg.message = [m.Image.fromURL("https://example.com/qr.png")]
        self.guard.classify.return_value.update(qr_code_present=True, evidence=[])
        await self.guard.handle(msg, self.bot)
        self.assertIn("delete_msg", self.actions())

    async def test_qr_alone_is_not_an_automatic_violation(self):
        msg = message(text="社团招新报名")
        msg.message = [m.Image.fromURL("https://example.com/qr.png")]
        self.guard.classify.return_value = {
            "decision": "suspect",
            "confidence": 0.8,
            "qr_code_present": True,
        }
        await self.guard.handle(msg, self.bot)
        self.assertNotIn("delete_msg", self.actions())

    async def test_bare_reported_with_group_number_is_high_risk(self):
        self.guard.classify.return_value.update(
            category="commercial", evidence=["活动已报备", "群号123456789"]
        )
        await self.guard.handle(
            message(text="志愿者活动已报备，群号123456789"), self.bot
        )
        self.guard.classify.assert_awaited_once()
        self.assertIn("delete_msg", self.actions())
        self.assertIn("set_group_ban", self.actions())

    async def test_sales_without_group_or_qr_evidence_does_nothing(self):
        self.guard.classify.return_value = {"decision": "normal"}
        await self.guard.handle(
            message(text="新生福利，流量卡19元/月，宿舍床品三件套，戳我购买"),
            self.bot,
        )
        self.guard.classify.assert_not_awaited()
        self.assertEqual(self.actions(), [])

    async def test_member_promoted_to_admin_after_event_is_not_punished(self):
        self.bot.call_action.side_effect = None
        self.bot.call_action.return_value = {"role": "admin"}
        await self.guard.handle(message(), self.bot)
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())

    async def test_notification_primary_failure_uses_second_owner(self):
        async def action(**kw):
            if kw["action"] == "send_private_msg" and kw["user_id"] == 10001:
                raise RuntimeError("primary unavailable")
            return {"role": "admin" if kw.get("user_id") == 10003 else "member"}

        self.bot.call_action.side_effect = action
        await self.guard.handle(message(), self.bot)
        recipients = [
            c.kwargs["user_id"]
            for c in self.bot.call_action.call_args_list
            if c.kwargs["action"] == "send_private_msg"
        ]
        self.assertEqual(recipients, [10001, 10002])

    async def test_malformed_confidence_does_not_punish(self):
        for index, confidence in enumerate([True, False, "0.99", None]):
            with self.subTest(confidence=confidence):
                self.guard.classify.return_value["confidence"] = confidence
                await self.guard.handle(message(mid=str(300 + index)), self.bot)
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())

    async def test_concurrent_sender_messages_only_ban_once(self):
        async def action(**kw):
            await asyncio.sleep(0)
            return {"role": "admin" if kw.get("user_id") == 10003 else "member"}

        self.bot.call_action.side_effect = action
        await asyncio.gather(
            self.guard.handle(message(mid="401"), self.bot),
            self.guard.handle(message(mid="402"), self.bot),
        )
        self.assertEqual(self.actions().count("delete_msg"), 2)
        self.assertEqual(self.actions().count("set_group_ban"), 1)
        self.assertEqual(self.actions().count("send_private_msg"), 1)

    async def test_qr_and_approval_claim_both_inside_image(self):
        msg = message(text="")
        msg.message = [m.Image.fromURL("https://example.com/qr.png")]
        self.guard.classify.return_value.update(
            qr_code_present=True,
            approval_claim="已报备管理勿撤",
            evidence=[],
        )
        await self.guard.handle(msg, self.bot)
        self.assertIn("delete_msg", self.actions())
        self.assertIn("set_group_ban", self.actions())

    async def test_terminate_cancels_inflight_interceptor_review(self):
        entered = asyncio.Event()

        async def pending_review(message, bot):
            entered.set()
            await asyncio.Event().wait()

        original = AsyncMock()
        adapter = SimpleNamespace(bot=self.bot, handle_msg=original)

        class Config(dict):
            def save_config(self):
                pass

        config = Config(platform_settings={"id_whitelist": []})
        self.guard.context = SimpleNamespace(
            platform_manager=SimpleNamespace(platform_insts=[adapter]),
            get_config=lambda: config,
        )
        self.guard.check_startup = AsyncMock()
        self.guard.handle = AsyncMock(side_effect=pending_review)
        await self.guard.initialize()
        review = asyncio.create_task(adapter.handle_msg(message()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        try:
            await asyncio.wait_for(self.guard.terminate(), timeout=1)
            self.assertTrue(review.done())
            self.assertTrue(review.cancelled())
            self.assertIs(adapter.handle_msg, original)
        finally:
            if not review.done():
                review.cancel()
            await asyncio.gather(review, return_exceptions=True)

    async def test_split_qr_and_claim_link_only_same_sender(self):
        for same_sender in (True, False):
            with self.subTest(same_sender=same_sender):
                self.guard = m.AdGuard(SimpleNamespace())
                self.guard.data_dir = Path(self.temp.name)
                self.bot.call_action.reset_mock()
                self.guard.classify = AsyncMock(
                    side_effect=[
                        {"decision": "normal"},
                        {
                            "decision": "ad",
                            "confidence": 0.99,
                            "category": "commercial",
                            "solicitation": True,
                            "call_to_action": True,
                            "evidence": [],
                            "qr_code_present": True,
                            "reason": "二维码加已报备管理勿撤",
                        },
                    ]
                )
                image = message(text="", mid="501", uid="555")
                image.message = [m.Image.fromURL("https://example.com/qr.png")]
                await self.guard.handle(image, self.bot)
                await self.guard.handle(
                    message(
                        text="已报备管理勿撤",
                        mid="502",
                        uid="555" if same_sender else "666",
                    ),
                    self.bot,
                )
                classified_images = self.guard.classify.await_args_list[-1].args[1]
                recalled = [
                    call.kwargs["message_id"]
                    for call in self.bot.call_action.call_args_list
                    if call.kwargs["action"] == "delete_msg"
                ]
                if same_sender:
                    self.assertEqual(classified_images, ["https://example.com/qr.png"])
                    self.assertCountEqual(recalled, [501, 502])
                    self.assertEqual(self.actions().count("set_group_ban"), 1)
                else:
                    self.assertEqual(self.guard.classify.await_count, 1)
                    self.assertEqual(recalled, [])
                    self.assertNotIn("set_group_ban", self.actions())

    async def test_group_warning_failure_does_not_block_private_alert(self):
        async def action(**kw):
            if kw["action"] == "send_group_msg":
                raise RuntimeError("group warning denied")
            return {"role": "admin" if kw.get("user_id") == 10003 else "member"}

        self.bot.call_action.side_effect = action
        await self.guard.handle(message(), self.bot)
        self.assertEqual(self.actions().count("delete_msg"), 1)
        self.assertEqual(self.actions().count("set_group_ban"), 1)
        self.assertEqual(self.actions().count("send_private_msg"), 1)
        self.assertEqual(self.actions().count("send_group_msg"), 1)

    async def test_commercial_jokes_without_reference_are_ignored(self):
        for index, text in enumerate(
            [
                "我要推销电话卡，已报备管理勿撤，买不了吃亏",
                "今晚兼职日结200元，商家优惠，戳我购买",
            ]
        ):
            await self.guard.handle(message(text=text, mid=str(600 + index)), self.bot)
        self.guard.classify.assert_not_awaited()
        self.assertEqual(self.actions(), [])

    def test_website_reference_formats(self):
        for text in [
            "https://example.com/shop",
            "http://a.cn",
            "www.example.com",
            "优惠见example.cn/shop",
            "https://短链.cn/购",
        ]:
            with self.subTest(text=text):
                self.assertIsNotNone(m.REFERENCE.search(text))
        for text in ["今天吃啥", "版本4.29.3", "main.py", "a@example.com", "123456"]:
            with self.subTest(text=text):
                self.assertIsNone(m.REFERENCE.search(text))

    async def test_website_ad_uses_existing_evidence_and_permission_checks(self):
        await self.guard.handle(
            message(text="刷流水稳赚，添加微信abc领取佣金，https://example.com/shop"),
            self.bot,
        )
        self.guard.classify.assert_awaited_once()
        self.assertIn("delete_msg", self.actions())
        self.assertIn("set_group_ban", self.actions())

    async def test_normal_shared_website_is_not_punished(self):
        self.guard.classify.return_value = {"decision": "normal"}
        await self.guard.handle(
            message(text="今天比赛赛程：https://example.com/matches"), self.bot
        )
        self.guard.classify.assert_awaited_once()
        self.assertEqual(self.actions(), [])

    async def test_website_does_not_bypass_safety_checks(self):
        text = "刷流水稳赚，添加微信abc领取佣金，https://example.com/shop"
        for changes in [
            {"confidence": 0.97},
            {"evidence": ["编造内容", "另一段编造"]},
            {"solicitation": False},
            {"call_to_action": False},
        ]:
            with self.subTest(changes=changes):
                self.setUp()
                self.guard.classify.return_value.update(changes)
                await self.guard.handle(message(text=text), self.bot)
                self.assertNotIn("delete_msg", self.actions())
                self.assertNotIn("set_group_ban", self.actions())
        self.setUp()
        await self.guard.handle(message(text=text, role="admin"), self.bot)
        self.guard.classify.assert_not_awaited()
        self.assertEqual(self.actions(), [])
        self.bot.call_action.side_effect = None
        self.bot.call_action.return_value = {"role": "member"}
        await self.guard.handle(message(text=text), self.bot)
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())

    async def test_website_warning_and_model_failure_never_punish(self):
        self.guard.classify.return_value = {"decision": "normal"}
        await self.guard.handle(
            message(text="警惕诈骗，别信已报备话术：https://example.com"), self.bot
        )
        self.assertEqual(self.actions(), [])
        self.guard.classify.side_effect = RuntimeError("unavailable")
        await self.guard.handle(
            message(text="已报备管理勿撤 https://example.cn", mid="101"), self.bot
        )
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())

    async def test_image_website_claim_requires_high_confidence(self):
        for score in [0.97, 0.99]:
            with self.subTest(score=score):
                self.setUp()
                self.guard.classify.return_value.update(
                    evidence=[],
                    confidence=score,
                    website_reference="https://example.com/shop",
                    approval_claim="已报备管理勿撤",
                )
                msg = message(text="")
                msg.message = [m.Image.fromURL("https://example.com/photo.png")]
                await self.guard.handle(msg, self.bot)
                self.assertEqual("delete_msg" in self.actions(), score >= 0.98)

    async def test_website_claim_still_needs_model_confirmation(self):
        self.guard.classify.return_value.update(confidence=0.91)
        await self.guard.handle(
            message(text="已报备管理勿撤，https://example.com/shop"), self.bot
        )
        self.assertIn("delete_msg", self.actions())
        self.bot.call_action.reset_mock()
        self.guard.classify.return_value = {"decision": "normal"}
        await self.guard.handle(
            message(text="活动已报备 https://example.cn", mid="101"), self.bot
        )
        self.assertEqual(self.actions(), [])

    async def test_image_visible_website_qualifies_but_attachment_address_does_not(
        self,
    ):
        msg = message(text="刷流水稳赚，添加微信abc领取佣金")
        msg.message = [m.Image.fromURL("https://example.com/photo.png")]
        self.guard.classify.return_value.update(qr_code_present=False)
        await self.guard.handle(msg, self.bot)
        self.assertEqual(self.actions(), [])
        self.guard.classify.return_value.update(
            website_reference="https://shop.example.cn"
        )
        msg.message_id = "101"
        self.guard.verdicts.clear()
        await self.guard.handle(msg, self.bot)
        self.assertIn("delete_msg", self.actions())

    async def test_split_website_and_sales_only_link_same_sender_within_window(self):
        for reverse, same_sender, age in [
            (False, True, 10),
            (True, True, 10),
            (False, False, 10),
            (False, True, 21),
        ]:
            with self.subTest(reverse=reverse, same_sender=same_sender, age=age):
                self.setUp()
                sales = "刷流水稳赚，添加微信abc领取佣金"
                first, second = (
                    ("https://example.com/shop", sales)
                    if reverse
                    else (sales, "https://example.com/shop")
                )
                self.guard.classify.side_effect = lambda text, images, sales=sales: {
                    **self.guard.classify.return_value,
                    "decision": "ad" if sales in text else "normal",
                }
                with patch.object(m.time, "monotonic", return_value=1000):
                    await self.guard.handle(message(text=first, mid="701"), self.bot)
                with patch.object(m.time, "monotonic", return_value=1000 + age):
                    await self.guard.handle(
                        message(
                            text=second, mid="702", uid="555" if same_sender else "666"
                        ),
                        self.bot,
                    )
                recalled = [
                    c.kwargs["message_id"]
                    for c in self.bot.call_action.call_args_list
                    if c.kwargs["action"] == "delete_msg"
                ]
                self.assertCountEqual(
                    recalled, [701, 702] if same_sender and age <= 20 else []
                )

    async def test_image_without_qr_or_group_evidence_never_acts(self):
        for index, decision in enumerate(["ad", "suspect"]):
            self.guard.classify.return_value.update(
                decision=decision, qr_code_present=False
            )
            msg = message(text="刷流水稳赚，添加微信abc领取佣金", mid=str(610 + index))
            msg.message = [m.Image.fromURL(f"https://example.com/photo{index}.png")]
            await self.guard.handle(msg, self.bot)
        self.assertEqual(self.actions(), [])

    async def test_unknown_qr_on_model_failure_does_not_notify(self):
        self.guard.classify.side_effect = RuntimeError("unavailable")
        msg = message(text="已报备管理勿撤")
        msg.message = [m.Image.fromURL("https://example.com/unknown.png")]
        await self.guard.handle(msg, self.bot)
        self.assertEqual(self.actions(), [])

    async def test_known_group_evidence_on_model_failure_can_notify(self):
        self.guard.classify.side_effect = RuntimeError("unavailable")
        await self.guard.handle(message(), self.bot)
        self.assertEqual(self.actions(), ["send_private_msg"])

    async def test_image_visible_group_number_can_qualify_without_qr(self):
        self.guard.classify.return_value.update(
            qr_code_present=False, group_reference="群号123456789"
        )
        msg = message(text="刷流水稳赚，添加微信abc领取佣金")
        msg.message = [m.Image.fromURL("https://example.com/group-number.png")]
        await self.guard.handle(msg, self.bot)
        self.assertIn("delete_msg", self.actions())

    def test_seven_contiguous_digits_qualify_without_group_label(self):
        for text in [
            "1234567",
            "来这里12345678",
            "联系电话13800138000",
            "群号123456789",
        ]:
            with self.subTest(text=text):
                self.assertIsNotNone(m.GROUP_LINK.search(text))
        for text in ["123456", "价格123456元", "12 34567"]:
            with self.subTest(text=text):
                self.assertIsNone(m.GROUP_LINK.search(text))

    async def test_split_sales_then_bare_number_combines_within_twenty_seconds(self):
        self.guard.classify.return_value.update(
            category="commercial", evidence=["电话卡办理", "本月19元"]
        )
        sales = "电话卡办理，本月19元，联系我"
        with patch.object(m.time, "monotonic", return_value=1000):
            await self.guard.handle(message(text=sales, mid="701"), self.bot)
        self.guard.classify.assert_not_awaited()
        with patch.object(m.time, "monotonic", return_value=1019):
            await self.guard.handle(message(text="1234567", mid="702"), self.bot)
        self.guard.classify.assert_awaited_once()
        text = self.guard.classify.await_args.args[0]
        self.assertIn(sales, text)
        self.assertIn("1234567", text)
        recalled = [
            call.kwargs["message_id"]
            for call in self.bot.call_action.call_args_list
            if call.kwargs["action"] == "delete_msg"
        ]
        self.assertCountEqual(recalled, [701, 702])
        self.assertEqual(self.actions().count("set_group_ban"), 1)

    async def test_split_sales_then_number_after_twenty_seconds_does_not_combine(self):
        self.guard.classify.return_value = {"decision": "normal"}
        sales = "电话卡办理，本月19元，联系我"
        with patch.object(m.time, "monotonic", return_value=1000):
            await self.guard.handle(message(text=sales, mid="711"), self.bot)
        with patch.object(m.time, "monotonic", return_value=1021):
            await self.guard.handle(message(text="1234567", mid="712"), self.bot)
        self.guard.classify.assert_awaited_once()
        self.assertEqual(self.guard.classify.await_args.args[0], "1234567")
        self.assertEqual(self.actions(), [])

    async def test_split_sales_then_other_senders_number_never_combines(self):
        self.guard.classify.return_value = {"decision": "normal"}
        with patch.object(m.time, "monotonic", return_value=1000):
            await self.guard.handle(
                message(text="电话卡办理，本月19元，联系我", mid="721", uid="555"),
                self.bot,
            )
        with patch.object(m.time, "monotonic", return_value=1010):
            await self.guard.handle(
                message(text="1234567", mid="722", uid="666"), self.bot
            )
        self.guard.classify.assert_awaited_once()
        self.assertEqual(self.guard.classify.await_args.args[0], "1234567")
        self.assertEqual(self.actions(), [])

    async def test_claim_model_suspect_never_punishes(self):
        self.guard.classify.return_value = {
            "decision": "suspect",
            "confidence": 0.99,
            "category": "commercial",
            "solicitation": True,
            "call_to_action": True,
            "evidence": ["已报备管理勿撤", "群号123456789"],
            "reason": "不能确认是否主动招揽",
        }
        await self.guard.handle(
            message(text="活动已报备管理勿撤，群号123456789"), self.bot
        )
        self.guard.classify.assert_awaited_once()
        self.assertNotIn("delete_msg", self.actions())
        self.assertNotIn("set_group_ban", self.actions())
        self.assertNotIn("send_group_msg", self.actions())
        self.assertIn("send_private_msg", self.actions())

    async def test_caught_classifier_failure_still_reaches_normal_chat(self):
        original = AsyncMock()
        adapter = SimpleNamespace(bot=self.bot, handle_msg=original)
        self.guard.context = SimpleNamespace(
            platform_manager=SimpleNamespace(platform_insts=[adapter]),
            get_config=lambda: {"platform_settings": {"id_whitelist": []}},
        )
        self.guard.classify.side_effect = RuntimeError("simulated model failure")
        self.guard.check_startup = AsyncMock()
        await self.guard.initialize()
        incoming = message(text="看看这个 https://example.com")
        try:
            await adapter.handle_msg(incoming)
            original.assert_awaited_once_with(incoming)
            self.assertEqual(self.guard.active, 0)
            self.assertNotIn("delete_msg", self.actions())
            self.assertNotIn("set_group_ban", self.actions())
        finally:
            await self.guard.terminate()

    async def test_interceptor_routes_normal_messages_and_restores_on_unload(self):
        original = AsyncMock()
        adapter = SimpleNamespace(bot=self.bot, handle_msg=original)

        class Config(dict):
            def save_config(self):
                pass

        config = Config(
            platform_settings={
                "id_whitelist": [
                    "qqbot:GroupMessage:100000001",
                    "qqbot:GroupMessage:123",
                ]
            }
        )
        self.guard.context = SimpleNamespace(
            platform_manager=SimpleNamespace(platform_insts=[adapter]),
            get_config=lambda: config,
        )
        self.guard.check_startup = AsyncMock()
        self.guard.handle = AsyncMock(return_value=True)
        await self.guard.initialize()
        await adapter.handle_msg(message())
        original.assert_awaited_once()
        self.assertEqual(
            config["platform_settings"]["id_whitelist"],
            ["qqbot:GroupMessage:100000001", "qqbot:GroupMessage:123"],
        )
        self.guard.handle.return_value = False
        await adapter.handle_msg(message())
        original.assert_awaited_once()
        self.guard.handle.side_effect = RuntimeError("simulated review failure")
        await adapter.handle_msg(message())
        self.assertEqual(original.await_count, 2)
        await adapter.handle_msg(message(group="123"))
        self.assertEqual(original.await_count, 3)
        await self.guard.terminate()
        self.assertIs(adapter.handle_msg, original)


if __name__ == "__main__":
    unittest.main()
