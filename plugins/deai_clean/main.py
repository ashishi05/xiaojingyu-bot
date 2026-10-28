"""去 AI 味硬后处理：把模型爱甩的空壳套话从回复里删掉。

思路来自 jiangchuangege/xiaojiao-harnees 的人格层（docs/modules/09-persona.md）：
提示词是软约束，模型该带客套还会带，所以在发送前用精确短语表做一次硬删除。
只删空壳，不动内容；删完如果句子变残缺，顺一下标点。
"""

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

# 精确短语：出现即删（含前后常见标点）
_PHRASES = [
    "希望对你有帮助",
    "希望对您有帮助",
    "希望这个回答对你有帮助",
    "希望这个回答能帮到你",
    "还有什么可以帮你",
    "还有什么需要帮助的吗",
    "还有什么我可以帮你",
    "如果还有其他问题，请随时提问",
    "如果还有其他问题",
    "有问题随时问我",
    "随时找我",
    "随时告诉我",
    "作为一个AI",
    "作为一个 AI",
    "作为AI",
    "作为语言模型",
    "我是一个AI助手",
    "作为一个语言模型",
    "我理解你的感受",
    "我明白你的感受",
    "这是个好问题",
    "这是一个好问题",
    "很好的问题",
    "综上所述",
    "总而言之",
    "总的来说",
    "值得注意的是",
    "需要注意的是",
    "首先，",
    "其次，",
    "最后，",
    "第一，",
    "第二，",
    "第三，",
]

# 行级删除：整行只有这些客套时删掉整行
_LINE_ONLY = re.compile(
    r"^\s*(希望(以上|这个回答|这些)?(内容)?(对你|对您)?(有|能)(所)?帮助.*|"
    r"(还有|如果)(什么|有其他)?(问题|需要|疑问).{0,10}(随时|尽管|可以).{0,10}(问|找|告诉).{0,6}|"
    r"祝(你|您).{0,12}(愉快|顺利|开心|好心情).{0,4})\s*[。！~～]?\s*$"
)

# 删完可能留下多余标点
_TIDY = [
    (re.compile(r"^\s*[，,。、；;：:]\s*"), ""),
    (re.compile(r"[，,]{2,}"), "，"),
    # 删掉空壳句后留下的「，。」「，！」之类
    (re.compile(r"[，,]\s*([。！？])"), r"\1"),
    (re.compile(r"([。！？])\s*[，,]+"), r"\1"),
    (re.compile(r"([。！？])\1+"), r"\1"),
]


def clean_text(text: str) -> str:
    if not text:
        return text
    # Preserve code and quoted source text instead of applying stylistic deletions.
    if any(marker in text for marker in ("`", '"', "'", "“", "”", "‘", "’")):
        return text
    original = text
    lines = text.split("\n")
    kept = []
    for line in lines:
        stripped = line.strip()
        # 整行空壳 -> 删
        if stripped and _LINE_ONLY.match(stripped):
            continue
        # 行内短语 -> 删
        for p in _PHRASES:
            if p in line:
                line = line.replace(p, "")
        line = line.rstrip()
        for pat, repl in _TIDY:
            line = pat.sub(repl, line)
        line = line.strip()
        if line:
            kept.append(line)
    out = "\n".join(kept).strip()
    # 全删光了就退回原文，不返回空
    if not out:
        return original
    # 行尾的句号「。」删掉（问号、感叹号、波浪号、省略号保留）
    out = re.sub(r"。(?=\s*$)", "", out, flags=re.M)
    out = "\n".join(x.rstrip() for x in out.split("\n") if x.strip()).strip()
    return out


@register("deai_clean", "Local", "去 AI 味硬后处理：删空壳套话", "1.0.1")
class DeaiClean(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._hits = 0

    @filter.on_decorating_result(priority=-20000)
    async def clean_reply(self, event: AstrMessageEvent):
        try:
            result = event.get_result()
            if result is None:
                return
            if not getattr(result, "is_model_result", lambda: False)():
                return
            for comp in result.chain:
                if not isinstance(comp, Plain):
                    continue
                before = comp.text or ""
                after = clean_text(before)
                if after != before:
                    self._hits += 1
                    logger.info(
                        f"[deai_clean] 删掉套话: {before[:40]!r} -> {after[:40]!r}"
                    )
                    comp.text = after
        except Exception as e:
            logger.warning(f"[deai_clean] 清理失败: {e}")
