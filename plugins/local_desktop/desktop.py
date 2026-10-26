"""Local desktop input and screenshot-scoped action validation."""

import ctypes
import secrets
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

KEYS = {
    "CTRL": 0x11,
    "SHIFT": 0x10,
    "ALT": 0x12,
    "WIN": 0x5B,
    "ENTER": 0x0D,
    "TAB": 0x09,
    "ESC": 0x1B,
    "BACKSPACE": 0x08,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "SPACE": 0x20,
    **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}
RISKS = {"normal", "send", "delete", "purchase", "submit", "security"}


class DesktopController:
    """Validate actions against the latest screenshot and explicit confirmations."""

    def __init__(self, backend, clock=time.monotonic):
        self.backend = backend
        self.clock = clock
        self.frames = {}
        self.pending = {}
        self.lock = threading.RLock()
        self.halted = threading.Event()
        self.backend.cancel = self.halted

    def screenshot(self, owner):
        """Capture the desktop and retain coordinate geometry for this owner."""
        with self.lock:
            bounds = self.backend.bounds()
            path, size = self.backend.capture()
            if self.backend.bounds() != bounds:
                raise ValueError("屏幕布局刚刚变化，请重新截图。")
            frame = {
                "capture_id": secrets.token_hex(8),
                "bounds": bounds,
                "size": size,
                "at": self.clock(),
                "path": str(path),
            }
            self.frames[owner] = frame
            self.pending.pop(owner, None)
            return {k: v for k, v in frame.items() if k != "at"}

    def _frame(self, owner, capture_id):
        frame = self.frames.get(owner)
        if not frame or frame["capture_id"] != capture_id:
            raise ValueError("请先获取当前会话的新截图，再进行操作。")
        if self.clock() - frame["at"] > 120:
            raise ValueError("截图已超过两分钟，请重新截图。")
        if self.backend.bounds() != frame["bounds"]:
            raise ValueError("屏幕布局变化，请重新截图。")
        return frame

    def act(
        self,
        owner,
        *,
        action,
        capture_id,
        x=0,
        y=0,
        end_x=0,
        end_y=0,
        button="left",
        clicks=1,
        amount=3,
        text="",
        keys="",
        risk="normal",
        reason="",
    ):
        """Validate a single action, executing it or creating a confirmation."""
        with self.lock:
            if self.halted.is_set():
                raise ValueError("桌面操作已停止。请由用户发送 /桌面继续。")
            frame = self._frame(owner, capture_id)
            if (
                action not in {"click", "drag", "scroll", "text", "keys"}
                or risk not in RISKS
            ):
                raise ValueError("未知操作或风险类型。")
            if not isinstance(reason, str) or len(reason) > 300:
                raise ValueError("操作说明不得超过300字。")
            spec = {"action": action}
            if action in {"click", "drag", "scroll"}:
                spec["x"], spec["y"] = self._point(frame, x, y)
            if action in {"click", "drag"}:
                if (
                    button not in {"left", "right", "middle"}
                    or type(clicks) is not int
                    or clicks not in {1, 2}
                ):
                    raise ValueError("鼠标按键或点击次数无效。")
                spec.update(button=button, clicks=clicks)
            if action == "drag":
                spec["end_x"], spec["end_y"] = self._point(frame, end_x, end_y)
            if action == "scroll":
                if type(amount) is not int or not 1 <= abs(amount) <= 20:
                    raise ValueError("滚动量需为-20至20的非零整数，正数向上。")
                spec["amount"] = amount
            if action == "text":
                if (
                    not isinstance(text, str)
                    or not text
                    or len(text) > 4000
                    or any(ord(c) < 32 for c in text)
                ):
                    raise ValueError(
                        "文字需为1至4000字；回车、制表等请使用快捷键工具。"
                    )
                spec["text"] = text
            if action == "keys":
                combo = keys.upper().split("+") if isinstance(keys, str) else []
                if not 1 <= len(combo) <= 4 or any(k not in KEYS for k in combo):
                    raise ValueError("快捷键无效，请使用如 CTRL+A、ALT+TAB、ENTER。")
                if len(combo) > 1 and any(
                    k not in {"CTRL", "SHIFT", "ALT", "WIN"} for k in combo[:-1]
                ):
                    raise ValueError("组合键只有最后一个按键可以是非修饰键。")
                if len(set(combo)) != len(combo):
                    raise ValueError("快捷键不得包含重复按键。")
                spec["keys"] = combo
            if risk != "normal":
                if not reason.strip():
                    raise ValueError("需确认的操作必须说明目的。")
                token = secrets.token_hex(3)
                self.pending[owner] = {
                    "token": token,
                    "spec": spec,
                    "frame": frame,
                    "expires": self.clock() + 60,
                }
                return {
                    "status": "confirmation_required",
                    "confirmation": token,
                    "reason": reason,
                    "instruction": f"请用户在60秒内发送 /桌面确认 {token}；模型不得代替用户确认。",
                }
            self.pending.pop(owner, None)
            return self._perform(owner, spec)

    @staticmethod
    def _point(frame, x, y):
        width, height = frame["size"]
        if (
            type(x) is not int
            or type(y) is not int
            or not (0 <= x < width and 0 <= y < height)
        ):
            raise ValueError("坐标必须位于最近截图范围内，以截图左上角为原点。")
        left, top, physical_width, physical_height = frame["bounds"]
        return left + x * physical_width // width, top + y * physical_height // height

    def _perform(self, owner, spec):
        if self.halted.is_set():
            raise ValueError("桌面操作已停止。")
        self.frames.clear()
        self.pending.clear()
        self.backend.perform(spec)
        return {
            "status": "done",
            "action": spec["action"],
            "next": "请重新截图核对结果，再决定下一步。",
        }

    def confirm(self, owner, token):
        """Consume a sender-bound confirmation once, checking its frame again."""
        with self.lock:
            pending = self.pending.get(owner)
            if not pending or not secrets.compare_digest(pending["token"], token):
                raise ValueError("没有匹配的待确认操作。")
            self.pending.pop(owner)
            if self.clock() > pending["expires"]:
                raise ValueError("确认已过期，请重新查看桌面并提出操作。")
            self._frame(owner, pending["frame"]["capture_id"])
            return self._perform(owner, pending["spec"])

    def stop(self):
        """Latch a global stop before waiting for any in-flight action."""
        self.halted.set()
        with self.lock:
            self.pending.clear()
            self.frames.clear()

    def resume(self):
        """Resume with no old screenshots or queued confirmations."""
        with self.lock:
            self.pending.clear()
            self.frames.clear()
            self.halted.clear()


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]


class WindowsDesktop:
    """Capture and operate the interactive Windows desktop with native input."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.cancel = threading.Event()
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(Input),
            ctypes.c_int,
        ]
        self.user32.SendInput.restype = wintypes.UINT
        self.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.user32.OpenInputDesktop.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.user32.OpenInputDesktop.restype = wintypes.HANDLE
        self.user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        self.user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        self.user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        self.user32.GetThreadDesktop.restype = wintypes.HANDLE
        self.user32.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]

    @contextmanager
    def _desktop(self):
        handle = self.user32.OpenInputDesktop(0, False, 0x01FF)
        if not handle:
            raise RuntimeError(
                "当前没有可访问的交互桌面；请检查是否锁屏或处于安全确认界面。"
            )
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if not self.user32.GetUserObjectInformationW(
                handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if name.value.casefold() != "default":
                raise RuntimeError(
                    "当前不是普通Windows桌面，请解锁或退出安全确认界面后重试。"
                )
            original = self.user32.GetThreadDesktop(
                ctypes.windll.kernel32.GetCurrentThreadId()
            )
            if not self.user32.SetThreadDesktop(handle):
                raise RuntimeError("无法连接当前交互桌面，请检查机器人运行会话。")
            try:
                previous = self.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
                if not previous:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    yield
                finally:
                    self.user32.SetThreadDpiAwarenessContext(previous)
            finally:
                self.user32.SetThreadDesktop(original)
        finally:
            self.user32.CloseDesktop(handle)

    def bounds(self):
        """Return physical virtual-screen origin, width, and height."""
        with self._desktop():
            return tuple(self.user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))

    def capture(self):
        """Save a bounded screenshot, preserving its coordinate mapping."""
        with self._desktop():
            image = ImageGrab.grab(all_screens=True)
            expected = tuple(self.user32.GetSystemMetrics(i) for i in (78, 79))
            if image.size != expected or min(expected) <= 0:
                raise RuntimeError("截图尺寸和桌面尺寸不一致，请检查显示器设置。")
            image.thumbnail((1920, 1920))
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{secrets.token_hex(12)}.jpg"
            image.convert("RGB").save(path, quality=90)
            # Keep at most 30 local captures; tool-image caching is managed by AstrBot.
            for old in sorted(
                self.directory.glob("*.jpg"), key=lambda p: p.stat().st_mtime
            )[:-30]:
                old.unlink(missing_ok=True)
            return path, image.size

    def _send(self, item):
        if self.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(Input)) != 1:
            raise RuntimeError(
                f"Windows拒绝输入（错误{ctypes.get_last_error()}）；目标可能以更高权限运行或桌面已锁定。"
            )

    def _mouse(self, flags, data=0):
        self._send(Input(type=0, mi=MouseInput(0, 0, data & 0xFFFFFFFF, flags, 0, 0)))

    def _key(self, vk=0, scan=0, flags=0):
        self._send(Input(type=1, ki=KeyboardInput(vk, scan, flags, 0, 0)))

    def _check_stop(self):
        if self.cancel.is_set():
            raise RuntimeError("桌面操作已停止。")

    def _move(self, x, y):
        if not self.user32.SetCursorPos(x, y):
            raise ctypes.WinError(ctypes.get_last_error())

    def perform(self, spec):
        """Perform one validated action and always release held input."""
        with self._desktop():
            self._check_stop()
            action = spec["action"]
            if action in {"click", "drag", "scroll"}:
                self._move(spec["x"], spec["y"])
            if action == "scroll":
                self._mouse(0x0800, spec["amount"] * 120)
            elif action in {"click", "drag"}:
                down, up = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}[
                    spec["button"]
                ]
                for _ in range(spec["clicks"] if action == "click" else 1):
                    self._check_stop()
                    self._mouse(down)
                    try:
                        if action == "drag":
                            for step in range(1, 21):
                                self._check_stop()
                                self._move(
                                    spec["x"]
                                    + (spec["end_x"] - spec["x"]) * step // 20,
                                    spec["y"]
                                    + (spec["end_y"] - spec["y"]) * step // 20,
                                )
                                time.sleep(0.02)
                    finally:
                        self._mouse(up)
                    time.sleep(0.06)
            elif action == "keys":
                pressed = []
                try:
                    for key in spec["keys"]:
                        self._check_stop()
                        self._key(KEYS[key])
                        pressed.append(KEYS[key])
                finally:
                    for vk in reversed(pressed):
                        self._key(vk, flags=2)
            elif action == "text":
                encoded = spec["text"].encode("utf-16-le")
                for offset in range(0, len(encoded), 2):
                    self._check_stop()
                    unit = int.from_bytes(encoded[offset : offset + 2], "little")
                    self._key(scan=unit, flags=4)
                    self._key(scan=unit, flags=6)
