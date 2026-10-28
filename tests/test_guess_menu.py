import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "AstrBot"), str(ROOT / "AstrBot")]
from astrbot.api.message_components import Plain  # noqa: E402
from astrbot.core.star.filter.command import CommandFilter  # noqa: E402
from astrbot.core.star.star_handler import EventType, star_handlers_registry  # noqa: E402
from data.plugins.function_menu import main as menu  # noqa: E402


async def main():
    handler = next(
        h
        for h in star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent
        )
        if h.handler_module_path == menu.__name__ and h.handler_name == "guess_menu"
    )
    command_filter = next(
        f for f in handler.event_filters if isinstance(f, CommandFilter)
    )
    assert handler.extras_configs["priority"] > 200004
    for command in ("猜", "猜猜猜", "猜菜单", "换个猜"):
        sent, extra, stopped = [], {}, []
        plugin = menu.FunctionMenu.__new__(menu.FunctionMenu)
        plugin.context = SimpleNamespace(
            get_registered_star=lambda name: SimpleNamespace(
                activated=name != "famous_person_guess"
            )
        )

        async def send(result):
            sent.append(result)

        event = SimpleNamespace(
            message_str=command,
            get_messages=lambda: [Plain(text="/" + command)],
            get_sender_id=lambda: "user",
            get_self_id=lambda: "bot",
            message_obj=SimpleNamespace(raw_message={"post_type": "message"}),
            get_message_str=lambda: command,
            is_at_or_wake_command=True,
            get_platform_name=lambda: "aiocqhttp",
            set_extra=lambda k, v: extra.__setitem__(k, v),
            get_extra=lambda k, default=None: extra.get(k, default),
            plain_result=lambda text: text,
            send=send,
            stop_event=lambda: stopped.append(True),
        )
        assert command_filter.filter(event, {})
        await plugin.guess_menu(event)
        assert stopped and len(sent) == 1
        assert all(
            "/" + name in sent[0]
            for name in ("猜角色", "猜国家", "猜游戏", "猜网络人物")
        )
        assert "/猜知名人物" not in sent[0]
        assert all(
            extra.get(name + "_gameplay")
            for name in (
                "emoji_guess",
                "country_guess",
                "videogame_guess",
                "famous_person_guess",
                "network_person_guess",
            )
        )
        plugin.context.get_registered_star = lambda name: SimpleNamespace(
            activated=True
        )
        await plugin.guess_menu(event)
        assert "/猜知名人物" in sent[-1]
    print(
        "PASS: menu aliases, priority above active games, only enabled games, game output markers"
    )


asyncio.run(main())
