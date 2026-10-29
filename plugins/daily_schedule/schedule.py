"""Read the public Bo3 schedule feed and return only grounded match information."""

import asyncio
import re
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp

BEIJING = timezone(timedelta(hours=8))
GAMES = {"cs2": 1, "valorant": 2, "lol": 3}
PREFERRED = {
    "cs2": "https://www.hltv.org/matches",
    "valorant": "https://web.haojiao.cc/wiki/wiki_home/t2Ud5pOQlscKLbRC",
    "lol": "https://lpl.qq.com/web202301/event.html?gameId=246&tabId=schedule",
}
ALIASES = {
    "vct cn": "vct china",
    "cn": "china",
    "无畏契约": "valorant",
    "大师赛": "masters",
    "全球冠军赛": "champions",
    "世界赛": "worlds",
    "全球总决赛": "worlds",
    "晋升赛": "threshold",
    "edg": "edward gaming",
    "drg": "dragon ranger gaming",
    "nova": "nova",
    "navi": "natus vincere",
    "geng": "gen g",
    "blg": "bilibili gaming",
    "tes": "top esports",
    "hle": "hanwha life esports",
    "c9": "cloud9",
    "dk": "dplus kia",
    "ig": "invictus gaming",
    "kc": "karmine corp",
    "gen": "gen g",
}


def clean(value):
    """Normalize source whitespace without exposing other source fields."""
    return " ".join(str(value).replace("\\t", " ").split())


def words(value):
    value = clean(value).casefold().strip()
    for alias in sorted(ALIASES, key=len, reverse=True):
        value = re.sub(
            r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", ALIASES[alias], value
        )
    return re.findall(r"[a-z0-9\u4e00-\u9fff]+", value)


def normalize(payload, game, day):
    """Normalize a daily or live payload; fail visibly on schema changes.

    Args:
        payload: Public API JSON dictionary.
        game: Canonical game key.
        day: Requested date in Beijing, also used for an undetermined start time.

    Returns:
        Matches with Beijing times, teams, tournament, format, status and source URL.
    """
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("数据源没有返回有效赛程结构")
    data = payload["data"]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and isinstance(data.get("tiers"), dict):
        rows = []
        for tier in data["tiers"].values():
            if not isinstance(tier, dict) or not isinstance(tier.get("matches"), list):
                raise ValueError("数据源的赛事分组结构已变化")
            rows.extend(tier["matches"])
    else:
        raise ValueError("数据源的赛程格式已变化")
    included = payload.get("included") or {}
    teams = included.get("teams", {})
    tournaments = included.get("tournaments", {})
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get("discipline_id") != GAMES[game]:
            raise ValueError("数据源返回了其他游戏或无效比赛")
        start = row.get("start_date")
        local = None
        if start:
            local = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if local.tzinfo is None:
                raise ValueError("数据源的比赛时间缺少时区")
            local = local.astimezone(BEIJING)
        names, slugs = [], []
        for key in ("team1", "team2"):
            ref = row.get(key)
            team = teams.get(str(ref), {})
            names.append(clean(team.get("name") or (f"队伍#{ref}" if ref else "待定")))
            slugs.append(team.get("slug", ""))
        tournament = tournaments.get(str(row.get("tournament")), {})
        prefix = {"cs2": "", "valorant": "/valorant", "lol": "/lol"}[game]
        result.append(
            {
                "id": row["id"],
                "game": game,
                "date": local.date().isoformat() if local else day,
                "time": local.strftime("%Y-%m-%d %H:%M") if local else "时间待定",
                "teams": names,
                "team_slugs": slugs,
                "tournament": clean(tournament.get("name") or "赛事待定"),
                "tournament_slug": tournament.get("slug", ""),
                "format": f"BO{row['bo_type']}" if row.get("bo_type") else "赛制待定",
                "status": {
                    "upcoming": "未开始",
                    "current": "进行中",
                    "finished": "已结束",
                    "postponed": "已延期",
                    "canceled": "已取消",
                }.get(row.get("status"), "状态待确认"),
                "source_url": f"https://bo3.gg{prefix}/matches/{quote(row['slug'], safe='-')}",
            }
        )
    return result


def normalize_lpl(payload):
    """Read the user's official Worlds event feed, whose dates are Beijing local time."""
    if (
        not isinstance(payload, dict)
        or str(payload.get("status")) != "0"
        or not isinstance(payload.get("msg"), list)
    ):
        raise ValueError("LPL官方赛程结构已变化")
    result = []
    for row in payload["msg"]:
        if str(row.get("GameId")) != "246":
            raise ValueError("LPL返回了其他赛事")
        names = re.split(r"\s+vs\.?\s+", row["bMatchName"], flags=re.I)
        if len(names) != 2:
            names = ["待定", "待定"]
        local = datetime.strptime(row["MatchDate"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=BEIJING
        )
        result.append(
            {
                "id": int(row["bMatchId"]),
                "game": "lol",
                "date": local.date().isoformat(),
                "time": local.strftime("%Y-%m-%d %H:%M"),
                "teams": [
                    clean(row.get("TeamShortNameA") or names[0]),
                    clean(row.get("TeamShortNameB") or names[1]),
                ],
                "team_slugs": [],
                "round": clean(row["bMatchName"]),
                "tournament": clean(row["GameName"]),
                "tournament_slug": "worlds-2026",
                "format": row.get("GameModeName") or "赛制待定",
                "status": {"1": "未开始", "2": "进行中", "3": "已结束"}.get(
                    str(row.get("MatchStatus")), "状态待确认"
                ),
                "source_url": PREFERRED["lol"],
            }
        )
    return result


def select_matches(rows, game, tournament="", team=""):
    """Filter explicit queries or apply the user's VALORANT default scope."""
    result = []
    for row in rows:
        event_words = words(row["tournament"] + " " + row["tournament_slug"])
        team_words = words(" ".join(row["teams"] + row["team_slugs"]))
        if tournament:
            if not set(words(tournament)).issubset(event_words):
                continue
        elif game == "valorant":
            if "changers" in event_words:
                continue
            if not (
                ("vct" in event_words and "china" in event_words)
                or "masters" in event_words
                or "champions" in event_words
            ):
                continue
        if team and not set(words(team)).issubset(team_words):
            continue
        result.append(row)
    return result


class ScheduleClient:
    """Fetch bounded daily schedules using the same public endpoint as the site."""

    def __init__(self):
        self.semaphore = asyncio.Semaphore(4)

    async def _fetch(self, game, day, status):
        return await self._get(
            f"https://api.bo3.gg/api/v2/matches/{status}",
            {
                "date": day,
                "utc_offset": 28800,
                "filter[discipline_id][eq]": GAMES[game],
            },
        )

    async def _get(self, url, params=None):
        async with self.semaphore:
            for attempt in range(2):
                try:
                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=10), trust_env=True
                    ) as session:
                        async with session.get(
                            url,
                            params=params,
                            headers={
                                "User-Agent": "Mozilla/5.0",
                                "Origin": "https://bo3.gg",
                            },
                        ) as response:
                            response.raise_for_status()
                            return await response.json(content_type=None)
                except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                    if attempt:
                        raise

    async def query(
        self,
        game,
        date="",
        days=7,
        tournament="",
        team="",
        limit=10,
        include_finished=False,
        *,
        now=None,
    ):
        """Query a bounded date range without turning source failures into empty results.

        Args:
            game: cs2, valorant or lol.
            date: ISO start date in Beijing, empty for today.
            days: Number of calendar days, 1 through 14.
            tournament: Event keywords, overriding the VALORANT default filter.
            team: Canonical team name or a supported abbreviation.
            limit: Maximum returned matches, 1 through 20.
            include_finished: Include today's completed matches. Past days always use results.
            now: Optional aware clock for deterministic checks.

        Returns:
            Matches, coverage, source notes and any partial failures.
        """
        if not isinstance(game, str) or game not in GAMES:
            raise ValueError("游戏需为cs2、valorant或lol")
        if type(days) is not int or not 1 <= days <= 14:
            raise ValueError("查询范围需为1至14天")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("每次返回1至20场比赛")
        if type(include_finished) is not bool:
            raise ValueError("include_finished需为布尔值")
        if any(not isinstance(v, str) or len(v) > 100 for v in (tournament, team)):
            raise ValueError("赛事和战队关键词需为不超过100字的文字")
        now = now or datetime.now(BEIJING)
        today = now.astimezone(BEIJING).date()
        if not isinstance(date, str) or (
            date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
        ):
            raise ValueError("日期需为YYYY-MM-DD，按北京时间理解")
        start = Date.fromisoformat(date) if date else today
        end = start + timedelta(days=days - 1)
        jobs = []
        for offset in range(days):
            day = start + timedelta(days=offset)
            statuses = ["finished"] if day < today else ["upcoming"]
            if day == today:
                statuses.append("live")
                if include_finished:
                    statuses.append("finished")
            jobs.extend((day.isoformat(), status) for status in statuses)

        async def fetch(day, status):
            try:
                return normalize(await self._fetch(game, day, status), game, day), None
            except Exception as error:
                return [], f"{day} {status}: {type(error).__name__}"

        batches = None
        source = "Bo3公开赛程"
        source_note = (
            "本工具数据来自Bo3，尚未与偏好站点核对；需要核对时调用现有联网工具。"
        )
        # shortcut: the user's official link selects Worlds 2026; update the event id when their preferred season changes.
        if (
            game == "lol"
            and start.year == 2026
            and "worlds" in words(tournament)
            and not any(
                re.fullmatch(r"20\d{2}", word) and word != "2026"
                for word in words(tournament)
            )
        ):
            try:
                official = normalize_lpl(
                    await self._get(
                        "https://lpl.qq.com/web201612/data/LOL_MATCH2_MATCH_HOMEPAGE_BMATCH_LIST_246.js"
                    )
                )
                official = [
                    row
                    for row in official
                    if row["date"] < today.isoformat()
                    or include_finished
                    or row["status"] != "已结束"
                ]
                batches = [(official, None)]
                source = "LPL官方赛程"
                source_note = (
                    "直接读取用户提供的LPL页面对应的2026全球总决赛公开赛程数据。"
                )
            except Exception as error:
                source_note = f"LPL官方读取失败（{type(error).__name__}），已改用Bo3，尚未与官方核对。"
        if batches is None:
            batches = await asyncio.gather(*(fetch(*job) for job in jobs))
        errors = [error for _, error in batches if error]
        unique = {}
        for batch, _ in batches:
            for row in batch:
                if start.isoformat() <= row["date"] <= end.isoformat():
                    unique[row["id"]] = row
        selected = select_matches(list(unique.values()), game, tournament, team)
        selected.sort(key=lambda row: (row["date"], row["time"], row["id"]))
        return {
            "game": game,
            "timezone": "Asia/Shanghai",
            "range": [start.isoformat(), end.isoformat()],
            "queried_at": now.astimezone(BEIJING).isoformat(timespec="seconds"),
            "source": source,
            "preferred_source": PREFERRED[game],
            "source_note": source_note,
            "default_scope": "VCT CN及国际主赛事"
            if game == "valorant" and not tournament
            else "按查询条件",
            "complete": not errors,
            "errors": errors,
            "total": len(selected),
            "truncated": len(selected) > limit,
            "matches": selected[:limit],
        }
