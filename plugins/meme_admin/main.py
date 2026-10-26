import asyncio
import copy
import json
import re
import os
import sys
import time
from pathlib import Path

from astrbot.api import llm_tool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Reply
from astrbot.api.star import Context, Star, register

# meme_manager 是同级插件，把插件根目录加入 sys.path 以便复用它的图片操作接口
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

# 允许操作表情库的账号（老大 + 小号）
_ALLOWED = {"10001", "10002"}

# 每个会话最近发出去的那张表情：umo -> {"filename","category","path","time"}
_LAST_MEME: dict[str, dict] = {}

# 表情备注：filename -> {note, tags, updated}
# 依赖 meme_manager 插件的备注数据；没装时这里读不到，功能自动降级
_MEME_DATA_DIR = Path(__file__).resolve().parents[2] / "plugin_data" / "meme_manager"
_NOTES_PATH = os.path.join(str(_MEME_DATA_DIR), "sticker_notes.json")


def _load_notes() -> dict:
    try:
        with open(_NOTES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_notes(notes: dict) -> None:
    os.makedirs(os.path.dirname(_NOTES_PATH), exist_ok=True)
    try:
        with open(_NOTES_PATH, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[meme_admin] 保存备注失败: {e}")


def _images():
    from meme_manager.backend.packs import images

    return images


def _denied(event: AstrMessageEvent) -> str | None:
    try:
        sender = str(event.get_sender_id())
    except Exception:
        return "无法确认身份，拒绝操作。"
    if sender not in _ALLOWED:
        return "只有老大能管理表情库。"
    return None


@register("meme_admin", "Local", "表情库管理工具：收录、查看、删除、改分类", "1.1.0")
class MemeAdmin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._recent_images = {}
        self._collect_lock = asyncio.Lock()

    def _collection_images(self, event):
        components = event.message_obj.message
        current = [c for c in components if isinstance(c, Image)]
        if current:
            return current
        replies = [c for c in components if isinstance(c, Reply)]
        if replies:
            return [c for reply in replies for c in (reply.chain or []) if isinstance(c, Image)]
        key = (event.unified_msg_origin, str(event.get_sender_id()))
        cached = self._recent_images.get(key)
        if cached and time.monotonic() - cached[0] <= 300:
            return cached[1]
        self._recent_images.pop(key, None)
        return []

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=90)
    async def receive_collection_request(self, event: AstrMessageEvent):
        if event.get_platform_name() != "aiocqhttp" or _denied(event):
            return
        now = time.monotonic()
        for key, (seen, _) in list(self._recent_images.items()):
            if now - seen > 300:
                del self._recent_images[key]
        images = [c for c in event.message_obj.message if isinstance(c, Image)]
        if images:
            key = (event.unified_msg_origin, str(event.get_sender_id()))
            self._recent_images[key] = (now, images)
        text = (event.message_str or "").strip()
        # Only standalone collection requests bypass the model; questions stay in chat.
        if not re.fullmatch(
            r"(?:请|帮我|麻烦)?(?:把|将)?(?:刚才的?|这些|这几个|这几张|这张|这个|那几个|那几张|那张|那个)?"
            r"(?:图片|图|表情包|表情)?(?:都|全部|一起)?"
            r"(?:加进|加入|添加到|添加进|放进|放到|存进|存到|收进|收录到|保存到|收藏到)"
            r"(?:你的|本地的?)?(?:表情包库|表情库|图库)(?:里|里面)?(?:吧|哦|呀|一下)?[。！!～~]*",
            text,
        ):
            return
        event.stop_event()
        result = await self.meme_collect_tool(event)
        await event.send(event.plain_result(result))

    @filter.on_llm_request(priority=50)
    async def collection_instructions(self, event, req):
        if _denied(event):
            return
        req.system_prompt += (
            "\n【表情收录】老大要求把当前、引用或刚发的图片加入表情库时，直接调用 meme_collect；"
            "未指定分类时 category 留空，存入 all 文件夹。图片由工具从消息中获取，无需传路径。"
            "禁止为表情收录查找磁盘目录、运行 shell/Python 或自行复制文件。"
            "直接操作，最后依据工具结果用一条消息反馈新增、重复或失败，不播报步骤，不预先宣称成功。"
        )

    @llm_tool(name="meme_collect")
    async def meme_collect_tool(self, event: AstrMessageEvent, category: str = "") -> str:
        """把老大当前消息、引用消息或5分钟内最近一条图片消息批量收进表情库。

        Args:
            category(string): 已有分类名称；留空放入 all 文件夹，不需要目录或文件路径。
        """
        denied = _denied(event)
        if denied:
            return denied
        images = self._collection_images(event)
        if not images:
            return "没找到要收录的图片，请把图片和收录要求一起发来，或引用那条图片消息"
        metadata = self.context.get_registered_star("meme_manager")
        manager = metadata.star_cls if metadata else None
        if manager is None:
            return "表情插件暂时不可用，这次没有收录"
        category = (category or "").strip() or "all"
        async with self._collect_lock:
            from meme_manager.backend.packs.categories import resolve_safe_category_directory
            from meme_manager.backend.packs.resolver import get_pack_paths
            key = f"{event.session_id}_{event.get_sender_id()}"
            previous = manager.upload_states.pop(key, None)
            working = None
            try:
                context = manager._resolve_runtime_pack_context(event=event)
                pack_id = str(context.get("pack_id") or "")
                paths = get_pack_paths(pack_id)
                pack_dir = Path(paths["pack_dir"]).resolve()
                memes_dir = Path(paths["memes_dir"]).resolve()
                if not pack_id or not pack_dir.is_dir() or memes_dir == pack_dir:
                    raise ValueError("没有可用的主表情包")
                memes_dir.relative_to(pack_dir)
                if memes_dir != Path(str(context.get("memes_dir") or "")).resolve():
                    raise ValueError("表情包路径与当前使用规则不一致")
                target = resolve_safe_category_directory(memes_dir, category)
                if category == "all" and not target.is_dir():
                    manager.semantic_task_manager.begin_external_pack_operation(pack_id, "创建 all 文件夹")
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                    finally:
                        manager.semantic_task_manager.end_external_pack_operation(pack_id)
                proxy = copy.copy(event)
                proxy.message_obj = copy.copy(event.message_obj)
                proxy.message_obj.message = list(images)
                setup = []
                async for result in manager.upload_meme(proxy, category):
                    setup.append(result.get_plain_text())
                working = manager.upload_states.get(key)
                if working is None:
                    return "\n".join(setup) or "未能开始收录，请稍后重试"
                results = []
                async for result in manager._handle_upload_image_impl(proxy):
                    results.append(result.get_plain_text())
                message = "\n".join(results)
                message = message.replace(f"主表情包「{pack_id}」分类「{category}」", f"「{category}」分类")
                return message or "收录没有返回结果，请稍后确认，暂不宣称成功"
            except Exception:
                logger.exception("[meme_admin] 批量收录失败")
                return "收录失败，可能是图片已过期或表情库暂时忙，请重发图片后重试"
            finally:
                if manager.upload_states.get(key) is working:
                    manager.upload_states.pop(key, None)
                if previous is not None and key not in manager.upload_states:
                    manager.upload_states[key] = previous

    @llm_tool(name="meme_list")
    async def meme_list_tool(self, event: AstrMessageEvent, category: str = "") -> str:
        """列出表情库内容。category 留空时列出所有分类及数量；填分类名时列出该分类下的文件名。"""
        denied = _denied(event)
        if denied:
            return denied
        try:
            scan = await _images().scan_emoji_folder()
            if category:
                items = scan.get(category) or []
                if not items:
                    return f"分类「{category}」不存在或是空的。现有分类：{', '.join(scan.keys())}"
                return f"「{category}」共 {len(items)} 张：\n" + "\n".join(items[:40])
            if not scan:
                return "表情库现在是空的。"
            return "表情库分类与数量：\n" + "\n".join(
                f"- {name}: {len(files)}" for name, files in scan.items()
            )
        except Exception as e:
            logger.error(f"[meme_admin] meme_list 失败: {e}")
            return f"读取表情库失败：{e}"

    @llm_tool(name="meme_delete")
    async def meme_delete_tool(
        self, event: AstrMessageEvent, category: str = "", filename: str = ""
    ) -> str:
        """删除表情。可以只给 filename（会自动找它所在的分类）；category 和 filename 都留空时删除刚发出去的那张。"""
        denied = _denied(event)
        if denied:
            return denied
        filename = (filename or "").strip()
        category = (category or "").strip()
        if not filename and not category:
            info = _LAST_MEME.get(event.unified_msg_origin)
            if not info:
                return "不知道要删哪张，本鱼还没在这个会话发过表情。"
            filename = info["filename"]
            category = info["category"]
        elif filename and not category:
            try:
                scan = await _images().scan_emoji_folder()
            except Exception as e:
                return f"读取表情库失败：{e}"
            for cat, files in scan.items():
                if filename in files:
                    category = cat
                    break
            if not category:
                return f"表情库里没有找到 {filename}"
        try:
            result = _images().delete_emoji_from_category(category, filename)
            _LAST_MEME.pop(event.unified_msg_origin, None)
            return f"已删除 {category}/{filename}：{result}"
        except Exception as e:
            logger.error(f"[meme_admin] meme_delete 失败: {e}")
            return f"删除失败：{e}"

    @llm_tool(name="meme_move")
    async def meme_move_tool(
        self,
        event: AstrMessageEvent,
        category: str,
        filename: str,
        target: str,
    ) -> str:
        """把表情从一个分类移到另一个分类。category 是原分类，filename 是文件名，target 是目标分类（不存在会自动创建）。"""
        denied = _denied(event)
        if denied:
            return denied
        try:
            result = _images().move_emoji_to_category(category, filename, target)
            return f"已移动：{result}"
        except Exception as e:
            logger.error(f"[meme_admin] meme_move 失败: {e}")
            return f"移动失败：{e}"

    @llm_tool(name="meme_clear")
    async def meme_clear_tool(self, event: AstrMessageEvent, category: str = "") -> str:
        """清空表情。category 填分类名只清空该分类；留空清空整个表情库（危险，必须经过老大明确同意）。"""
        denied = _denied(event)
        if denied:
            return denied
        try:
            images = _images()
            if category:
                result = images.clear_category_emojis(category)
                return f"已清空分类「{category}」：{result}"
            result = images.clear_all_emojis()
            return f"已清空整个表情库：{result}"
        except Exception as e:
            logger.error(f"[meme_admin] meme_clear 失败: {e}")
            return f"清空失败：{e}"

    @llm_tool(name="meme_note")
    async def meme_note_tool(
        self,
        event: AstrMessageEvent,
        filename: str,
        note: str,
        category: str = "",
        tags: str = "",
    ) -> str:
        """给某张表情写备注，让以后选图更准。filename 是文件名；note 是一句话描述这张图表达什么、适合什么场合；category 填了就把这张图移到该分类；tags 是逗号分隔的关键词。"""
        denied = _denied(event)
        if denied:
            return denied

        filename = (filename or "").strip()
        note = (note or "").strip()
        if not filename or not note:
            return "filename 和 note 都要填。"

        notes = _load_notes()
        moved = ""
        if category:
            src = category
            # 找到这张图现在在哪个分类
            try:
                scan = await _images().scan_emoji_folder()
            except Exception as e:
                return f"读取表情库失败：{e}"
            found_in = None
            for cat, files in scan.items():
                if filename in files:
                    found_in = cat
                    break
            if found_in is None:
                return f"表情库里没有找到 {filename}"
            if found_in != category:
                try:
                    _images().move_emoji_to_category(found_in, filename, category)
                    moved = f"（已从 {found_in} 移到 {category}）"
                except Exception as e:
                    return f"移动失败：{e}"

        notes[filename] = {
            "note": note,
            "tags": [t.strip() for t in (tags or "").split(",") if t.strip()],
        }
        _save_notes(notes)
        return f"备注已记下：{filename} → {note}{moved}"

    @filter.on_decorating_result(priority=-9999)
    async def record_last_meme(self, event: AstrMessageEvent):
        try:
            result = event.get_result()
            if result is None:
                return
            for comp in result.chain:
                if not isinstance(comp, Image):
                    continue
                path = getattr(comp, "path", "") or getattr(comp, "file", "") or ""
                if not path:
                    continue
                norm = path.replace("\\", "/")
                if "memes" not in norm:
                    continue
                fn = os.path.basename(norm)
                cat = os.path.basename(os.path.dirname(norm))
                _LAST_MEME[event.unified_msg_origin] = {
                    "filename": fn,
                    "category": cat,
                    "path": path,
                    "time": time.time(),
                }
                logger.info(f"[meme_admin] 记录刚发的表情: {cat}/{fn}")
        except Exception as e:
            logger.warning(f"[meme_admin] 记录表情失败: {e}")

    @llm_tool(name="meme_last")
    async def meme_last_tool(self, event: AstrMessageEvent) -> str:
        """查最近发出去的那张表情是哪个文件、属于哪个分类。老大说「刚发的那张」时先用这个。"""
        denied = _denied(event)
        if denied:
            return denied
        info = _LAST_MEME.get(event.unified_msg_origin)
        if not info:
            return "本鱼还没在这个会话里发过表情。"
        ago = int(time.time() - info["time"])
        note = ""
        try:
            n = _load_notes().get(info["filename"])
            if n and n.get("note"):
                note = f"｜备注：{n['note']}"
        except Exception:
            pass
        return (
            f"最近发的是「{info['category']}/{info['filename']}」"
            f"（{ago} 秒前）{note}"
        )
