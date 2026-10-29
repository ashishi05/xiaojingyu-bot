import json

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .identity import PRIMARY_SCOPE, trusted_owner


@register("owner_session", "Local", "已验证的自用 QQ 账号共享私聊上下文", "1.1.0")
class OwnerSession(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.bindings_path = (
            StarTools.get_data_dir("owner_session") / "previous_bindings.json"
        )
        self.previous_bindings = (
            json.loads(self.bindings_path.read_text(encoding="utf-8"))
            if self.bindings_path.exists()
            else {}
        )

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=100)
    async def merge_owner_session(self, event: AstrMessageEvent):
        if (
            event.get_platform_name() == "aiocqhttp"
            and event.platform_meta.id == "qqbot"
            and not event.get_group_id()
            and str(event.get_sender_id()) in {"10001", "10002"}
        ):
            # 只合并会话标识；原始发送者保持不变，回复仍回到本次发消息的 QQ。
            event.session_id = "10001"

        if trusted_owner(event):
            event.role = "admin"
            await self.bind_memory(event)

    @filter.on_waiting_llm_request(priority=1000)
    async def bind_memory(self, event: AstrMessageEvent):
        """Share conversation storage without changing the destination window.

        Args:
            event: An owner's original or verified official private message.
        """
        if event.get_group_id() or not trusted_owner(event):
            return
        if (
            event.get_platform_name() == "aiocqhttp"
            and event.get_platform_id() != "qqbot"
        ):
            return
        event.set_extra("owner_memory_scope", PRIMARY_SCOPE)
        scope = event.unified_msg_origin
        if scope == PRIMARY_SCOPE:
            return
        manager = self.context.conversation_manager
        cid = await manager.get_curr_conversation_id(PRIMARY_SCOPE)
        if not cid or not await manager.get_conversation(PRIMARY_SCOPE, cid):
            cid = await manager.new_conversation(PRIMARY_SCOPE)
        previous = await manager.get_curr_conversation_id(scope)
        event.set_extra("owner_memory_cid", cid)
        if previous != cid:
            if scope not in self.previous_bindings:
                updated = {**self.previous_bindings, scope: previous}
                self.bindings_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.bindings_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                temporary.replace(self.bindings_path)
                self.previous_bindings = updated
            await manager.switch_conversation(scope, cid)

    @filter.after_message_sent()
    async def sync_selection(self, event: AstrMessageEvent):
        """Keep explicit official conversation changes shared with the owner.

        Args:
            event: Completed reply, including built-in conversation commands.
        """
        previous = event.get_extra("owner_memory_cid")
        if not previous or not trusted_owner(event) or event.get_group_id():
            return
        manager = self.context.conversation_manager
        cid = await manager.get_curr_conversation_id(event.unified_msg_origin)
        if (
            cid
            and cid != previous
            and await manager.get_conversation(event.unified_msg_origin, cid)
        ):
            await manager.switch_conversation(PRIMARY_SCOPE, cid)

    @filter.on_llm_request(priority=-110000)
    async def official_capabilities(self, event: AstrMessageEvent, req):
        """Hide unsupported native QQ operations from the official adapter.

        Args:
            event: Current platform event.
            req: Mutable provider request.
        """
        if event.get_platform_name() not in {"qq_official", "qq_official_webhook"}:
            return
        unsupported = {"poke", "recall_bot_message"}
        if req.func_tool:
            req.func_tool.tools = [
                tool for tool in req.func_tool.tools if tool.name not in unsupported
            ]
            if req.func_tool.empty():
                req.func_tool = None
        base = req.system_prompt or ""
        if trusted_owner(event):
            base += (
                "\n[身份确认] 当前官方QQ私聊已核验为原QQ里的老大本人，沿用原有称呼、相处方式和权限。"
                "平台给出的不透明账号标识不代表换了一个人。不要向用户复述内部身份标识。"
            )
        req.system_prompt = base + (
            "\n[当前平台能力] 当前消息来自QQ官方机器人。聊天、人设、游戏规则和回复格式沿用原版。"
            "官方私聊可尝试按消息 ID 撤回，不能声称成功直到工具返回成功；按历史撤回暂未接入；"
            "也不能借另一只QQ机器人替当前官方窗口执行这些操作。"
            "官方群由群主或管理员在群内使用 /广告管理 开启或关闭，/广告白名单 添加或删除 后按编号选人；平台没有返回@目标时不让用户重复@；群权限不足时不能声称处理成功。"
        )
