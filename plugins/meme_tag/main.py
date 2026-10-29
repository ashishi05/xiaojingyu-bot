"""表情包按标签发送：模型写 [[tag:标签]]，从大池子里按备注标签挑图发。

- 大池子：packs/official-001/memes/all/ 下所有图片
- 标签：sticker_notes.json 里每条备注的 tags 字段
- 匹配：标签做子串匹配（"生气"能匹配 "生气,吐槽"），再随机挑一张
- 兜底：清掉模型惯性输出的旧格式 &&xxx&&，避免漏到聊天里
"""

import json
import os
import random
import re
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register

_MEME_DATA_DIR = Path(__file__).resolve().parents[2] / "plugin_data" / "meme_manager"
MEMES_DIR = str(_MEME_DATA_DIR / "packs" / "official-001" / "memes" / "all")
NOTES_PATH = str(_MEME_DATA_DIR / "sticker_notes.json")
CACHE_DIR = str(_MEME_DATA_DIR.parent / "meme_tag_cache")

# 标签标记：[[tag:生气]]
_TAG_RE = re.compile(r"\[\[tag[:：]\s*([^\]\s]+)\s*\]\]")
# 旧格式残留：&&xxx&&
_LEGACY_RESIDUE_RE = re.compile(r"&&[^&\n]{1,20}&&")
# 算正文长度时要去掉的标记
_MARKUP_STRIP_RE = re.compile(r"\[\[.*?\]\]|&&[^&]*?&&")

_AUTO_MEME_MAX_CHARS = 150
_MEME_COOLDOWN = 20.0
_LAST_MEME_TS: dict[str, float] = {}
_LAST_SENT: dict[str, str] = {}


def _load_notes() -> dict:
    """读 sticker_notes.json，返回 {文件名: {"tags": [...], "note": "..."}}。"""
    try:
        with open(NOTES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[meme_tag] 读备注失败: {e}")
        return {}


def _available_files() -> set[str]:
    """大池子里可用的图片文件名。"""
    try:
        return {
            f
            for f in os.listdir(MEMES_DIR)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        }
    except Exception:
        return set()


def _auto_pick(body: str, notes: dict, available: set[str]) -> str | None:
    """按正文关键词找标签，找不到时不配图。"""
    try:
        body_low = body.lower()
        hit = []
        for fn, meta in notes.items():
            if fn not in available:
                continue
            tags = [str(t).strip().lower() for t in (meta.get("tags") or [])]
            note = str(meta.get("note") or "").lower()
            if any(t and t in body_low for t in tags):
                hit.append(fn)
            elif note and any(
                seg and seg in body_low for seg in (note[:12], note[-12:])
            ):
                hit.append(fn)
        if hit:
            return random.choice(hit)
        return None
    except Exception:
        return None


def _to_qq_safe(path: str) -> str:
    """QQ 发不了静态 webp，转成 png 放缓存目录。"""
    try:
        if not path.lower().endswith(".webp"):
            return path
        os.makedirs(CACHE_DIR, exist_ok=True)
        out = os.path.join(
            CACHE_DIR, os.path.splitext(os.path.basename(path))[0] + ".png"
        )
        if os.path.exists(out):
            return out
        from PIL import Image as PILImage

        with PILImage.open(path) as im:
            im.save(out, "PNG")
        return out
    except Exception as e:
        logger.warning(f"[meme_tag] webp 转换失败: {e}")
        return path


def _pick(tag: str, notes: dict, available: set[str]) -> str | None:
    """按标签挑图：先精确匹配，再模糊匹配。"""
    tag_norm = tag.strip().lower()
    if not tag_norm:
        return None
    exact, fuzzy, note_hit = [], [], []
    for fn, meta in notes.items():
        if fn not in available:
            continue
        tags = [str(t).strip().lower() for t in (meta.get("tags") or [])]
        note = str(meta.get("note") or "").lower()
        if any(tag_norm == t for t in tags):
            exact.append(fn)
        elif any(tag_norm in t for t in tags):
            fuzzy.append(fn)
        elif tag_norm in note:
            # 备注正文匹配放最低优先级，避免「困」命中「委屈困惑」
            note_hit.append(fn)
    pool = exact or fuzzy or note_hit
    if not pool:
        return None
    return random.choice(pool)


@register("meme_tag", "Local", "表情包按标签发送（大池子模式）", "1.0.0")
class MemeTag(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._notes = _load_notes()
        self._notes_mtime = 0.0
        try:
            self._notes_mtime = os.path.getmtime(NOTES_PATH)
        except Exception:
            pass

    def _refresh_notes(self) -> dict:
        try:
            mtime = os.path.getmtime(NOTES_PATH)
            if mtime != self._notes_mtime:
                self._notes = _load_notes()
                self._notes_mtime = mtime
                logger.info(f"[meme_tag] 备注已刷新（{len(self._notes)} 条）")
        except Exception:
            pass
        return self._notes

    @filter.on_decorating_result(priority=-15000)
    async def tag_send(self, event: AstrMessageEvent):
        try:
            result = event.get_result()
            if result is None:
                return
            notes = self._refresh_notes()
            available = _available_files()
            if not available:
                logger.warning("[meme_tag] 大池子为空，跳过")
                return

            # 冷却：20 秒内同一会话只发一张
            umo = event.unified_msg_origin
            now = time.time()
            in_cooldown = (now - _LAST_MEME_TS.get(umo, 0)) < _MEME_COOLDOWN
            selected = result.is_model_result() and random.random() < 0.7

            new_chain = []
            picked_files = []
            for comp in result.chain:
                if not isinstance(comp, Plain):
                    new_chain.append(comp)
                    continue

                text = comp.text or ""

                # 1) 提取 [[tag:xxx]]
                tags = [m.group(1).strip() for m in _TAG_RE.finditer(text)]
                if tags:
                    text = _TAG_RE.sub("", text)

                # 2) 清掉旧格式 &&xxx&&（不发图，只删标记）
                if "&&" in text:
                    cleaned = _LEGACY_RESIDUE_RE.sub("", text)
                    if cleaned != text:
                        logger.info(f"[meme_tag] 清掉旧格式标记: {text[:60]}")
                        text = cleaned

                # 3) 按标签选图
                for tag in tags:
                    if in_cooldown or not selected:
                        logger.info(f"[meme_tag] 冷却中，跳过标签「{tag}」")
                        break
                    fn = _pick(tag, notes, available)
                    if fn:
                        picked_files.append(fn)
                        _LAST_SENT[event.unified_msg_origin] = fn
                        logger.info(f"[meme_tag] 标签「{tag}」→ {fn}")
                    else:
                        logger.info(f"[meme_tag] 标签「{tag}」没找到图")

                text = text.strip()
                if text:
                    new_chain.append(Plain(text))



            # 5) 附上表情（最多一张），独立气泡由下游拆分
            if picked_files:
                _LAST_MEME_TS[umo] = now
                path = _to_qq_safe(os.path.join(MEMES_DIR, picked_files[0]))
                try:
                    new_chain.append(Image.fromFileSystem(path))
                except Exception as e:
                    logger.warning(f"[meme_tag] 构造图片失败: {e}")

            # 无论有没有配图，标记都已清掉，直接应用结果
            result.chain = new_chain
        except Exception as e:
            logger.error(f"[meme_tag] 处理失败: {e}")

    @filter.on_llm_request(priority=-100)
    async def inject_tag_hint(self, event: AstrMessageEvent, req):
        """每轮注入：可用的高频标签，让模型知道能写什么。"""
        try:
            notes = self._refresh_notes()
            from collections import Counter

            counter = Counter()
            available = _available_files()
            for fn, meta in notes.items():
                if fn not in available:
                    continue
                for t in (meta.get("tags") or []):
                    t = str(t).strip()
                    if t:
                        counter[t] += 1
            top = [t for t, _ in counter.most_common(40)]
            if not top:
                return
            base = getattr(req, "system_prompt", None) or ""
            req.system_prompt = base + (
                "\n[表情发送] 适合配图的日常闲聊可在回复末尾另起一行写 [[tag:标签]]，由程序决定是否发送；"
                "程序会按标签挑图单独发一条。执行任务、严肃话题、用户难过、内容太长时不配。"
                "标签要贴当前语境，一次最多一个。常用标签："
                + "、".join(top)
                + "\n"
            )
        except Exception as e:
            logger.warning(f"[meme_tag] 注入标签提示失败: {e}")
