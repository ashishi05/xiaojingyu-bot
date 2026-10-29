import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

# 表情标记由 meme_tag 插件消费，分条时不能把它当成独立一条。
_TAG_RE = re.compile(r"\[\[tag:[^\]]*\]\]")

# 句末标点后切分；保留标点本身。
_SENT_RE = re.compile(r"(?<=[。？！~…!?])")

# 群聊一条消息最多拆成几条。
_MAX_AUTO_PARTS = 3

# 群聊外发条数上限：只做兜底防刷屏，具体条数交给提示词把握。
_GROUP_CAP = 4

# 私聊单条超过这么多字，才按句子自动拆开
_PRIVATE_SPLIT_MIN = 30

# 判断句子里有没有中文/日文假名，用来区分“正常句子”和“颜文字前缀”。
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")


def _merge_evenly(parts: list[str], limit: int) -> list[str]:
    """把若干条按条数上限均匀合并，避免最后一条变成一大段。"""
    if limit <= 0 or len(parts) <= limit:
        return parts
    n = len(parts)
    base, rem = divmod(n, limit)
    out: list[str] = []
    i = 0
    for k in range(limit):
        size = base + (1 if k < rem else 0)
        chunk = parts[i : i + size]
        # Preserve multiline sections when the message budget merges bubbles.
        separator = '\n\n' if any('\n' in part for part in chunk) else ''
        out.append(separator.join(chunk))
        i += size
    return out


def _split_sentences(text: str, max_parts: int = _MAX_AUTO_PARTS) -> list[str]:
    """把一整段话按句子切成若干条，最多 max_parts 条。没句末标点时按逗号兜底切。"""
    sents = [s.strip() for s in _SENT_RE.split(text) if s.strip()]
    if len(sents) <= 1:
        # 没有句末标点（全逗号长句）时，按逗号切，再均匀合并
        rough = [s.strip() for s in re.split(r"[，,]", text) if s.strip()]
        if len(rough) <= 1:
            return [text]
        return _merge_evenly(rough, max_parts)

    out: list[str] = [sents[0]]
    for sent in sents[1:]:
        # 句首若是颜文字/符号（如 "(｡･ω･｡) 我在这儿"），把这个前缀并回上一条，
        # 免得把颜文字从中间劈开。
        m = re.match(r"^(\S+)\s+(.*)$", sent, re.S)
        if m and len(m.group(1)) <= 12 and not _CJK_RE.search(m.group(1)):
            out[-1] = out[-1] + m.group(1)
            sent = m.group(2).strip()
            if not sent:
                continue
        out.append(sent)

    if len(out) <= 1:
        return [text]
    return _merge_evenly(out, max_parts)


def prepare_reply(event):
    result = event.get_result()
    if event.get_platform_name() not in {'aiocqhttp', 'webchat', 'qq_official', 'qq_official_webhook'} or not result or not result.is_model_result():
        return
    text = '[split]'.join(c.text for c in result.chain if isinstance(c, Plain))

    # 删掉引用回复（Reply）：不管配置/插件哪来的，发送前统一收拾掉
    try:
        from astrbot.api.message_components import Reply as _Reply
        before = len(result.chain)
        result.chain = [c for c in result.chain if not isinstance(c, _Reply)]
        if len(result.chain) != before:
            logger.info("[chat_delivery] 已移除引用组件")
    except Exception:
        pass

    # 先把表情标记摘出来，最后再挂回最后一条，避免它单独成为一条空气泡。
    tags = _TAG_RE.findall(text)
    text = _TAG_RE.sub('', text).strip()

    # 分条规则：[split] 标记，或者空行（两个以上换行）都算分条
    parts = [
        p.strip()
        for p in re.split(r'\[split\]|\n\s*\n', text)
        if p.strip()
    ]

    # 模型没写 [split] 又给了一整段时，按句子补分条：
    # Short single replies stay together in both private and group chats.
    if parts and len(parts) == 1:
        if len(parts[0]) > _PRIVATE_SPLIT_MIN:
            parts = _split_sentences(parts[0])

    if tags:
        marker = '\n'.join(tags)
        if parts:
            parts[-1] = parts[-1] + '\n' + marker
        else:
            parts = [marker]

    if not parts:
        return
    others = [c for c in result.chain if not isinstance(c, Plain)]
    if event.get_platform_name() in {'qq_official', 'qq_official_webhook'}:
        pending = (event.get_extra('meme_manager_pending_images') or []) if event.get_group_id() else []
        limit = max(1, _GROUP_CAP - len(pending) - len(others))
        while len(parts) > limit:
            i = min(range(len(parts) - 1), key=lambda j: (
                '\n' in parts[j] and '\n' in parts[j + 1],
                len(parts[j]) + len(parts[j + 1]), j,
            ))
            separator = '\n\n' if '\n' in parts[i] or '\n' in parts[i + 1] else ''
            parts[i:i + 2] = [parts[i] + separator + parts[i + 1]]
    elif event.get_group_id():
        pending = event.get_extra('meme_manager_pending_images') or []
        limit = max(1, _GROUP_CAP - len(pending) - len(others))
        parts = _merge_evenly(parts, limit)
    result.chain = [Plain(part) for part in parts] + others


@register('chat_delivery', 'Local', '自然分条与群聊消息上限', '1.2.1')
class ChatDelivery(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_decorating_result(priority=-10000)
    async def shape_reply(self, event: AstrMessageEvent):
        prepare_reply(event)
