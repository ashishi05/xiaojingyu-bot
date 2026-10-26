"""睡眠模式：管理员说「没你事儿了」之类，机器人就闭嘴；只有 @ 她才能叫醒。

- 睡眠触发（仅管理员）：没你事儿了 / 睡吧 / 去睡 / 闭嘴 / 别说了 / 安静
- 唤醒：必须 @ 机器人（文字里说「醒醒」不管用）
- 状态持久化：data/plugin_data/sleep_mode/state.json
- 隔离：按会话（unified_msg_origin）
"""

import json
import os
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star, register

DATA_DIR = str(Path(__file__).resolve().parents[2] / "plugin_data" / "sleep_mode")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# 管理员 QQ 号占位符，改成你自己的（可多个）
ADMINS = {"10001", "10002"}

_SLEEP_WORDS = ["没你事儿了", "没你事了", "睡吧", "去睡", "闭嘴", "别说了", "安静", "歇着吧"]


def _load() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.warning(f"[sleep_mode] 读状态失败: {e}")
    return {}


def _save(state: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[sleep_mode] 存状态失败: {e}")


@register("sleep_mode", "Local", "睡眠模式（@ 才能叫醒）", "1.1.0")
class SleepMode(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._state = _load()

    def _sleeping(self, umo: str) -> bool:
        return bool(self._state.get(umo, False))

    @filter.on_waiting_llm_request(priority=25)
    async def handle(self, event: AstrMessageEvent):
        try:
            text = (event.message_str or "").strip()
            umo = event.unified_msg_origin

            if self._sleeping(umo):
                # 只有 @ 机器人才能唤醒
                at_self = False
                try:
                    self_id = str(event.get_self_id() or "")
                    for m in (event.get_messages() or []):
                        if isinstance(m, At) and str(m.qq) == self_id:
                            at_self = True
                            break
                except Exception:
                    pass

                if at_self:
                    self._state[umo] = False
                    _save(self._state)
                    await event.send(event.plain_result("醒了醒了，本鱼在这儿"))
                    event.stop_event()
                    logger.info("[sleep_mode] 被 @ 唤醒")
                else:
                    logger.info("[sleep_mode] 睡眠中，没 @，静默")
                    event.stop_event()
                return

            # 没睡：管理员下令睡觉
            if not text:
                return
            uid = str(event.get_sender_id() or "")
            if uid in ADMINS and any(w in text for w in _SLEEP_WORDS):
                self._state[umo] = True
                _save(self._state)
                await event.send(event.plain_result("行，本鱼先躺了，@ 我或者有事再喊"))
                event.stop_event()
                return
        except Exception as e:
            logger.warning(f"[sleep_mode] 处理失败: {e}")
