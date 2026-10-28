"""Local Emoji rounds, deterministic answers, and durable scoped scores."""

import asyncio
import logging
import random
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

GAP_SECONDS = 0
ROUNDS = 5
LOG = logging.getLogger(__name__)
POOLS = {"lol": "英雄联盟", "val": "无畏契约", "hsr": "星穹铁道"}

GUESS_GAMES = (
    ("emoji_guess", "猜角色"),
    ("country_guess", "猜国家"),
    ("videogame_guess", "猜游戏"),
    ("famous_person_guess", "猜知名人物"),
    ("network_person_guess", "猜网络人物"),
    ("idiom_guess", "猜成语"),
    ("trivia_guess", "猜假冷知识"),
)
LAST_GAMES = {}


async def send_guess_menu(context, event):
    """Send enabled games for menu commands and return navigation.

    Args:
        context: Live plugin registry.
        event: Destination QQ event.
    """
    if event.get_platform_name() != "aiocqhttp":
        return
    event.stop_event()
    for name, _ in GUESS_GAMES:
        event.set_extra(name + "_gameplay", True)
    await event.send(event.plain_result(guess_menu_text(context)))


def guess_menu_text(context=None, *, finished=False):
    """Format the game choices for menus and match results.

    Args:
        context: Optional live registry used to hide disabled games.
        finished: Whether the text follows a finished match.

    Returns:
        Plain text with slash command entries.
    """
    lines = ["小鲸鱼 · 猜猜杯比赛"]
    for name, command in GUESS_GAMES:
        metadata = context.get_registered_star(name) if context else None
        if context is None or (metadata and metadata.activated):
            lines.append(f"• /{command}")
    lines.append(
        "直接发送上方指令开始新游戏"
        if finished
        else "按各玩法说明用 /名字 或 /编号 答题；/结束 结算整场"
    )
    return "\n".join(lines)


def occupied_game(context, scope: str, excluding: str) -> str | None:
    """Find another active game, including an unfinished pool selection.

    Args:
        context: AstrBot context used to inspect live plugin instances.
        scope: Native QQ conversation origin.
        excluding: Plugin whose own state is handled by its game manager.

    Returns:
        The occupying game's command name, or None.
    """
    for plugin_name, title in GUESS_GAMES:
        if plugin_name == excluding:
            continue
        metadata = context.get_registered_star(plugin_name)
        instance = metadata.star_cls if metadata and metadata.activated else None
        if instance and (
            scope in instance.manager.sessions
            or scope in getattr(instance, "pending", {})
        ):
            return title
    return None


def normalize(text: str) -> str:
    """Normalize a complete answer without matching substrings.

    Args:
        text: One candidate answer.

    Returns:
        Case-folded letters and numbers, or an empty string for oversized input.
    """
    if len(text) > 80:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum()
    )


def score_text(rows, limit=3) -> str:
    """Format match results, stopped matches, or persistent rankings.

    Args:
        rows: Tuples of display name, points, and correct answers.
        limit: Maximum displayed players.

    Returns:
        Plain-text ranking lines.
    """
    rows = sorted(rows, key=lambda row: (-row[1], -row[2], row[0]))[:limit]
    return (
        "\n".join(
            f"{i}. {name} · {points} 分（答对 {wins} 题）"
            for i, (name, points, wins) in enumerate(rows, 1)
        )
        or "本局暂无人得分"
    )


@dataclass
class Match:
    scope: str
    owner: str
    questions: list
    mode: str = "mixed"
    initial_clues: int = 1
    index: int = 0
    phase: str = "starting"
    started_at: float = 0
    hint_count: int = 0
    scores: dict = field(default_factory=dict)
    attempts: set = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    answered: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    error: Exception | None = None

    @property
    def question(self):
        return self.questions[self.index]

    @property
    def clue(self):
        if "options" in self.question:
            return "\n\n".join(
                f"{i}. {option['text']}"
                for i, option in enumerate(self.question["options"], 1)
            )
        return " ".join(
            self.question["emoji"].split()[: self.hint_count + self.initial_clues]
        )

    def points(self) -> int:
        """Return three, two, or one point for the manually revealed stage."""
        return 3 - self.hint_count


class GameManager:
    def __init__(
        self,
        questions: list,
        data_dir: Path,
        send,
        *,
        pools=None,
        title="猜角色",
        show_explanation=False,
        initial_clues=1,
    ):
        self._send_callback = send
        self.pools = POOLS if pools is None else pools
        self.title = title
        self.show_explanation = show_explanation
        if initial_clues not in (1, 2):
            raise ValueError("Initial clue count must be one or two")
        self.initial_clues = initial_clues
        self.resolve_alias = None
        self.sessions = {}
        self.start_lock = asyncio.Lock()
        self.bank = {game: [] for game in self.pools}
        self.aliases = {game: {} for game in self.pools}
        self.question_answers = {}
        ids = set()
        for q in questions:
            if q["id"] in ids or q["game"] not in self.bank:
                raise ValueError("Invalid question identity, game, or hints")
            options = q.get("options")
            if options is not None and (
                not isinstance(options, list)
                or len(options) != 3
                or any(
                    not isinstance(option, dict)
                    or not isinstance(option.get("text"), str)
                    or not option["text"].strip()
                    or not isinstance(option.get("truth"), bool)
                    or not isinstance(option.get("source_id"), str)
                    for option in options
                )
                or sum(not option["truth"] for option in options) != 1
                or len({option["source_id"] for option in options}) != 3
            ):
                raise ValueError(
                    "Each choice question needs two true and one false statement"
                )
            required = (
                ("answer", "explanation")
                if options
                else ("answer", "emoji", "explanation")
            )
            if not all(
                isinstance(q.get(k), str) and q[k].strip() for k in required
            ) or (
                options is None
                and (
                    len(q.get("hints", [])) != 2
                    or not all(isinstance(h, str) and h.strip() for h in q["hints"])
                )
            ):
                raise ValueError("Empty or invalid question text")
            ids.add(q["id"])
            if options is None and len(q["emoji"].split()) != self.initial_clues + 2:
                raise ValueError(
                    "Each question needs three manual stages of Emoji clues"
                )
            answers = {normalize(a) for a in q["answers"]}
            if not answers or "" in answers:
                raise ValueError("Invalid answer aliases")
            for name in answers:
                self.aliases[q["game"]].setdefault(name, set()).add(q["id"])
            self.question_answers[q["id"]] = answers
            self.bank[q["game"]].append(q)
        if any(len(pool) < ROUNDS for pool in self.bank.values()):
            raise ValueError(f"Each game needs at least {ROUNDS} questions")
        self.known_answers = set().union(*self.aliases.values())
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data_dir / "scores.sqlite3")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS scores (
                scope TEXT NOT NULL, user_id TEXT NOT NULL, name TEXT NOT NULL,
                points INTEGER NOT NULL, wins INTEGER NOT NULL,
                PRIMARY KEY(scope, user_id));
            CREATE TABLE IF NOT EXISTS recent (
                scope TEXT NOT NULL, question_id TEXT NOT NULL, played_at REAL NOT NULL,
                PRIMARY KEY(scope, question_id));
        """)
        cup_dir = (
            data_dir.parent / "guess_cup"
            if data_dir.name in dict(GUESS_GAMES)
            else data_dir / "guess_cup"
        )
        cup_dir.mkdir(parents=True, exist_ok=True)
        self.db.execute("ATTACH DATABASE ? AS cup", (str(cup_dir / "scores.sqlite3"),))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS cup.scores (
                scope TEXT NOT NULL, user_id TEXT NOT NULL, name TEXT NOT NULL,
                points INTEGER NOT NULL, wins INTEGER NOT NULL,
                PRIMARY KEY(scope, user_id));
            CREATE TABLE IF NOT EXISTS cup.sessions (
                scope TEXT PRIMARY KEY, owner TEXT NOT NULL);
        """)
        self.closed = False

    async def send(self, scope: str, text: str):
        """Abort a match if its delivery fails instead of leaving future timers.

        Args:
            scope: Destination conversation.
            text: Plain-text game message.
        """
        match = self.sessions.get(scope)
        try:
            if await self._send_callback(scope, text) is False:
                raise OSError("No matching message transport")
        except Exception as exc:
            if match is not None and self.sessions.get(scope) is match:
                match.error = exc
                await self.cancel(scope)
            raise

    async def cancel(self, scope: str):
        """Cancel a session without sending another message.

        Args:
            scope: Conversation being stopped, unloaded, or aborted.
        """
        match = self.sessions.get(scope)
        if match is None:
            return
        match.phase = "finished"
        if match.task is not asyncio.current_task():
            match.task.cancel()
            await asyncio.gather(match.task, return_exceptions=True)
        if self.sessions.get(scope) is match:
            self.sessions.pop(scope)

    async def start(self, scope: str, owner: str, mode: str):
        """Reserve one session and wait for its first question to be sent.

        Args:
            scope: Native QQ conversation origin.
            owner: User who starts the match.
            mode: A pool key, plus-separated pool keys, or legacy mixed (LOL/VAL).

        Raises:
            ValueError: The mode is invalid or a session already exists.
            RuntimeError: Initial delivery fails or the manager is closed.
        """
        if self.closed:
            raise RuntimeError("Game manager is closed")
        games = ("lol", "val") if mode == "mixed" else tuple(mode.split("+"))
        if (
            not games
            or any(game not in self.bank for game in games)
            or len(set(games)) != len(games)
        ):
            raise ValueError("请选择有效的角色池")
        async with self.start_lock:
            if scope in self.sessions:
                raise ValueError(
                    f"本会话已经有一局，请用 /名字 答题；结束用 /{self.title} 结束"
                )
            recent = {
                r[0]
                for r in self.db.execute(
                    "SELECT question_id FROM recent WHERE scope=? ORDER BY played_at DESC LIMIT 20",
                    (scope,),
                )
            }
            pool = [q for game in games for q in self.bank[game]]
            selected = []
            for _ in range(ROUNDS):
                used = {
                    option["source_id"]
                    for previous in selected
                    for option in previous.get("options", [])
                }
                available = [
                    q
                    for q in pool
                    if q not in selected
                    and not any(
                        option["source_id"] in used for option in q.get("options", [])
                    )
                ]
                fresh = [q for q in available if q["id"] not in recent]
                question = random.choice(fresh or available)
                if "options" in question:
                    question = dict(question)
                    question["options"] = random.sample(question["options"], 3)
                    answer = next(
                        i
                        for i, option in enumerate(question["options"], 1)
                        if not option["truth"]
                    )
                    question["answer"] = str(answer)
                    question["explanation"] = (
                        f"假的是第{answer}条：{question['options'][answer - 1]['text']}\n另外两条为真。"
                    )
                selected.append(question)
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO cup.sessions VALUES(?,?)",
                    (scope, str(owner)),
                )
            match = Match(
                scope, str(owner), selected, mode=mode, initial_clues=self.initial_clues
            )
            self.sessions[scope] = match
            LAST_GAMES.pop(scope, None)
            # Keep one task for the whole match so cancellation covers every timer.
            match.task = asyncio.create_task(self._run(match))
        await match.ready.wait()
        if match.error:
            raise RuntimeError("出题发送失败，请稍后重试") from match.error

    async def _run(self, match: Match):
        """Drive one match and clean up on timeout, failure, or cancellation.

        Args:
            match: The reserved match, identified by object identity on cleanup.
        """
        try:
            for index in range(ROUNDS):
                async with match.lock:
                    match.index = index
                    match.phase = "starting"
                    match.hint_count = 0
                    match.attempts.clear()
                    match.answered.clear()
                    q = match.question
                    text = f"🎮 {self.title} · 第 {index + 1}/{ROUNDS} 题\n\n{match.clue}\n\n答对 +3 分"
                    if index == 0 and "options" in q:
                        text += "\n三条中只有一条是假话\n/1、/2、/3：找出假的一条，每人每题一次\n答对 +3 分，答错不扣分；/揭秘：公布答案\n/结束：开局者或管理员可结束"
                    elif index == 0:
                        answer_kind = {
                            "猜国家": "国家",
                            "猜游戏": "游戏",
                            "猜知名人物": "人物",
                            "猜网络人物": "网络人物",
                            "猜成语": "成语",
                        }.get(self.title, "角色")
                        text += f"\n/{answer_kind}名字：每人每阶段一次\n/提示：追加 Emoji，重置答题次数\n/揭秘：{self.initial_clues + 2} 个 Emoji 全展示后可揭秘\n/结束：开局者或管理员可结束"
                    await self.send(match.scope, text)
                    match.started_at = time.perf_counter()
                    with self.db:
                        self.db.execute(
                            "INSERT INTO recent VALUES(?,?,?) ON CONFLICT(scope,question_id) DO UPDATE SET played_at=excluded.played_at",
                            (match.scope, q["id"], time.time()),
                        )
                    match.phase = "answering"
                    match.ready.set()
                await match.answered.wait()
                if index < ROUNDS - 1:
                    await asyncio.sleep(GAP_SECONDS)
            async with match.lock:
                match.phase = "finished"
                await self.send(
                    match.scope,
                    "本轮结束 🏁\n"
                    + self.leaderboard(match.scope, limit=None)
                    + "\n/继续：再来一轮　/换个猜：选其他玩法\n/结束：结算整场并清零\n\n"
                    + guess_menu_text(finished=True),
                )
                LAST_GAMES[match.scope] = (self, match.mode)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            match.error = exc
            LOG.exception("Emoji match failed; pending timers will be cancelled")
        finally:
            match.ready.set()
            match.phase = "finished"
            if self.sessions.get(match.scope) is match:
                self.sessions.pop(match.scope)

    async def guess(
        self,
        scope: str,
        user: str,
        name: str,
        text: str,
        received_at: float | None = None,
    ) -> bool:
        """Reserve one attempt, verify aliases, and atomically score the result.

        Args:
            scope: Native conversation origin.
            user: Actual sender ID.
            name: Player display name.
            text: One complete guess.
            received_at: Monotonic arrival time before waiting.

        Returns:
            Whether this guess won the current question.
        """
        match = self.sessions.get(scope)
        if match is None:
            return False
        arrived = time.perf_counter() if received_at is None else received_at
        async with match.lock:
            if match.phase != "answering" or arrived < match.started_at:
                return False
            if str(user) in match.attempts:
                await self.send(
                    scope,
                    "本题机会已用完，请等下一题"
                    if "options" in match.question
                    else "本阶段机会已用完，请等下一阶段或下一题",
                )
                return False
            index, stage = match.index, match.hint_count
            match.attempts.add(str(user))
        candidate = normalize(text)
        resolved = {
            question_id
            for aliases in self.aliases.values()
            for question_id in aliases.get(candidate, ())
        }
        question = match.questions[index]
        if "options" in question:
            resolved = {question["id"]} if candidate == question["answer"] else set()
        if not resolved and "options" not in question:
            try:
                async with asyncio.timeout(25):
                    resolved = (
                        await self.resolve_alias(scope, text)
                        if self.resolve_alias
                        else None
                    )
            except Exception as exc:  # noqa: BLE001 - failed lookups do not consume attempts.
                LOG.warning("Alias verification unavailable: %s", type(exc).__name__)
                resolved = None
        async with match.lock:
            if (
                self.sessions.get(scope) is not match
                or match.phase != "answering"
                or match.index != index
                or match.hint_count != stage
            ):
                return False
            if (
                not isinstance(resolved, set)
                or not resolved <= self.question_answers.keys()
            ):
                match.attempts.discard(str(user))
                await self.send(scope, "名称暂未确认，请换正式名字；本次不占次数")
                return False
            won = match.question["id"] in resolved
            points, wins = (match.points(), 1) if won else (0, 0)
            name = "".join(
                c for c in (name or str(user)) if c.isprintable() and c not in "[]"
            ).strip()[:30] or str(user)
            try:
                with self.db:
                    self.db.execute(
                        "INSERT INTO scores VALUES(?,?,?,?,?) ON CONFLICT(scope,user_id) DO UPDATE SET name=excluded.name,points=scores.points+excluded.points,wins=scores.wins+excluded.wins",
                        (scope, str(user), name, points, wins),
                    )
                    self.db.execute(
                        "INSERT INTO cup.scores VALUES(?,?,?,?,?) ON CONFLICT(scope,user_id) DO UPDATE SET name=excluded.name,points=scores.points+excluded.points,wins=scores.wins+excluded.wins",
                        (scope, str(user), name, points, wins),
                    )
            except sqlite3.Error:
                await self.cancel(scope)
                raise
            row = match.scores.setdefault(str(user), [name, 0, 0])
            row[0], row[1], row[2] = name, row[1] + points, row[2] + wins
            if not won:
                waiting = (
                    "下一阶段"
                    if stage < 2 and "options" not in match.question
                    else "下一题"
                )
                await self.send(scope, f"{name} 猜错了 · 等{waiting}再猜")
                return False
            match.phase = "gap"
            match.answered.set()
            await self.send(
                scope,
                f"✅ {match.question['answer']}\n{name} +{points} 分"
                + (
                    f"\n{match.question['explanation']}"
                    if self.show_explanation
                    else ""
                ),
            )
            return True

    async def hint(self, scope: str) -> bool:
        """Reveal the next public hint and lower the available score.

        Args:
            scope: Conversation whose active question receives the hint.

        Returns:
            Whether a new hint was sent.
        """
        match = self.sessions.get(scope)
        if match is None:
            return False
        async with match.lock:
            if (
                match.phase != "answering"
                or match.hint_count >= 2
                or "options" in match.question
            ):
                return False
            match.hint_count += 1
            match.attempts.clear()
            reveal_tip = "\n可 /揭秘" if match.hint_count == 2 else ""
            await self.send(
                scope,
                f"{match.clue}\n答对 +{match.points()} 分 · 每人可再猜一次{reveal_tip}",
            )
            match.started_at = time.perf_counter()
            return True

    async def reveal(self, scope: str) -> bool:
        """Reveal an unsolved question only after all three clues are visible.

        Args:
            scope: Conversation requesting the reveal.

        Returns:
            Whether an answer was revealed and the next round unlocked.
        """
        match = self.sessions.get(scope)
        if match is None:
            return False
        async with match.lock:
            if match.phase != "answering" or (
                "options" not in match.question and match.hint_count != 2
            ):
                return False
            match.phase = "gap"
            match.answered.set()
            await self.send(
                scope,
                f"揭秘 · 答案：{match.question['answer']}"
                + (
                    f"\n{match.question['explanation']}"
                    if self.show_explanation
                    else ""
                )
                + "\n本题无人答对",
            )
            return True

    async def stop(self, scope: str, user: str, admin: bool = False) -> bool:
        """Settle and reset the whole cup, including between rounds.

        Args:
            scope: Native conversation whose cup is ending.
            user: User requesting settlement.
            admin: Trusted group or bot administrator flag.

        Returns:
            Whether a cup was present.

        Raises:
            PermissionError: The requester is neither cup owner nor administrator.
        """
        match = self.sessions.get(scope)
        session = self.db.execute(
            "SELECT owner FROM cup.sessions WHERE scope=?", (scope,)
        ).fetchone()
        if match is None and session is None:
            return False
        owner = session[0] if session else match.owner
        if str(user) != owner and not admin:
            raise PermissionError("只有本场开局者或管理员能结束整场")
        answer = ""
        if match:
            async with match.lock:
                if match.phase == "answering":
                    answer = f"\n当前题答案：{match.question['answer']}"
                match.phase = "finished"
        summary = self.leaderboard(scope, limit=None)
        # Clear before awaiting delivery so a new cup cannot lose newly earned points.
        with self.db:
            self.db.execute("DELETE FROM cup.scores WHERE scope=?", (scope,))
            self.db.execute("DELETE FROM cup.sessions WHERE scope=?", (scope,))
        if match:
            await self.cancel(scope)
        await self.send(
            scope,
            "本场已结束。"
            + answer
            + "\n"
            + summary
            + "\n本场积分已清零\n/继续：同玩法开启新一场　/换个猜：选其他玩法\n\n"
            + guess_menu_text(finished=True),
        )
        if match:
            LAST_GAMES[scope] = (self, match.mode)
        return True

    def leaderboard(self, scope: str, limit: int | None = 10) -> str:
        rows = self.db.execute(
            "SELECT name,points,wins FROM cup.scores WHERE scope=? AND (wins>0 OR points<>0) ORDER BY points DESC,wins DESC,user_id",
            (scope,),
        ).fetchall()
        return "猜猜杯 · 本场累计积分\n" + (
            score_text(rows, len(rows) if limit is None else limit)
            if rows
            else "本场积分为 0，发 /猜 选择游戏"
        )

    async def close(self):
        if self.closed:
            return
        self.closed = True
        await asyncio.gather(*(self.cancel(scope) for scope in list(self.sessions)))
        self.sessions.clear()
        for scope, (manager, _) in list(LAST_GAMES.items()):
            if manager is self:
                LAST_GAMES.pop(scope)
        self.db.close()
