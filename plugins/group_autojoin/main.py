"""群库同步：管理员说一声「拉进群了 / 更新群库」，就把机器人在的群补进白名单。

- 不轮询（省资源），改成手动触发
- 触发（仅管理员）：拉进群了 / 更新群库 / 同步群 / 加群了
- 动作：get_group_list → 白名单缺的补上 → 热更新内存
"""

import json
import shutil
import tempfile
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# 插件位于 <AstrBot>/data/plugins/<插件名>/，parents[2] 即 <AstrBot>/data
CONFIG = str(Path(__file__).resolve().parents[2] / "cmd_config.json")
# 管理员 QQ 号占位符，改成你自己的（可多个）
ADMINS = {"10001", "10002"}

# 触发词
_TRIGGERS = [
    "拉进群了",
    "拉我进群",
    "进群了",
    "加群了",
    "新群",
    "更新群库",
    "同步群",
    "更新群列表",
    "同步群列表",
    "更新白名单",
]


def _find_bot(context: Context):
    try:
        for inst in context.platform_manager.platform_insts:
            bot = getattr(inst, "bot", None)
            if bot is not None:
                return bot
    except Exception as e:
        logger.warning(f"[group_autojoin] 获取平台实例失败: {e}")
    return None


def _read_whitelist() -> list[str]:
    try:
        cfg = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
        wl = cfg["platform_settings"]["id_whitelist"]
        return [str(x).strip() for x in wl if str(x).strip()]
    except Exception as e:
        logger.warning(f"[group_autojoin] 读配置失败: {e}")
        return []


def _save_whitelist(wl: list[str]) -> bool:
    """Replace the config only after the complete update is written."""
    pending = None
    try:
        config = Path(CONFIG)
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["platform_settings"]["id_whitelist"] = wl
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config.parent,
            prefix=config.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            pending = Path(stream.name)
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
        shutil.copy2(config, str(config) + ".autojoin.bak")
        pending.replace(config)
        return True
    except Exception as e:
        logger.error(f"[group_autojoin] Config update failed: {e}")
        return False
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _patch_runtime(gid: str) -> bool:
    """把群号塞进运行中的 WhitelistCheckStage，不用重启。"""
    try:
        import gc

        from astrbot.core.pipeline.whitelist_check.stage import WhitelistCheckStage

        ok = False
        for obj in gc.get_objects():
            if isinstance(obj, WhitelistCheckStage):
                try:
                    if gid not in obj.whitelist:
                        obj.whitelist.append(gid)
                    ok = True
                except Exception:
                    pass
        return ok
    except Exception as e:
        logger.warning(f"[group_autojoin] 热更新失败: {e}")
        return False


@register("group_autojoin", "Local", "手动同步群库（不再轮询）", "2.0.0")
class GroupAutoJoin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_waiting_llm_request(priority=5)
    async def manual_sync(self, event: AstrMessageEvent):
        try:
            uid = str(event.get_sender_id() or "")
            if uid not in ADMINS:
                return
            text = (event.message_str or "").strip()
            if not text or not any(w in text for w in _TRIGGERS):
                return

            bot = _find_bot(self.context)
            if bot is None:
                await event.send(event.plain_result("平台还没连上，稍后再试"))
                event.stop_event()
                return

            try:
                groups = await bot.call_action(action="get_group_list")
            except Exception as e:
                await event.send(event.plain_result(f"拉群列表失败：{e}"))
                event.stop_event()
                return

            if not isinstance(groups, list):
                await event.send(event.plain_result("群列表格式不对，同步失败"))
                event.stop_event()
                return

            wl = _read_whitelist()
            added = []
            for g in groups:
                if not isinstance(g, dict):
                    continue
                gid = str(g.get("group_id") or "").strip()
                if not gid or gid == "100000001":
                    continue
                key = f"qqbot:GroupMessage:{gid}"
                if key in wl:
                    continue
                wl.append(key)
                added.append(gid)

            if not added:
                await event.send(
                    event.plain_result(f"群库已是最新（共 {len(groups)} 个群）")
                )
                event.stop_event()
                return

            if _save_whitelist(wl):
                for gid in added:
                    _patch_runtime(gid)
                await event.send(
                    event.plain_result(
                        f"群库已更新，新增 {len(added)} 个群：{', '.join(added)}"
                    )
                )
            else:
                await event.send(event.plain_result("写配置失败，群库没更新"))
            event.stop_event()
            logger.info(f"[group_autojoin] 手动同步: 新增 {added}")
        except Exception as e:
            logger.warning(f"[group_autojoin] 处理失败: {e}")
