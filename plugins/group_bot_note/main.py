"""机器人账号库：识别机器人账号，注入「只点评别多聊」的提示。

- 管理员说「10004 是机器人」→ 加入账号库并持久化
- 管理员说「10004 不是机器人」→ 移出账号库
- 持久化：data/plugin_data/group_bot_note/bots.json
"""

import json
import os
import re
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# 管理员 QQ 号占位符，改成你自己的（可多个）
ADMINS = {"10001", "10002"}
DATA_DIR = str(Path(__file__).resolve().parents[2] / "plugin_data" / "group_bot_note")
BOTS_FILE = os.path.join(DATA_DIR, "bots.json")

# 初始账号（首次没有文件时使用）
DEFAULT_BOTS = {"10004"}

_ADD_RE = re.compile(r"(\d{5,12})\s*(?:也|以后|就|都)?\s*(?:是|当成|当作|当|算)\s*机器人")
_DEL_RE = re.compile(r"(\d{5,12})\s*(?:不是|不算)\s*机器人")

_NOTE = (
    "\n[群机器人] 这条消息来自机器人账号 {uid}（不是真人）。"
    "对它：回复尽量一句话（20 字以内），别跟它一问一答地聊，当热闹看。"
    "可以点评它，像人看机器人那样：「这机器人说话真官方」「挺像那么回事」「又来念稿了」。"
    "不当它是真人，不用客气。\n"
)


def _load() -> set[str]:
    try:
        if os.path.exists(BOTS_FILE):
            with open(BOTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return {str(x) for x in data if str(x).strip()}
    except Exception as e:
        logger.warning(f"[group_bot_note] 读取账号库失败: {e}")
    return set(DEFAULT_BOTS)


def _save(bots: set[str]) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BOTS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(bots), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[group_bot_note] 保存账号库失败: {e}")


@register("group_bot_note", "Local", "机器人账号库", "1.1.0")
class GroupBotNote(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._bots = _load()
        logger.info(f"[group_bot_note] 账号库加载 {len(self._bots)} 个: {sorted(self._bots)}")

    # ---------- 管理员增删 ----------
    @filter.on_waiting_llm_request(priority=5)
    async def detect_admin_cmd(self, event: AstrMessageEvent):
        try:
            uid = str(event.get_sender_id() or "")
            if uid not in ADMINS:
                return
            text = (event.message_str or "").strip()
            if not text or "机器人" not in text:
                return

            m_add = _ADD_RE.search(text)
            if m_add:
                target = m_add.group(1)
                self._bots.add(target)
                _save(self._bots)
                await event.send(event.plain_result(f"记下了，{target} 以后当机器人处理"))
                event.stop_event()
                return

            m_del = _DEL_RE.search(text)
            if m_del:
                target = m_del.group(1)
                if target in self._bots:
                    self._bots.discard(target)
                    _save(self._bots)
                    await event.send(event.plain_result(f"好，{target} 不当机器人了"))
                else:
                    await event.send(event.plain_result(f"{target} 本来就不在机器人库里"))
                event.stop_event()
        except Exception as e:
            logger.warning(f"[group_bot_note] 处理管理指令失败: {e}")

    # ---------- 识别机器人并注入 ----------
    @filter.on_llm_request(priority=-70)
    async def mark_bot(self, event: AstrMessageEvent, req):
        try:
            uid = str(event.get_sender_id() or "")
            if uid not in self._bots:
                return
            req.system_prompt = (
                (getattr(req, "system_prompt", None) or "")
                + _NOTE.format(uid=uid)
            )
            gid = str(event.get_group_id() or "私聊")
            logger.info(f"[group_bot_note] 识别到机器人 {uid}（场景 {gid}）")
        except Exception as e:
            logger.warning(f"[group_bot_note] 注入失败: {e}")
