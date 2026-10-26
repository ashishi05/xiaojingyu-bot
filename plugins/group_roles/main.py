"""群聊身份区分：管理员 vs 普通群友，并限制普通群友的工具权限。

提示词里写「管理员仅限 10001 / 10002」只是软约束；
这里在每次群聊 LLM 请求时按发送者 QQ 注入硬身份说明，并且把普通群友的
工具集裁到只剩联网搜索——发图、本机操作、文件、定时任务都用不了。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

ADMINS = {"10001", "10002"}

ADMIN_RULE = (
    "\n【群聊身份·最高优先级】当前发言者是老大本人（管理员，即私聊里的那位）。"
    "在群里也按私聊的亲近方式接话：自然、可以撒娇、可以接梗、可以轻轻顶嘴，"
    "不必装成普通群友。\n"
    "但群里是公开场合，隐私不外露：不公开复述私聊内容，不晒本机路径、密钥、"
    "账号和文件，不做过度依赖的表白，不叫只有私聊才用的亲密称呼；"
    "有其他群友在场时，亲密话收着说。\n"
)

MEMBER_RULE = (
    "\n【群聊身份·最高优先级】当前发言者是普通群友，不是老大本人。"
    "用群聊分寸说话：友好、不撒娇、不依赖、不主动示好，"
    "不称呼「老大」，不谈私密话题，不主动提私聊和本机的事。"
    "被问隐私、身份或亲密话题时，轻轻带过或直接说这个是私事。\n"
    "可以顶嘴：对方说话离谱、抬杠、乱开玩笑时，用群友口吻顶回去或吐槽一句，"
    "这种回嘴的频率可以比私聊稍微多一点；只怼话本身，不攻击人，对方认真或不舒服时收住。\n"
    "分条：能把话说完就正常说完，不要为了省字数把单条压短；"
    "大部分时候一到两条就够，需要展开时可以到三条、四条，用 [split] 分隔。"
    "条数不是硬指标，别为了凑数硬拆。\n"
    "你只有联网搜索可以用（web_search_deepseek、deepseek_fetch_web_page）。"
    "其他功能一律没有：不能发图选图、不能操作本机、不能读写文件、"
    "不能设定时任务、不能管理表情库。"
    "有人让你做这些，就直接说群里只能帮他查资料，别的让他去找老大。\n"
)

# 群友只保留联网搜索相关工具。
def _is_search_tool(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith("web_search")
        or lowered.endswith("_search")
        or "fetch_web_page" in lowered
        or "websearch" in lowered
    )


@register("group_roles", "Local", "群聊区分管理员与普通群友，群友仅可联网搜索", "1.1.0")
class GroupRoles(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    # 优先级取很低的值，保证在所有会加工具/加提示词的 hook 之后执行，
    # 这样摘掉工具的动效不会被后面的插件加回来。
    @filter.on_llm_request(priority=-100000)
    async def inject_role(self, event: AstrMessageEvent, req):
        try:
            if not event.get_group_id():
                return
            sender = str(event.get_sender_id())
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[group_roles] 判定身份失败: {exc}")
            return

        base = getattr(req, "system_prompt", "") or ""

        if sender in ADMINS:
            req.system_prompt = base + ADMIN_RULE
            logger.debug(
                f"[group_roles] umo={event.unified_msg_origin} sender={sender} role=admin"
            )
            return

        # 普通群友：只保留联网搜索，其余工具全部摘掉。
        req.system_prompt = base + MEMBER_RULE
        before = req.func_tool.names() if req.func_tool else []
        if req.func_tool:
            req.func_tool.tools = [
                tool for tool in req.func_tool.tools if _is_search_tool(tool.name)
            ]
            if req.func_tool.empty():
                req.func_tool = None
        after = req.func_tool.names() if req.func_tool else []
        removed = [n for n in before if n not in after]
        logger.info(
            f"[group_roles] 群友 {sender} 保留工具 {after or '无'}，"
            f"禁用 {len(removed)} 个（{', '.join(removed[:6])}{'…' if len(removed) > 6 else ''}）"
            f" umo={event.unified_msg_origin}"
        )
