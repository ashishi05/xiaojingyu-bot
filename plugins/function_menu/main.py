import asyncio
import json
import os
import re
import tempfile

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register
from data.plugins.emoji_guess.game import (
    GUESS_GAMES,
    LAST_GAMES,
    occupied_game,
    send_guess_menu,
)
from data.plugins.emoji_guess.main import native_scope, slash_text
from data.plugins.owner_session.identity import trusted_owner

MENU = """小鲸鱼 · 功能菜单

【被动技能】
• 聊天（可联网搜索、可简单识别图片）
• 查询比赛赛程赛果
• 表情包使用与保存
• 主机管理（文档/表格处理、远程文件检索、脚本编写/执行）
• 群聊接话、图片理解和广告管理（按群设置）

【主动技能】
• /天使模式：开启温柔夸夸
• /关闭天使模式：关闭（也可说“别夸了”）
• /猜：猜猜杯菜单，可选择角色、国家、游戏、知名人物、网络人物、成语和假冷知识
• /名单：查看设置名单"""



# shortcut: static menu for this deployment; update when available features change.


TRIGGER = re.compile(


    r"/?(?:功能菜单|菜单|你有什么功能|你有哪些功能|(?:发|发个|发一下|给我发|给我发个|给我发一下|看看|查看|打开)(?:功能菜单|菜单))[？?！!。~～]*"


)








def display_session(value):


    """Render a native session ID as a conversation label.





    Args:


        value: Configured session identifier or bare group number.





    Returns:


        Human-readable conversation label.


    """


    text = str(value)


    parts = text.rsplit(":", 2)


    if len(parts) == 3 and parts[1] in {"FriendMessage", "GroupMessage"}:


        return ("私聊：" if parts[1] == "FriendMessage" else "群聊：") + parts[2]


    return text








@register("function_menu", "Local", "私聊功能菜单、设置名单与用法", "1.1.0")


class FunctionMenu(Star):


    def __init__(self, context: Context):


        super().__init__(context)


        self.angel_path = StarTools.get_data_dir("function_menu") / "angel_mode.json"


        self.angel_scopes = set()


        if self.angel_path.exists():


            data = json.loads(self.angel_path.read_text(encoding="utf-8"))


            if not isinstance(data, list) or any(not isinstance(x, str) for x in data):


                raise ValueError("Invalid angel mode state")


            self.angel_scopes = set(data)





    def save_angel(self, scopes):


        self.angel_path.parent.mkdir(parents=True, exist_ok=True)


        temp = None


        try:


            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.angel_path.parent, delete=False) as stream:


                temp = stream.name


                json.dump(sorted(scopes), stream, ensure_ascii=False)


            os.replace(temp, self.angel_path)


            self.angel_scopes = scopes


        finally:


            if temp and os.path.exists(temp):


                os.unlink(temp)





    @filter.command("天使模式", alias={"夸夸模式"}, priority=200011)


    async def angel_on(self, event: AstrMessageEvent, action: str = ""):


        if slash_text(event) in {"天使模式 关闭", "夸夸模式 关闭"}:
            await self.angel_off(event)
            return
        if slash_text(event) not in {"天使模式", "夸夸模式"}:


            return


        event.stop_event()


        scope = native_scope(event)


        if scope in self.angel_scopes:


            await event.send(event.plain_result("天使模式已经开着啦"))


            return


        try:


            self.save_angel(self.angel_scopes | {scope})


        except OSError:


            await event.send(event.plain_result("天使模式保存失败，请稍后再试"))


            return


        await event.send(event.plain_result("天使模式开启啦，今天想听什么样的夸夸？"))





    @filter.command("关闭天使模式", alias={"关闭夸夸模式"}, priority=200011)


    async def angel_off(self, event: AstrMessageEvent):


        if slash_text(event) not in {"关闭天使模式", "关闭夸夸模式", "天使模式 关闭", "夸夸模式 关闭"}:


            return


        event.stop_event()


        scope = native_scope(event)


        if scope not in self.angel_scopes:


            await event.send(event.plain_result("天使模式现在没有开启"))


            return


        try:


            self.save_angel(self.angel_scopes - {scope})


        except OSError:


            await event.send(event.plain_result("天使模式保存失败，请稍后再试"))


            return


        await event.send(event.plain_result("天使模式已关闭，本鱼恢复平常的样子啦"))





    @filter.on_waiting_llm_request(priority=101)


    async def angel_stop_text(self, event: AstrMessageEvent):


        if event.get_platform_name() not in {"aiocqhttp", "qq_official", "qq_official_webhook"} or (event.message_str or "").strip().strip("。！？!? ") != "别夸了":


            return


        scope = native_scope(event)


        if scope not in self.angel_scopes:


            return


        event.stop_event()


        try:


            self.save_angel(self.angel_scopes - {scope})


        except OSError:


            await event.send(event.plain_result("天使模式保存失败，请稍后再试"))


            return


        await event.send(event.plain_result("好，不夸啦，天使模式已关闭"))





    @filter.on_llm_request(priority=-80)


    async def angel_prompt(self, event: AstrMessageEvent, req):


        if event.get_platform_name() in {"aiocqhttp", "qq_official", "qq_official_webhook"} and native_scope(event) in self.angel_scopes:


            req.system_prompt = (getattr(req, "system_prompt", "") or "") + (


                "\n\n【天使模式】说话温柔自然，先回应对方实际说的事；有值得肯定的具体细节时，"


                "当用户分享努力、进展、作品或主动求夸时，直接用温柔、有分量的语言明确夸奖具体行动或选择，让人能听出来是夸奖，并自然流露为对方高兴；日常小事也可以偏心地夸一夸，主动求夸时可以稍微大胆、直球和俏皮；普通信息查询仍先回答问题。比如对方整理了积压的笔记，可以说“把那堆积压的笔记整理出来了，这份耐心真的很值得夸呀”；只完成一部分可以说“这一部分是你实实在在整理出来的，你愿意动手这点很棒”。示例只供参考，要按事实换说法。"


                "普通提问直接回答，闲聊可以顺着聊；对方失落时先接住情绪，措辞温和，"


                "不要用‘弄错就弄错呗’等显得不在乎的话，也不替对方安排休息。"


                "避免空洞套话和捏造事实，例如不要说‘肯开始就已经赢一半’；"


                "允许偶尔夸得略夸张、偏心一些，但不捏造事实或把严重错误说成正确，也不要每句重复同样的夸奖。"


                "天使模式单句话鼓励在30字以内，不是硬限制；内容需要时自然说完整，比赛、游戏和其他专门格式优先；"


                "沿用原本的句数和分条习惯，不为变长额外增加句子或消息，也不重复凑字数。"


                "分享时先欣赏，需要建议再给具体建议。保持小鲸鱼本来的性格和现有权限，"


                "不默认恋爱关系、不索取关注；医疗、金钱、账号安全等问题仍要清楚真实地提醒风险。"


            )





    @filter.command("名单", alias={"名单输出", "查看名单"}, priority=1000)


    async def show_lists(self, event: AstrMessageEvent):


        """Read explicit account and session lists for trusted private users.





        Args:


            event: Native QQ command requesting the current lists.


        """


        if event.get_platform_name() not in {"aiocqhttp", "qq_official", "qq_official_webhook"}:


            return


        event.stop_event()


        if trusted_owner(event) not in {"10001", "10002"}:


            await event.send(event.plain_result("名单仅限机器人管理账号查看"))


            return


        if event.get_group_id():


            await event.send(


                event.plain_result("请私聊发送 /名单 查看，避免把账号设置发到群里")


            )


            return





        config = self.context.get_config(umo=event.unified_msg_origin)


        sections = ["小鲸鱼 · 设置名单"]
        if event.get_platform_name() in {"qq_official", "qq_official_webhook"}:
            sections.append("【官方 QQ 兼容】\n此私聊已关联原 QQ 管理账号，聊天记忆共用；游戏和每日赛程仍按窗口独立设置。\n官方群管理员可在群内使用 /广告管理 开启、关闭或状态，以及 /广告白名单 添加，按编号选择成员 管理本群名单。")


        admins = "、".join(str(uid) for uid in config.get("admins_id", [])) or "暂无"


        sections.append("【机器人管理员】\n" + admins)


        permissions = {}


        for name, label, attribute in (


            ("group_roles", "群聊高级权限", "ADMINS"),


            ("meme_admin", "表情管理", "_ALLOWED"),


            ("msg_recall", "消息撤回", "_ALLOWED"),





            ("sleep_mode", "休眠控制", "ADMINS"),


            ("group_autojoin", "群库同步", "ADMINS"),


            ("group_bot_note", "机器人标记管理", "ADMINS"),


            ("ad_guard", "广告管理账号", "OWNERS"),


        ):


            metadata = self.context.get_registered_star(name)


            if metadata and metadata.activated and metadata.star_cls:


                accounts = tuple(


                    sorted(str(uid) for uid in getattr(metadata.module, attribute, ()))


                )


                permissions.setdefault(accounts, []).append(label)


        if permissions:


            sections.append(


                "【各功能管理账号】\n"


                + "\n".join(


                    "、".join(labels) + "：" + ("、".join(accounts) or "暂无")


                    for accounts, labels in permissions.items()


                )


            )





        settings = config.get("platform_settings", {})


        enabled = "已启用" if settings.get("enable_id_white_list") else "未启用"


        sessions = [


            display_session(value) for value in settings.get("id_whitelist", [])


        ]


        sections.append(


            f"【聊天放行名单 · {enabled}】\n"


            + ("\n".join(sessions) or "暂无；空名单不限制会话")


        )


        reply = config.get("provider_ltm_settings", {}).get("active_reply", {})


        enabled = "已启用" if reply.get("enable") else "未启用"


        sections.append(


            f"【主动回复白名单 · {enabled}】\n"


            + (


                "\n".join(


                    display_session(value) for value in reply.get("whitelist", [])


                )


                or "暂无"


            )


        )





        guard_meta = self.context.get_registered_star("ad_guard")
        if guard_meta and guard_meta.activated and guard_meta.star_cls:
            guard = guard_meta.star_cls
            cfg = self.context.get_config().get("platform_settings", {})
            wl = cfg.get("id_whitelist", [])
            groups = {str(x).rsplit(":", 1)[-1] for x in wl if str(x).startswith("qqbot:GroupMessage:")}
            groups |= set(guard.group_settings) | {guard.group}
            rows = []
            for gid in sorted(groups):
                opts = guard.group_settings.get(gid, {})
                chat = opts.get("chat", gid in wl or any(str(x).endswith(":GroupMessage:" + gid) for x in wl))
                ads = opts.get("ads", gid == guard.group)
                rows.append(f"{'官方群 '+gid[9:] if gid.startswith('official-') else '群 '+gid}：闲聊{'开' if (any(str(x).endswith(':GroupMessage:'+gid[9:]) for x in wl) if gid.startswith('official-') else chat) else '关'}｜广告管理{'开' if ads else '关'}")
            sections.append("【按群功能设置】\n" + "\n".join(rows) + "\n管理员私聊：/群设置 群号 聊天或广告 开启或关闭；官方群内：/广告管理 开启或关闭")

        metadata = self.context.get_registered_star("ad_guard")


        if metadata and metadata.activated and metadata.star_cls:


            group = str(metadata.module.GROUP)


            accounts = (


                "、".join(sorted(metadata.star_cls.whitelist, key=int))


                or "暂无手动添加账号"


            )


            sections.append(


                f"【广告白名单 · 群 {group}】\n{accounts}\n群主、群管理员和广告管理账号自动豁免。"


            )


            try:
                from data.plugins.group_autojoin.main import _find_bot
                bot = event.bot if event.get_platform_name() == "aiocqhttp" else _find_bot(self.context)
                if bot is None:
                    raise RuntimeError("Original QQ adapter is unavailable")
                members = await asyncio.wait_for(
                    bot.call_action(


                        action="get_group_member_list", group_id=int(group)


                    ),


                    10,


                )


                if not isinstance(members, list):


                    raise ValueError("Unexpected group member list")


                managers = []


                for member in members:


                    if member.get("role") in {"owner", "admin"}:


                        label = "群主" if member["role"] == "owner" else "管理员"


                        name = " ".join(


                            str(


                                member.get("card") or member.get("nickname") or ""


                            ).split()


                        )[:32]


                        managers.append(f"{label}：{name}（{member['user_id']}）")


                sections.append(


                    "【广告群自动豁免成员】\n"


                    + ("\n".join(managers) or "接口未返回群主和管理员，名单未确认")


                )


            except Exception:


                sections.append(


                    "【广告群自动豁免成员】\n群成员读取失败，暂时无法列出；自动豁免规则仍保留。"


                )


        else:


            sections.append("【广告白名单】\n广告管理未启用")





        for name, label in (


            ("group_bot_note", "已标记的机器人账号"),


            ("sleep_mode", "休眠会话"),


        ):


            metadata = self.context.get_registered_star(name)


            if not metadata or not metadata.activated or not metadata.star_cls:


                sections.append(f"【{label}】\n对应功能未启用")


                continue


            instance = metadata.star_cls


            values = (


                instance._bots


                if name == "group_bot_note"


                else [scope for scope, asleep in instance._state.items() if asleep]


            )


            sections.append(


                f"【{label}】\n"


                + (


                    "\n".join(sorted(display_session(value) for value in values))


                    or "暂无"


                )


            )


        sections.append("广告名单增删：/广告白名单 添加 QQ号／删除 QQ号")


        output = "\n\n".join(sections)


        for offset in range(0, len(output), 3000):


            await event.send(event.plain_result(output[offset : offset + 3000]))





    @filter.command("猜菜单", alias={"猜猜猜", "猜", "换个猜"}, priority=200010)


    async def guess_menu(self, event: AstrMessageEvent):


        """List enabled Emoji games, including during an active match.





        Args:


            event: Native QQ command event.


        """


        if slash_text(event) is not None:


            await send_guess_menu(self.context, event)





    @filter.command("继续", priority=200009)


    async def continue_game(self, event: AstrMessageEvent):


        """Start another match of the last finished game with a slash command.





        Args:


            event: Native QQ slash command.


        """


        if slash_text(event) != "继续":


            return


        scope = native_scope(event)


        active = occupied_game(self.context, scope, "")


        previous = LAST_GAMES.get(scope)


        event.stop_event()


        for name, _ in GUESS_GAMES:


            event.set_extra(name + "_gameplay", True)


        if active:


            await event.send(event.plain_result("本轮尚未结束；/结束 会结算整场并清零"))


            return


        if previous is None:


            await send_guess_menu(self.context, event)


            return


        manager, mode = previous


        try:


            await manager.start(scope, str(event.get_sender_id()), mode)


        except (ValueError, RuntimeError) as exc:


            await event.send(event.plain_result(str(exc)))





    @filter.command("结束", priority=200008)


    async def end_game(self, event: AstrMessageEvent):


        """Consume game endings before sleep or ordinary chat handling.





        Args:


            event: Native QQ slash command.


        """


        if slash_text(event) != "结束":


            return


        scope = native_scope(event)


        event.stop_event()


        for name, _ in GUESS_GAMES:


            event.set_extra(name + "_gameplay", True)


        for name, _ in GUESS_GAMES:


            metadata = self.context.get_registered_star(name)


            instance = metadata.star_cls if metadata and metadata.activated else None


            if instance and (


                scope in instance.manager.sessions


                or scope in getattr(instance, "pending", {})


            ):


                await instance.game_command(event, "结束")


                return


        raw = event.message_obj.raw_message


        role = raw.get("sender", {}).get("role") if isinstance(raw, dict) else None


        admin = event.is_admin() or role in ("admin", "owner")


        for name, _ in GUESS_GAMES:


            metadata = self.context.get_registered_star(name)


            if metadata and metadata.activated:


                try:


                    if await metadata.star_cls.manager.stop(


                        scope, str(event.get_sender_id()), admin


                    ):


                        return


                except PermissionError as exc:


                    await event.send(event.plain_result(str(exc)))


                    return


        await event.send(event.plain_result("当前没有进行中的猜猜杯"))


        await send_guess_menu(self.context, event)





    @filter.command("积分", priority=200007)


    async def cup_score(self, event: AstrMessageEvent):


        """Show the same cup total during play and between rounds.





        Args:


            event: Native QQ slash command.


        """


        if slash_text(event) != "积分":


            return


        event.stop_event()


        for name, _ in GUESS_GAMES:


            event.set_extra(name + "_gameplay", True)


        for name, _ in GUESS_GAMES:


            metadata = self.context.get_registered_star(name)


            if metadata and metadata.activated:


                await event.send(


                    event.plain_result(


                        metadata.star_cls.manager.leaderboard(native_scope(event))


                    )


                )


                return





    @filter.on_waiting_llm_request(priority=100)


    async def show_menu(self, event: AstrMessageEvent):


        if (


            event.get_platform_name() not in {"aiocqhttp", "qq_official", "qq_official_webhook"}


            or event.get_group_id()


            or trusted_owner(event) not in {"10001", "10002"}


            or not TRIGGER.fullmatch((event.message_str or "").strip())


        ):


            return


        await event.send(event.plain_result(MENU))


        event.stop_event()
