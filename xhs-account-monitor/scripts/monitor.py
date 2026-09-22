#!/usr/bin/env python3
"""小红书账号持续监控。

镜像 douyin-account-monitor 的架构（accounts/snapshots/notes/comments 四表 + 巡查判新），
但有三处**不能照搬**，是小红书特有的机制差异，改代码前务必先读：

  ┌────────────────┬──────────────────────────┬──────────────────────────────┐
  │ 维度           │ 抖音                      │ 小红书（本脚本的取舍）        │
  ├────────────────┼──────────────────────────┼──────────────────────────────┤
  │ 笔记标识       │ aweme_id 永久有效         │ feed_id + xsec_token，token   │
  │                │ 可随时 detail 补抓        │ 是列表派生的临时令牌会过期     │
  │                │                          │ → 详情必须在同轮内立刻抓       │
  ├────────────────┼──────────────────────────┼──────────────────────────────┤
  │ 主页卡片指标   │ 带点赞数，可批量 backfill │ 只有 标题/封面/id/token       │
  │                │                          │ → 建基线只能逐个开详情页       │
  ├────────────────┼──────────────────────────┼──────────────────────────────┤
  │ 作品总数       │ aweme_count 可算增量      │ 主页无笔记总数                 │
  │                │ = 最有效的防误报防线      │ → 换成「头部位置约束」         │
  └────────────────┴──────────────────────────┴──────────────────────────────┘

取数能力复用同仓库的 xhs-account-data 技能（CDP 驱动已登录 Chrome），
登录态 profile 由两个技能共享，扫码一次即可。

用法：
    monitor.py probe <链接|user_id>      # 首次自检：主页到底暴露了什么字段
    monitor.py add <链接|分享口令>        # 纳入监控 + 建基线
    monitor.py run [user_id]             # 巡查（含同轮详情抓取）
    monitor.py list                      # 监控名单 + 最新快照
    monitor.py report <user_id>          # 该账号历史趋势
    monitor.py notes <user_id> [N]       # 笔记排行（含相对常态倍数）
    monitor.py detail <note_id>          # 补抓单条（会先回主页刷新 token）
    monitor.py backfill [user_id]        # 建/重建点赞基线
    monitor.py matrix <user_id> [N]      # 结构参数拆解（模仿用的安全产物）
    monitor.py opportunities             # 跨账号选题机会汇总
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import statistics
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# 路径与环境
# ---------------------------------------------------------------------------

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_ROOT = os.path.dirname(SKILL_DIR)
DATA_DIR = os.path.join(SKILL_DIR, "data")
REPORT_DIR = os.path.join(DATA_DIR, "reports")
DB_PATH = os.path.join(DATA_DIR, "monitor.db")
PEER_SKILL = os.path.join(SKILLS_ROOT, "xhs-account-data")
SYNC_SCRIPT = os.path.join(PEER_SKILL, "scripts", "cdp_publish.py")

PYTHON = os.environ.get(
    "XHS_PYTHON",
    os.path.expanduser("~/.workbuddy/binaries/python/envs/default/bin/python"),
)
# 与 xhs-account-data 共用同一个 LOCALAPPDATA → Chrome profile 与登录态完全共享
RUNTIME_ROOT = os.environ.get(
    "XHS_RUNTIME_DIR", os.path.expanduser("~/.workbuddy/runtime/xhs-data")
)

CDP_TIMEOUT = 240

# ---------------------------------------------------------------------------
# 判新参数（小红书适配版）
# ---------------------------------------------------------------------------

# 头部位置窗口。主页按「置顶 + 最新发布」排序，真新笔记必然落在列表前部。
# 深部才冒出来的「新 ID」= 基线未采全的历史笔记，直接压制不报警。
# 这是对抖音「作品总数硬约束」的等价替代（小红书主页拿不到笔记总数）。
# ⚠️ 取舍：若某账号在两轮巡查之间发布超过 HEAD_WINDOW 条，超出的会被判为深部而压制。
#    高频刷屏号（内容农场）会出现这种情况 —— 但它不是本技能的监控目标，
#    用 `run --head-window N` 按账号放宽即可，不要为了它把默认值调大。
HEAD_WINDOW = 8

# 单轮最多抓几条详情。**只限抓详情，不限入队** ——
# 入队便宜（只写一行），抓详情贵（一次页面加载 + 可选评论滚动）。
# 超额的部分保持 notified=0 留到下轮，绝不丢弃（对齐抖音坑 14）：
# 一旦在这里写死压制，那条真新笔记就永远报不出来。
MAX_DETAIL_PER_RUN = 10

# 详情页拿到的发布时间若早于今天 N 天 → 判为误入的历史笔记（对齐抖音坑 21）
STALE_DAYS = 7

# 主页默认翻页深度
DEFAULT_LIMIT = 40
DEFAULT_SCROLLS = 6

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id       TEXT PRIMARY KEY,
    nickname      TEXT,
    red_id        TEXT,            -- 小红书号（主页可见）
    desc          TEXT,            -- 签名 / 简介
    followers     INTEGER,
    following     INTEGER,
    liked         INTEGER,         -- 获赞与收藏
    note_count    INTEGER,         -- 主页若暴露则写入，否则 NULL（见 run 的判新注释）
    baseline_likes REAL,           -- 点赞中位数，判爆款的参照系
    baselined     INTEGER DEFAULT 0,
    first_seen    TEXT,
    updated_at    TEXT,
    active        INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    followers    INTEGER,
    following    INTEGER,
    liked        INTEGER,
    note_count   INTEGER,
    ok           INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_snap_user ON snapshots(user_id, captured_at);

CREATE TABLE IF NOT EXISTS notes (
    note_id       TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    title         TEXT,
    cover         TEXT,
    note_url      TEXT,
    xsec_token    TEXT,
    token_at      TEXT,            -- token 获取时间（会过期，用于判断能否复用）
    first_seen    TEXT,
    seen_count    INTEGER DEFAULT 1,
    notified      INTEGER DEFAULT 0,
    discover_run  TEXT,
    suppressed    TEXT,            -- 压制原因，便于追溯
    -- 详情字段（同轮抓取或 detail 补抓）
    likes         INTEGER,
    collects      INTEGER,
    comments_cnt  INTEGER,
    shares        INTEGER,
    publish_time  TEXT,
    content       TEXT,
    tags          TEXT,
    note_type     TEXT,
    detail_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_note_user ON notes(user_id, publish_time);
CREATE INDEX IF NOT EXISTS idx_note_queue ON notes(seen_count, notified);

CREATE TABLE IF NOT EXISTS comments (
    note_id     TEXT NOT NULL,
    content     TEXT NOT NULL,
    author      TEXT,
    liked_cnt   INTEGER,
    captured_at TEXT,
    PRIMARY KEY (note_id, content)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    summary     TEXT
);
"""


def now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def ts_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# CDP 调用层
# ---------------------------------------------------------------------------


class CDPFailure(RuntimeError):
    pass


def cdp(*args: str, marker: str | None = None) -> Any:
    """调用 xhs-account-data 的 cdp_publish.py，返回 marker 之后的 JSON。

    marker 为 None 时返回原始 stdout 文本。
    """
    cmd = [PYTHON, SYNC_SCRIPT, *args]
    env = dict(os.environ)
    env["LOCALAPPDATA"] = RUNTIME_ROOT  # 共用 profile
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=CDP_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise CDPFailure(f"CDP 调用超时（{CDP_TIMEOUT}s）：{' '.join(args)}") from exc

    out = proc.stdout or ""
    if "NOT_LOGGED_IN" in out:
        raise CDPFailure(
            "小红书未登录。请先执行：\n"
            f"  cd {PEER_SKILL}\n"
            f"  LOCALAPPDATA={RUNTIME_ROOT} {PYTHON} scripts/chrome_launcher.py\n"
            f"  LOCALAPPDATA={RUNTIME_ROOT} {PYTHON} scripts/cdp_publish.py login"
        )

    if marker:
        if marker not in out:
            raise CDPFailure(
                f"未拿到 {marker}。returncode={proc.returncode}\n"
                f"--- stdout ---\n{out[-2000:]}\n--- stderr ---\n{(proc.stderr or '')[-1500:]}"
            )
        raw = out.split(marker, 1)[1].strip()
        # 截到第一个完整 JSON（后面可能还有日志行）
        depth, start = 0, None
        for i, ch in enumerate(raw):
            if ch in "{[":
                if start is None:
                    start = i
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0 and start is not None:
                    raw = raw[start : i + 1]
                    break
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CDPFailure(f"{marker} 返回非合法 JSON：{exc}\n{raw[:800]}") from exc

    if proc.returncode != 0:
        raise CDPFailure(
            f"CDP 调用失败 rc={proc.returncode}：{' '.join(args)}\n"
            f"{out[-1500:]}\n{(proc.stderr or '')[-1000:]}"
        )
    return out


# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------


def parse_count(value: Any) -> int | None:
    """'1.2万' -> 12000；'1234' -> 1234；'粉丝 1.2万' -> 12000；'-' -> None

    注意「前缀文本」这种形态：小红书的统计区文本常是「粉丝 1.2万」这种
    标签在前、数值在后的写法，所以**不能要求数字出现在开头**，
    但单位必须在数字紧邻之后（否则 '1 万' 之外的脏串会误判）。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    if text in ("", "-", "--", "null", "None"):
        return None

    # 数值 + 可选单位，允许数值前有任意非数字前缀
    m = re.search(r"(\d+(?:\.\d+)?)\s*([万亿wW])?", text)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("万", "w"):
        num *= 10_000
    elif unit == "亿":
        num *= 100_000_000
    return int(num)


def extract_user_id(text: str) -> str | None:
    """从主页链接里取 24 位 user_id。"""
    m = re.search(r"/user/profile/([0-9a-fA-F]{24})", text or "")
    return m.group(1) if m else None


def extract_note_id(text: str) -> str | None:
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-fA-F]{24})", text or "")
    return m.group(1) if m else None


def resolve_target(target: str) -> tuple[str | None, str | None]:
    """把用户给的东西解析成 (user_id, note_id)。

    支持：主页链接、笔记链接、xhslink 短链、App 分享口令。
    """
    text = (target or "").strip()
    uid = extract_user_id(text)
    nid = extract_note_id(text)
    if uid or nid:
        return uid, nid

    # 分享口令里的 http 链接 / 裸 xhslink 域名
    m = re.search(r"https?://[^\s，,、）)】\]]+", text)
    url = m.group(0) if m else (text if text.startswith("http") else None)
    if not url:
        return None, None

    if "xhslink.com" in url or "xhs.cn" in url:
        url = _expand_short_link(url)
        if url:
            return extract_user_id(url), extract_note_id(url)
    return None, None


def _expand_short_link(url: str) -> str | None:
    """跟随 xhslink 短链重定向，拿到真实 URL。"""
    try:
        import requests
    except ImportError:
        print("⚠️ 未安装 requests，无法展开短链", file=sys.stderr)
        return None
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": UA},
            allow_redirects=True,
            timeout=15,
        )
        return resp.url
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 短链展开失败：{exc}", file=sys.stderr)
        return None


def _is_stale(publish_time: str | None) -> bool:
    """发布时间是否远早于今天 → 说明这条不是真新笔记，而是误入的历史笔记。

    对齐抖音坑 21：主页滚动加载每次返回的集合不固定，老笔记会被顶到前面。
    小红书更常见（置顶 + 推荐位混排），所以这道复核必须有。
    """
    if not publish_time:
        return False  # 拿不到时间就不判，宁可放过也不要误杀真新笔记
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", publish_time.strip())
    if not m:
        return False
    try:
        pub = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return (datetime.now() - pub).days > STALE_DAYS


def _dig(obj: Any, keys: tuple[str, ...], max_nodes: int = 3000) -> Any:
    """在嵌套结构里按 key 名广度优先找第一个非空值。

    小红书 __INITIAL_STATE__ 的结构随版本变动，硬编码路径很容易失效，
    所以统一用「按 key 名找」而不是「按路径取」。
    """
    queue: list[Any] = [obj]
    seen: set[int] = set()
    scanned = 0
    while queue and scanned < max_nodes:
        scanned += 1
        node = queue.pop(0)
        if not isinstance(node, dict):
            if isinstance(node, list):
                queue.extend(x for x in node if isinstance(x, (dict, list)))
            continue
        node_id = id(node)
        if node_id in seen:
            continue
        seen.add(node_id)
        for key in keys:
            val = node.get(key)
            if val is not None and val != "" and val != []:
                return val
        for val in node.values():
            if isinstance(val, (dict, list)):
                queue.append(val)
    return None


def parse_note_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """从 noteDetailMap 条目里提取字段。

    interactInfo 的计数是字符串（可能带「万」），发布时间是毫秒时间戳。
    用 _dig 做保底，避免小红书改版后整条抓空。
    """
    note = detail.get("note") if isinstance(detail.get("note"), dict) else detail

    interact = note.get("interactInfo") if isinstance(note, dict) else None
    if not isinstance(interact, dict):
        interact = {}

    def metric(*keys: str) -> int | None:
        for key in keys:
            if key in interact:
                v = parse_count(interact.get(key))
                if v is not None:
                    return v
        raw = _dig(note, keys)
        return parse_count(raw)

    raw_time = None
    for key in ("time", "publishTime", "createTime", "lastUpdateTime"):
        if isinstance(note, dict) and note.get(key):
            raw_time = note.get(key)
            break
    if raw_time is None:
        raw_time = _dig(note, ("publishTime", "createTime"))

    publish_time = None
    if isinstance(raw_time, (int, float)) or (
        isinstance(raw_time, str) and raw_time.isdigit()
    ):
        secs = float(raw_time)
        if secs > 1e11:  # 毫秒
            secs /= 1000.0
        try:
            publish_time = datetime.fromtimestamp(secs).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            publish_time = None
    elif isinstance(raw_time, str):
        publish_time = raw_time.strip() or None

    tags: list[str] = []
    raw_tags = _dig(note, ("tagList", "tags"))
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title")
                if name:
                    tags.append(str(name).strip())
            elif isinstance(item, str):
                tags.append(item.strip())

    user = note.get("user") if isinstance(note, dict) else None
    if not isinstance(user, dict):
        user = {}

    return {
        "note_id": (note.get("noteId") or note.get("id") or "") or None,
        "title": (note.get("title") or "").strip() or None,
        "content": (note.get("desc") or note.get("content") or "").strip() or None,
        "likes": metric("likedCount", "likeCount", "likes"),
        "collects": metric("collectedCount", "collectCount", "collects"),
        "comments_cnt": metric("commentCount", "commentsCount"),
        "shares": metric("shareCount", "sharedCount", "shares"),
        "publish_time": publish_time,
        "author": (user.get("nickname") or "").strip() or None,
        "tags": ",".join(tags) if tags else None,
        "note_type": (note.get("type") or "").strip() or None,
    }


def extract_comments(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """从详情 payload 里抽一级评论。"""
    raw = _dig(detail, ("comments",))
    if isinstance(raw, dict):
        raw = raw.get("list") or []
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if not content:
            continue
        author = ""
        user = item.get("userInfo") or item.get("user")
        if isinstance(user, dict):
            author = (user.get("nickname") or user.get("nickName") or "").strip()
        out.append(
            {
                "content": content.replace("\n", " ")[:500],
                "author": author or None,
                "liked_cnt": parse_count(item.get("likeCount") or item.get("likedCount")),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 取数原语
# ---------------------------------------------------------------------------


def snapshot_profile(user_id: str) -> dict[str, Any]:
    return cdp(
        "profile-snapshot",
        "--user-id",
        user_id,
        marker="PROFILE_SNAPSHOT_RESULT:",
    )


def list_notes(user_id: str, limit: int, scrolls: int) -> list[dict[str, Any]]:
    payload = cdp(
        "notes-from-profile",
        "--user-id",
        user_id,
        "--limit",
        str(limit),
        "--max-scrolls",
        str(scrolls),
        marker="PROFILE_NOTES_RESULT:",
    )
    notes = payload.get("notes") if isinstance(payload, dict) else None
    return notes if isinstance(notes, list) else []


def fetch_detail(note_id: str, xsec_token: str, with_comments: bool = False) -> dict[str, Any]:
    args = ["get-feed-detail", "--feed-id", note_id, "--xsec-token", xsec_token]
    if with_comments:
        args += ["--load-all-comments", "--limit", "20"]
    payload = cdp(*args, marker="FEED_DETAIL_RESULT:")
    return payload.get("detail") if isinstance(payload, dict) else payload


def refresh_token(user_id: str, note_id: str, limit: int = DEFAULT_LIMIT) -> str | None:
    """token 会过期。补抓单条时回主页重新找该笔记的最新 token。"""
    try:
        for note in list_notes(user_id, limit=limit, scrolls=DEFAULT_SCROLLS):
            if note.get("id") == note_id:
                tok = note.get("xsec_token")
                return tok if tok else None
    except CDPFailure as exc:
        print(f"⚠️ 刷新 token 失败：{exc}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# 写库
# ---------------------------------------------------------------------------


def upsert_account(conn: sqlite3.Connection, user_id: str, profile: dict[str, Any]) -> None:
    p = profile.get("profile") if isinstance(profile.get("profile"), dict) else profile
    followers = parse_count(p.get("followers"))
    following = parse_count(p.get("following"))
    liked = parse_count(p.get("liked"))

    # 笔记总数：小红书主页 header 只暴露 关注/粉丝/获赞与收藏，
    # 没有笔记总数。这里做一次尝试（若某天版本加了就能自动用上），
    # 拿不到就写 NULL —— 判新逻辑绝不能依赖它。
    note_count = parse_count(_dig(profile, ("noteCount", "note_count", "notesCount")))

    existing = conn.execute(
        "SELECT user_id, baselined FROM accounts WHERE user_id = ?", (user_id,)
    ).fetchone()

    if existing is None:
        conn.execute(
            """INSERT INTO accounts
               (user_id, nickname, red_id, desc, followers, following, liked,
                note_count, baselined, first_seen, updated_at, active)
               VALUES (?,?,?,?,?,?,?,?,0,?,?,1)""",
            (
                user_id,
                p.get("nickname"),
                p.get("redId") or p.get("red_id"),
                p.get("desc"),
                followers,
                following,
                liked,
                note_count,
                now(),
                now(),
            ),
        )
    else:
        conn.execute(
            """UPDATE accounts SET nickname=COALESCE(?,nickname),
                   desc=COALESCE(?,desc), followers=?, following=?, liked=?,
                   note_count=?, updated_at=? WHERE user_id=?""",
            (
                p.get("nickname"),
                p.get("desc"),
                followers,
                following,
                liked,
                note_count,
                now(),
                user_id,
            ),
        )
    conn.commit()


def write_snapshot(
    conn: sqlite3.Connection, user_id: str, profile: dict[str, Any], ok: bool = True
) -> None:
    p = profile.get("profile") if isinstance(profile.get("profile"), dict) else profile
    conn.execute(
        """INSERT INTO snapshots
           (user_id, captured_at, followers, following, liked, note_count, ok)
           VALUES (?,?,?,?,?,?,?)""",
        (
            user_id,
            now(),
            parse_count(p.get("followers")),
            parse_count(p.get("following")),
            parse_count(p.get("liked")),
            parse_count(_dig(profile, ("noteCount", "note_count"))),
            1 if ok else 0,
        ),
    )
    conn.commit()


def write_detail(conn: sqlite3.Connection, note_id: str, detail: dict[str, Any]) -> bool:
    """写详情。用 COALESCE 保护已知值，绝不用 None 覆盖（对齐抖音坑 10）。"""
    info = parse_note_detail(detail)
    conn.execute(
        """UPDATE notes SET
             likes        = COALESCE(?, likes),
             collects     = COALESCE(?, collects),
             comments_cnt = COALESCE(?, comments_cnt),
             shares       = COALESCE(?, shares),
             publish_time = COALESCE(NULLIF(?,''), publish_time),
             content      = COALESCE(NULLIF(?,''), content),
             tags         = COALESCE(NULLIF(?,''), tags),
             note_type    = COALESCE(NULLIF(?,''), note_type),
             detail_at    = ?
           WHERE note_id = ?""",
        (
            info["likes"],
            info["collects"],
            info["comments_cnt"],
            info["shares"],
            info["publish_time"],
            info["content"],
            info["tags"],
            info["note_type"],
            now(),
            note_id,
        ),
    )
    conn.commit()

    comments = extract_comments(detail)
    for c in comments:
        conn.execute(
            """INSERT OR IGNORE INTO comments
               (note_id, content, author, liked_cnt, captured_at) VALUES (?,?,?,?,?)""",
            (note_id, c["content"], c["author"], c["liked_cnt"], now()),
        )
    if comments:
        conn.commit()
    return bool(info["likes"] is not None or info["publish_time"])


def recompute_baseline(conn: sqlite3.Connection, user_id: str) -> float | None:
    """点赞中位数作为「常态」参照系（对齐抖音 backfill 的 baseline_digg）。"""
    rows = conn.execute(
        "SELECT likes FROM notes WHERE user_id=? AND likes IS NOT NULL", (user_id,)
    ).fetchall()
    vals = [r["likes"] for r in rows if r["likes"] is not None]
    if not vals:
        conn.execute(
            "UPDATE accounts SET baseline_likes=NULL, baselined=1 WHERE user_id=?",
            (user_id,),
        )
        conn.commit()
        return None
    med = float(statistics.median(vals))
    conn.execute(
        "UPDATE accounts SET baseline_likes=?, baselined=1 WHERE user_id=?",
        (med, user_id),
    )
    conn.commit()
    return med


# ---------------------------------------------------------------------------
# 命令：probe —— 首次自检，回答「主页到底暴露了什么」
# ---------------------------------------------------------------------------


def cmd_probe(args: argparse.Namespace) -> int:
    uid, _ = resolve_target(args.target)
    if not uid:
        uid = args.target.strip() if re.fullmatch(r"[0-9a-fA-F]{24}", args.target.strip()) else None
    if not uid:
        print("❌ 无法从输入解析出 user_id", file=sys.stderr)
        return 1

    print(f"user_id = {uid}")
    print()
    snap = snapshot_profile(uid)
    print("=== profile-snapshot 原始返回 ===")
    print(json.dumps(snap, ensure_ascii=False, indent=2))

    p = snap.get("profile") if isinstance(snap.get("profile"), dict) else snap
    print()
    print("=== 关键问题：主页有没有「笔记总数」？ ===")
    nc = _dig(snap, ("noteCount", "note_count", "notesCount"))
    if nc is None:
        print("❌ 没有。判新逻辑不得依赖作品总数增量 → 本技能用「头部位置约束」替代。")
    else:
        print(f"✅ 有：{nc}（若稳定可考虑启用增量校验作为额外防线）")

    print()
    print("=== dom_stat_texts（主页统计区文本，看是否有笔记数） ===")
    print(json.dumps(snap.get("dom_stat_texts"), ensure_ascii=False))

    print()
    notes = list_notes(uid, limit=DEFAULT_LIMIT, scrolls=DEFAULT_SCROLLS)
    print(f"=== 主页笔记列表：拿到 {len(notes)} 条 ===")
    for i, n in enumerate(notes[:HEAD_WINDOW + 2]):
        title = (n.get("title") or "")[:36]
        tok = "有token" if n.get("xsec_token") else "无token"
        print(f"  [{i:>2}] {n.get('id')} {tok}  {title}")
    if notes:
        print()
        print("=== 单条卡片字段（确认有没有指标） ===")
        print(json.dumps(notes[0], ensure_ascii=False, indent=2))
        has_metric = any(
            k in notes[0] for k in ("likes", "likedCount", "likeCount", "digg")
        )
        if not has_metric:
            print()
            print("❌ 卡片无指标 → 不能像抖音那样批量 backfill，建基线必须逐个开详情页。")
    return 0


# ---------------------------------------------------------------------------
# 命令：add
# ---------------------------------------------------------------------------


def cmd_add(args: argparse.Namespace) -> int:
    uid, note_id = resolve_target(args.target)
    if not uid and note_id:
        # 只给了笔记链接：先开详情拿到作者 user_id
        print("· 输入是笔记链接，先解析作者…")
        tok = None
        m = re.search(r"xsec_token=([^&\s]+)", args.target)
        if m:
            tok = m.group(1)
        if not tok:
            print("❌ 笔记链接缺 xsec_token，请改用账号主页链接或分享口令", file=sys.stderr)
            return 1
        detail = fetch_detail(note_id, tok)
        uid = _dig(detail, ("userId", "user_id"))
        if not uid:
            print("❌ 未能从笔记详情取到作者 user_id", file=sys.stderr)
            return 1

    if not uid:
        print("❌ 无法解析出 user_id（支持主页链接 / 分享口令 / xhslink 短链）", file=sys.stderr)
        return 1

    conn = connect()
    print(f"· 解析到 user_id = {uid}")

    profile = snapshot_profile(uid)
    upsert_account(conn, uid, profile)
    p = profile.get("profile") if isinstance(profile.get("profile"), dict) else profile
    print(
        f"· 账号：{p.get('nickname')}  "
        f"粉丝 {parse_count(p.get('followers'))}  获赞与收藏 {parse_count(p.get('liked'))}"
    )
    write_snapshot(conn, uid, profile)

    notes = list_notes(uid, limit=DEFAULT_LIMIT, scrolls=DEFAULT_SCROLLS)
    print(f"· 主页可见笔记 {len(notes)} 条")

    run_id = f"add_{ts_id()}"
    for idx, n in enumerate(notes):
        nid = n.get("id")
        if not nid:
            continue
        # 基线轮：全部标记为已见已报（notified=1），永不报警
        conn.execute(
            """INSERT OR IGNORE INTO notes
               (note_id, user_id, title, cover, note_url, xsec_token, token_at,
                first_seen, seen_count, notified, discover_run, suppressed)
               VALUES (?,?,?,?,?,?,?,?,2,1,?, 'baseline')""",
            (
                nid,
                uid,
                (n.get("title") or "").strip() or None,
                n.get("cover"),
                n.get("note_url"),
                n.get("xsec_token"),
                now(),
                now(),
                run_id,
            ),
        )
    conn.commit()

    print()
    print("· 建点赞基线（需逐个打开详情页；此时 token 新鲜，是本轮独有的机会窗口）…")
    rows = conn.execute(
        "SELECT note_id, xsec_token FROM notes WHERE user_id=? AND likes IS NULL",
        (uid,),
    ).fetchall()
    ok = 0
    for i, r in enumerate(rows):
        try:
            detail = fetch_detail(r["note_id"], r["xsec_token"] or "")
            if write_detail(conn, r["note_id"], detail):
                ok += 1
            print(f"  [{i+1}/{len(rows)}] {r['note_id']} ok")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i+1}/{len(rows)}] {r['note_id']} 失败：{str(exc)[:80]}")

    med = recompute_baseline(conn, uid)
    conn.execute(
        "UPDATE accounts SET baselined=1, updated_at=? WHERE user_id=?", (now(), uid)
    )
    conn.commit()
    conn.close()

    print()
    print(f"✅ 已纳入监控：{p.get('nickname')}（{uid}）")
    print(f"   基线笔记 {len(notes)} 条，补到详情 {ok} 条，点赞中位数 "
          f"{med if med is not None else 'NULL（无点赞数据）'}")
    return 0


# ---------------------------------------------------------------------------
# 命令：run —— 巡查 + 判新
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    conn = connect()
    if args.user_id:
        accounts = conn.execute(
            "SELECT * FROM accounts WHERE user_id=? AND active=1", (args.user_id,)
        ).fetchall()
    else:
        accounts = conn.execute("SELECT * FROM accounts WHERE active=1").fetchall()

    if not accounts:
        print("监控名单为空。先用 `monitor.py add <链接>` 添加账号。")
        return 0

    run_id = f"run_{ts_id()}"
    run_started = now()
    conn.execute(
        "INSERT OR REPLACE INTO runs (run_id, started_at) VALUES (?,?)",
        (run_id, run_started),
    )
    conn.commit()

    report_lines: list[str] = []
    total_new = 0

    for acc in accounts:
        uid = acc["user_id"]
        nick = acc["nickname"] or uid
        print(f"\n=== 巡查 {nick} ({uid}) ===")

        try:
            profile = snapshot_profile(uid)
        except CDPFailure as exc:
            print(f"  ❌ 抓主页失败，跳过：{str(exc)[:150]}")
            write_snapshot(conn, uid, {}, ok=False)
            continue

        prev = conn.execute(
            """SELECT followers FROM snapshots WHERE user_id=? AND ok=1
               ORDER BY captured_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        upsert_account(conn, uid, profile)
        write_snapshot(conn, uid, profile)

        p = profile.get("profile") if isinstance(profile.get("profile"), dict) else profile
        cur_fans = parse_count(p.get("followers"))
        d_fans = (
            (cur_fans - prev["followers"])
            if prev and prev["followers"] is not None and cur_fans is not None
            else None
        )
        print(
            f"  粉丝 {cur_fans}  变化 {d_fans if d_fans is not None else '?'}"
            f"  获赞与收藏 {parse_count(p.get('liked'))}"
        )

        try:
            listed = list_notes(uid, limit=args.limit, scrolls=args.scrolls)
        except CDPFailure as exc:
            print(f"  ❌ 抓笔记列表失败：{str(exc)[:150]}")
            continue

        try:
            ready, candidates = _judge_new(
                conn, uid, acc, listed, run_id, head_window=args.head_window
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ 判新失败：{exc}")
            continue

        # 抓详情有预算（贵），入队无预算（便宜）。超额部分保持 notified=0 留到下轮——
        # 绝不在这里写死压制，否则那条真新笔记永远报不出来（抖音坑 14）。
        todo = ready[:MAX_DETAIL_PER_RUN]
        deferred = len(ready) - len(todo)
        print(
            f"  列表 {len(listed)} 条 → 待确认 {len(candidates)} 条，"
            f"确认 {len(ready)} 条，本轮抓详情 {len(todo)} 条"
            + (f"（{deferred} 条顺延下轮）" if deferred > 0 else "")
        )

        # 同轮抓详情 —— token 是本轮刚拿到的，这是唯一可靠的窗口
        token_map = {n.get("id"): n.get("xsec_token") for n in listed}
        for nid in todo:
            # 优先用本轮列表刚拿的 token；欠账重试的笔记可能已不在当前列表里，
            # 退化用库里存的（可能已过期，失败后再回主页刷新）
            tok = token_map.get(nid)
            if not tok:
                r = conn.execute(
                    "SELECT user_id, xsec_token FROM notes WHERE note_id=?", (nid,)
                ).fetchone()
                if r and not r["xsec_token"]:
                    tok = refresh_token(r["user_id"], nid) or ""
                else:
                    tok = (r["xsec_token"] if r else "") or ""
            try:
                detail = fetch_detail(nid, tok, with_comments=not args.no_comments)
                write_detail(conn, nid, detail)
                row = conn.execute(
                    "SELECT title, likes, collects, comments_cnt, shares, publish_time "
                    "FROM notes WHERE note_id=?",
                    (nid,),
                ).fetchone()

                # —— 防线 2：freshness 复核 ——
                # 主页排序只保证「位置靠前」，不保证「真的新」。一条几个月前发布、
                # 此前没进过库的老笔记也可能被顶到前面（对齐抖音坑 21 的三次复发）。
                # 判据：发布时间远早于今天 → 判为误入，回写 suppressed 并从报告里撤下。
                if _is_stale(row["publish_time"]):
                    conn.execute(
                        "UPDATE notes SET notified=1, suppressed='stale_publish_time' "
                        "WHERE note_id=?",
                        (nid,),
                    )
                    conn.commit()
                    print(
                        f"    ⛔ 撤回：{(row['title'] or '')[:30]} 实为 "
                        f"{row['publish_time']} 发布（> {STALE_DAYS} 天）→ 判为误入历史笔记"
                    )
                    continue

                print(
                    f"    ✅ {(row['title'] or '')[:30]} | 赞 {row['likes']} "
                    f"藏 {row['collects']} 评 {row['comments_cnt']} 转 {row['shares']}"
                    f" | {row['publish_time']}"
                )
                report_lines.append(
                    f"- **{nick}** 新笔记「{row['title'] or '(无标题)'}」"
                    f" 赞 {row['likes']} / 藏 {row['collects']} / "
                    f"评 {row['comments_cnt']} / 转 {row['shares']}"
                    f"（{row['publish_time'] or '时间未知'}）"
                )
                # notified=1 表示「详情已抓到并已报告」，必须在成功之后才写
                conn.execute("UPDATE notes SET notified=1 WHERE note_id=?", (nid,))
                conn.commit()
                total_new += 1
            except Exception as exc:  # noqa: BLE001
                # 抓失败不写 notified → 下轮重试，不会永久漏掉
                print(f"    ❌ 详情抓取失败 {nid}（留到下轮重试）：{str(exc)[:100]}")

        # 每次巡查后重算基线，纳入新数据
        if not args.no_baseline:
            recompute_baseline(conn, uid)

    conn.execute(
        "UPDATE runs SET finished_at=?, summary=? WHERE run_id=?",
        (now(), json.dumps({"new_notes": total_new}, ensure_ascii=False), run_id),
    )
    conn.commit()
    conn.close()

    print()
    print("=" * 62)
    if report_lines:
        print(f"🆕 本轮放行 {total_new} 条新笔记：")
        for line in report_lines:
            print(line)
    else:
        print("本轮无新笔记放行。")
        print("⚠️ 这不代表没有新笔记 —— 首次出现的候选会进二次确认队列，")
        print("   要连续两轮都出现才放行；抓详情超预算的也会顺延。查队列：")
        print("   SELECT note_id,title FROM notes WHERE seen_count=1 AND notified=0;")
        print("   SELECT note_id,title FROM notes WHERE seen_count>=2 AND notified=0;")
    print("=" * 62)
    return 0


def _judge_new(
    conn: sqlite3.Connection,
    uid: str,
    acc: sqlite3.Row,
    listed: list[dict[str, Any]],
    run_id: str,
    head_window: int = HEAD_WINDOW,
) -> tuple[list[str], list[str]]:
    """判新。返回 (ready, candidates)。

    ready     —— 已通过二次确认、可以抓详情的笔记（seen_count>=2 且 notified=0）
    candidates—— 本轮刚进队列、还没确认的笔记（seen_count=1 且 notified=0）

    三道防线，缺一不可。改动前务必读完注释。

    防线 0（小红书独有）：头部位置约束
        ⚠️ 抖音用 `expected_new = 当前作品数 - 上次作品数` 硬约束，效果最好；
        但**小红书主页没有笔记总数**（`probe` 命令可现场确认），
        所以改用「位置」作为代理信号：主页按「置顶 + 最新发布」排序，
        真新笔记必然落在前 head_window 位；出现在深部的「新 ID」
        是基线没采全的历史笔记，直接压制不报警。

    防线 1：二次确认
        新 ID 首次出现只写 seen_count=1（入队），不报警；
        下一轮列表里仍在 → 提到 seen_count=2，才算确认。

    防线 2：详情页发布时间复核（在 cmd_run 里做，需要拿到 publish_time）
        发布时间早于今天 STALE_DAYS 天 → 判为误入的历史笔记，回写 suppressed。

    ⚠️ 不要在这里加「配额」把入队卡住。入队是廉价的，且一旦压制就不可逆
    （笔记已进 DB → 下轮不再是 fresh → 永远报不出来，即抖音坑 14）。
    要控成本就控抓详情，用 MAX_DETAIL_PER_RUN，超额的自然留到下轮。
    """
    known = {
        r["note_id"]
        for r in conn.execute("SELECT note_id FROM notes WHERE user_id=?", (uid,)).fetchall()
    }
    pending = {
        r["note_id"]
        for r in conn.execute(
            "SELECT note_id FROM notes WHERE user_id=? AND seen_count=1 AND notified=0",
            (uid,),
        ).fetchall()
    }

    baselined = bool(acc["baselined"])
    ready: list[str] = []
    candidates: list[str] = []

    # —— 二次确认（上轮入队的候选本轮仍在 → 确认）——
    # 注意：这里只把 seen_count 提到 2，**不写 notified=1**。
    # notified=1 表示「详情已抓到并已报告」，由 cmd_run 在成功抓完之后写。
    # 写早了会在详情抓取失败时造成永久漏报。
    for n in listed:
        nid = n.get("id")
        if nid and nid in pending:
            conn.execute(
                "UPDATE notes SET seen_count=2, xsec_token=?, token_at=? WHERE note_id=?",
                (n.get("xsec_token"), now(), nid),
            )
            ready.append(nid)
    conn.commit()

    # —— 欠账重试 ——
    # 已确认（seen_count>=2）但 notified 仍为 0 的，说明上一轮详情没抓成功。
    # 必须在本轮重新带出来，否则它们再也不会回到 pending（seen_count 已不是 1），
    # 永久卡在未报告状态 —— 这正是抖音坑 14「配额烧掉即永久压制」的同一类错误。
    backlog = [
        r["note_id"]
        for r in conn.execute(
            """SELECT note_id FROM notes
               WHERE user_id=? AND seen_count>=2 AND notified=0
               ORDER BY first_seen""",
            (uid,),
        ).fetchall()
    ] if baselined else []
    for nid in backlog:
        if nid not in ready:
            ready.append(nid)

    # —— 首次出现的新 ID ——
    existing_ids = known | pending | set(ready)
    for idx, n in enumerate(listed):
        nid = n.get("id")
        if not nid or nid in existing_ids:
            continue

        row = (
            nid,
            uid,
            (n.get("title") or "").strip() or None,
            n.get("cover"),
            n.get("note_url"),
            n.get("xsec_token"),
            now(),
            now(),
            run_id,
        )

        if not baselined:
            # 首轮巡查：只建基线，绝不报警
            conn.execute(
                """INSERT OR IGNORE INTO notes
                   (note_id,user_id,title,cover,note_url,xsec_token,token_at,
                    first_seen,seen_count,notified,discover_run,suppressed)
                   VALUES (?,?,?,?,?,?,?,?,2,1,?,'baseline')""",
                row,
            )
        elif idx >= head_window:
            # 防线 0：深部新 ID = 基线漏录的历史笔记 → 压制
            conn.execute(
                """INSERT OR IGNORE INTO notes
                   (note_id,user_id,title,cover,note_url,xsec_token,token_at,
                    first_seen,seen_count,notified,discover_run,suppressed)
                   VALUES (?,?,?,?,?,?,?,?,2,1,?,'deep_position')""",
                row,
            )
        else:
            # 头部窗口内的新 ID → 入队等二次确认
            cur = conn.execute(
                """INSERT OR IGNORE INTO notes
                   (note_id,user_id,title,cover,note_url,xsec_token,token_at,
                    first_seen,seen_count,notified,discover_run,suppressed)
                   VALUES (?,?,?,?,?,?,?,?,1,0,?,NULL)""",
                row,
            )
            if (cur.rowcount or 0) > 0:
                candidates.append(nid)

    conn.commit()

    if not baselined:
        conn.execute("UPDATE accounts SET baselined=1 WHERE user_id=?", (uid,))
        conn.commit()

    return ready, candidates


# ---------------------------------------------------------------------------
# 命令：list / report / notes / detail / backfill
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    conn = connect()
    rows = conn.execute(
        """SELECT a.user_id, a.nickname, a.followers, a.liked, a.baseline_likes,
                  a.baselined,
                  (SELECT COUNT(*) FROM notes n WHERE n.user_id=a.user_id) AS notes,
                  (SELECT captured_at FROM snapshots s
                    WHERE s.user_id=a.user_id AND s.ok=1
                    ORDER BY captured_at DESC LIMIT 1) AS last_at,
                  (SELECT followers FROM snapshots s
                    WHERE s.user_id=a.user_id AND s.ok=1
                    ORDER BY captured_at DESC LIMIT 1) AS last_fans,
                  (SELECT followers FROM snapshots s
                    WHERE s.user_id=a.user_id AND s.ok=1
                    ORDER BY captured_at DESC LIMIT 1 OFFSET 1) AS prev_fans,
                  (SELECT COUNT(*) FROM notes n
                    WHERE n.user_id=a.user_id AND n.seen_count=1 AND n.notified=0
                  ) AS queue
           FROM accounts a WHERE a.active=1 ORDER BY a.followers DESC"""
    ).fetchall()
    conn.close()

    if not rows:
        print("监控名单为空。")
        return 0

    print(f"{'昵称':<22} {'粉丝':>8} {'变化':>8} {'笔记':>5} {'中位赞':>8} {'待确认':>6}  最近巡查")
    print("-" * 88)
    for r in rows:
        d = (
            r["last_fans"] - r["prev_fans"]
            if r["last_fans"] is not None and r["prev_fans"] is not None
            else None
        )
        med = f"{r['baseline_likes']:.0f}" if r["baseline_likes"] is not None else "NULL"
        print(
            f"{(r['nickname'] or '')[:20]:<22} "
            f"{r['followers'] if r['followers'] is not None else '?':>8} "
            f"{d if d is not None else '?':>8} "
            f"{r['notes']:>5} {med:>8} {r['queue']:>6}  {r['last_at'] or '未巡查'}"
        )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM snapshots WHERE user_id=? AND ok=1
           ORDER BY captured_at""",
        (args.user_id,),
    ).fetchall()
    acc = conn.execute(
        "SELECT * FROM accounts WHERE user_id=?", (args.user_id,)
    ).fetchone()
    conn.close()

    if not rows:
        print("无快照数据。先跑 `monitor.py run`。")
        return 0

    print(f"# 账号趋势：{acc['nickname'] if acc else args.user_id} ({args.user_id})")
    print()
    print(f"监控起始：{rows[0]['captured_at']}　快照数：{len(rows)}")
    print()
    print("| 时间 | 粉丝 | 变化 | 获赞与收藏 |")
    print("|---|---|---|---|")
    for i, r in enumerate(rows):
        prev = rows[i - 1] if i > 0 else None
        d = (
            r["followers"] - prev["followers"]
            if prev and prev["followers"] is not None and r["followers"] is not None
            else None
        )
        print(
            f"| {r['captured_at']} | {r['followers']} | "
            f"{d if d is not None else '-'} | {r['liked']} |"
        )
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    conn = connect()
    acc = conn.execute(
        "SELECT * FROM accounts WHERE user_id=?", (args.user_id,)
    ).fetchone()
    rows = conn.execute(
        """SELECT * FROM notes WHERE user_id=? AND likes IS NOT NULL
           ORDER BY likes DESC LIMIT ?""",
        (args.user_id, args.n),
    ).fetchall()
    conn.close()

    if not rows:
        print("该账号还没有带点赞数据的笔记。先跑 `monitor.py backfill`。")
        return 0

    med = acc["baseline_likes"] if acc else None
    print(f"# 笔记排行：{acc['nickname'] if acc else args.user_id}")
    print()
    print(f"点赞中位数（常态基线）：{med if med is not None else 'NULL'}")
    print()
    print("| 标题 | 赞 | 倍数 | 藏 | 评 | 转 | 藏赞比 | 发布 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        mult = f"{r['likes']/med:.1f}x" if med else "-"
        ratio = (
            f"{r['collects']/r['likes']:.2f}" if r["collects"] and r["likes"] else "-"
        )
        print(
            f"| {(r['title'] or '(无标题)')[:26]} | {r['likes']} | {mult} | "
            f"{r['collects'] if r['collects'] is not None else '-'} | "
            f"{r['comments_cnt'] if r['comments_cnt'] is not None else '-'} | "
            f"{r['shares'] if r['shares'] is not None else '-'} | {ratio} | "
            f"{r['publish_time'] or '-'} |"
        )
    print()
    if med:
        print("> 倍数 = 该篇赞数 ÷ 账号中位赞数。倍数低 ≠ 内容差，先看新鲜度：")
        print("> 发布不足 24 小时的笔记点赞远未发酵完成，不要直接下结论。")
    return 0


def cmd_detail(args: argparse.Namespace) -> int:
    conn = connect()
    row = conn.execute(
        "SELECT * FROM notes WHERE note_id=?", (args.note_id,)
    ).fetchone()
    if not row:
        print("库中无此 note_id，请先用 add/run 纳入。")
        conn.close()
        return 1

    tok = row["xsec_token"]
    print(f"· 使用库内 token（获取于 {row['token_at']}）")
    try:
        detail = fetch_detail(args.note_id, tok or "", with_comments=not args.no_comments)
    except Exception as exc:  # noqa: BLE001
        print(f"· 失败，回主页刷新 token：{str(exc)[:120]}")
        tok = refresh_token(row["user_id"], args.note_id)
        if not tok:
            print("❌ 未能刷新 token（笔记可能已删除或不在主页可见范围）")
            conn.close()
            return 1
        detail = fetch_detail(args.note_id, tok, with_comments=not args.no_comments)

    write_detail(conn, args.note_id, detail)
    out = conn.execute(
        "SELECT * FROM notes WHERE note_id=?", (args.note_id,)
    ).fetchone()
    print(json.dumps({k: out[k] for k in out.keys()}, ensure_ascii=False, indent=2, default=str))
    conn.close()
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """建/重建点赞基线。

    ⚠️ 与抖音不同：小红书主页卡片没有指标，无法批量刷。
    必须逐个打开详情页，token 又随列表生成 → 本命令会先重拉主页刷新 token。
    """
    conn = connect()
    if args.user_id:
        uids = [args.user_id]
    else:
        uids = [r["user_id"] for r in conn.execute("SELECT user_id FROM accounts WHERE active=1")]

    for uid in uids:
        acc = conn.execute("SELECT * FROM accounts WHERE user_id=?", (uid,)).fetchone()
        print(f"\n=== {acc['nickname'] if acc else uid} ===")
        try:
            listed = list_notes(uid, limit=args.limit, scrolls=args.scrolls)
        except CDPFailure as exc:
            print(f"  ❌ 列表抓取失败：{str(exc)[:150]}")
            continue

        token_map = {n.get("id"): n.get("xsec_token") for n in listed}
        for n in listed:
            nid = n.get("id")
            if not nid:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO notes
                   (note_id,user_id,title,cover,note_url,xsec_token,token_at,
                    first_seen,seen_count,notified,suppressed)
                   VALUES (?,?,?,?,?,?,?,?,2,1,'baseline')""",
                (
                    nid,
                    uid,
                    (n.get("title") or "").strip() or None,
                    n.get("cover"),
                    n.get("note_url"),
                    n.get("xsec_token"),
                    now(),
                    now(),
                ),
            )
            # 顺手刷新 token（会过期）
            if n.get("xsec_token"):
                conn.execute(
                    "UPDATE notes SET xsec_token=?, token_at=? WHERE note_id=?",
                    (n["xsec_token"], now(), nid),
                )
        conn.commit()

        rows = conn.execute(
            "SELECT note_id FROM notes WHERE user_id=? AND likes IS NULL", (uid,)
        ).fetchall()
        print(f"  待补详情 {len(rows)} 条")
        ok = 0
        for i, r in enumerate(rows):
            tok = token_map.get(r["note_id"])
            if not tok:
                continue
            try:
                detail = fetch_detail(r["note_id"], tok)
                if write_detail(conn, r["note_id"], detail):
                    ok += 1
                if (i + 1) % 10 == 0:
                    print(f"  [{i+1}/{len(rows)}] …")
            except Exception:  # noqa: BLE001
                continue
        med = recompute_baseline(conn, uid)
        print(f"  ✅ 补到 {ok} 条，点赞中位数 = {med if med is not None else 'NULL'}")

    conn.close()
    return 0


# ---------------------------------------------------------------------------
# 命令：matrix —— 结构参数拆解（模仿用的安全产物）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 赛道 profile —— 钩子规则是「赛道相关」的，不是通用尺子
# ---------------------------------------------------------------------------
# ⚠️ 为什么必须分赛道：
#   出海服务号（Mark 旧号）的爆款钩子是「踩坑／血泪／第一年亏了多少」；
#   投资地图号的爆款钩子是「认知反差／排名榜单／全网没人讲」。
#   用服务号规则去量地图号，绝大多数笔记会落进「陈述式」兜底桶，
#   分布图失去分辨力，矩阵等于废掉。所以规则按赛道分档存储。

# 赛道一：出海服务（原规则原样保留，勿动）
_HOOK_RULES_OVERSEAS_SERVICE: list[tuple[str, str]] = [
    ("疑问式", r"[？?]$|^(为什么|怎么|如何|哪些|有没有|要不要|是不是)"),
    ("反常识/否定", r"^(别|不要|千万别|不是|没人|劝你|停止)|别(碰|这样|买|做)"),
    ("结果前置", r"(赚了|亏了|亏|翻车|血泪|教训|第一年.*(赚|亏))"),
    ("数字锚点", r"\d+\s*(个|条|年|天|万|块|平|次|种|步|%)"),
    ("身份标签", r"(老板|同行|新手|小白|中介|创业者|出海|工厂|货代)"),
    ("对比", r"(vs|VS|还是|对比|区别|差别)"),
    ("内幕/揭秘", r"(内幕|揭秘|真相|潜规则|没人告诉你)"),
]

# 赛道二：地理 / 投资地图
# ⚠️ 本表的顺序是在**没有真实样本**的情况下按这类内容的通行结构排的。
#    拿到真实账号数据后，第一件事是核对「陈述式」兜底桶的占比：
#    若 > 30%，说明规则没覆盖住这个账号的真实句式，必须回改本表。
_HOOK_RULES_GEO_MAP: list[tuple[str, str]] = [
    ("认知反差", r"(你以为|想不到|没想到|竟然|居然|原来|其实|真相|颠覆|反常识|相反)"),
    ("稀缺信息", r"(全网|没人(讲|说)|教科书|99%|很少有人|冷知识|不知道|不为人知|独家|仅此)"),
    ("排名榜单", r"(TOP|top|Top|排行|榜单|榜(单)?|第[一二三四五六七八九十\d]+名|最(大|小|多|少|贵|便宜|富|穷|强|惨))"),
    ("投资视角", r"(赚钱|赚什么|生意|商机|红利|掘金|暴利|利润|做什么|投资|风口|成本|关税|注册)"),
    ("地理特征", r"(出海口|内陆国|海岸线|海峡|运河|边界|纬度|气候|雨林|沙漠|河流|港口|资源)"),
    ("对比", r"(vs|VS|对比|区别|差别|同样|一条.*两国)"),
    ("数字锚点", r"\d+\s*(个|条|国|年|亿|万|%|倍|公里|美元)"),
    ("时点", r"(20\d\d|最新|刚刚|今年|本月|本周|一季度)"),
]

# 赛道注册表
TRACK_HOOKS: dict[str, list[tuple[str, str]]] = {
    "overseas_service": _HOOK_RULES_OVERSEAS_SERVICE,
    "geo_map": _HOOK_RULES_GEO_MAP,
}
TRACK_LABELS = {
    "overseas_service": "出海服务",
    "geo_map": "地理／投资地图",
}
DEFAULT_TRACK = "overseas_service"


def _hook_type(title: str, content: str, track: str = DEFAULT_TRACK) -> str:
    """钩子类型判定。抽的是句式类型，不是原文。

    ⚠️ 必须**标题优先**。早期版本把 title 和 content 拼在一起匹配，
    导致正文里的数字（如「清关周期从 7 天涨到 18 天」）把标题的疑问句式
    （「为什么阿比让的仓库租金涨了 40%？」）盖成了「数字锚点」。
    钩子主要是标题的属性，正文只在标题判不出来时兜底。
    """
    rules = TRACK_HOOKS.get(track) or TRACK_HOOKS[DEFAULT_TRACK]
    title = title or ""
    for name, pattern in rules:
        if re.search(pattern, title):
            return name
    head = (content or "")[:60]
    for name, pattern in rules:
        if re.search(pattern, head):
            return name
    return "陈述式"


# ---------------------------------------------------------------------------
# 地图赛道特有维度
# ---------------------------------------------------------------------------
# 地图号跟服务号最大的结构差别：**「讲哪个尺度的地理」和「这条信息对谁有用」
# 决定了受众**。一个「全球 TOP10」和一条「科特迪瓦某行业机会」，流量来源
# 完全不同（泛流量 vs 精准客户）。这两列是判读地图号的关键，服务号没有。

_REGION_WORDS = {
    "西非": "西非", "东非": "东非", "北非": "北非", "中非": "中非",
    "南部非洲": "南部非洲", "非洲": "非洲（大区）", "撒哈拉": "撒哈拉带",
    "东南亚": "东南亚", "南亚": "南亚", "中亚": "中亚", "东亚": "东亚",
    "中东": "中东", "海湾": "海湾", "波斯湾": "海湾",
    "南美": "南美", "拉美": "拉美", "拉丁美洲": "拉美", "北美": "北美",
    "欧洲": "欧洲", "巴尔干": "巴尔干", "高加索": "高加索",
    "一带一路": "一带一路", "印度洋": "印度洋", "太平洋": "太平洋",
}

_GLOBAL_WORDS = ("全球", "世界", "全世界", "各国", "遍布", "遍布全球")

# 常见国家／地区中文名（用于判「是不是在讲单一国家」）。
# 不求穷尽 —— 目的是区分「单国深挖」与「区域／全球综述」，漏几个不影响判定。
_COUNTRY_NAMES = (
    # 非洲
    "科特迪瓦", "塞内加尔", "贝宁", "尼日利亚", "加纳", "多哥", "布基纳法索",
    "马里", "几内亚", "塞拉利昂", "利比里亚", "冈比亚", "几内亚比绍", "毛里塔尼亚",
    "尼日尔", "乍得", "喀麦隆", "加蓬", "刚果", "安哥拉", "埃塞俄比亚", "厄立特里亚",
    "吉布提", "索马里", "苏丹", "南苏丹", "肯尼亚", "坦桑尼亚", "乌干达", "卢旺达",
    "布隆迪", "赞比亚", "津巴布韦", "马拉维", "莫桑比克", "马达加斯加", "毛里求斯",
    "塞舌尔", "科摩罗", "南非", "纳米比亚", "博茨瓦纳", "莱索托", "斯威士兰",
    "埃及", "利比亚", "突尼斯", "阿尔及利亚", "摩洛哥", "佛得角", "赤道几内亚",
    "圣多美",
    # 亚洲
    "越南", "泰国", "印尼", "印度尼西亚", "马来西亚", "新加坡", "菲律宾", "柬埔寨",
    "老挝", "缅甸", "文莱", "东帝汶", "印度", "巴基斯坦", "孟加拉", "斯里兰卡",
    "尼泊尔", "不丹", "马尔代夫", "蒙古", "哈萨克斯坦", "乌兹别克斯坦", "吉尔吉斯",
    "塔吉克斯坦", "土库曼斯坦", "阿富汗", "伊朗", "伊拉克", "土耳其", "叙利亚",
    "黎巴嫩", "约旦", "以色列", "巴勒斯坦", "沙特", "阿联酋", "卡塔尔",
    "科威特", "巴林", "阿曼", "也门", "格鲁吉亚", "亚美尼亚", "阿塞拜疆",
    # 欧洲
    "俄罗斯", "乌克兰", "白俄罗斯", "波兰", "德国", "法国", "英国", "西班牙",
    "葡萄牙", "意大利", "荷兰", "比利时", "瑞士", "瑞典", "挪威", "芬兰",
    "希腊", "匈牙利", "捷克", "奥地利", "塞尔维亚", "罗马尼亚", "保加利亚",
    # 美洲
    "美国", "加拿大", "墨西哥", "巴西", "阿根廷", "智利", "秘鲁", "哥伦比亚",
    "委内瑞拉", "厄瓜多尔", "玻利维亚", "巴拉圭", "乌拉圭", "古巴", "巴拿马",
    "危地马拉", "洪都拉斯", "萨尔瓦多", "哥斯达黎加", "多米尼加", "海地",
    # 大洋洲
    "澳大利亚", "新西兰", "巴布亚新几内亚", "斐济",
)

_INFO_TYPE_RULES: list[tuple[str, str]] = [
    ("机会", r"(机会|红利|商机|赚钱|掘金|风口|值得|可以做|蓝海|缺口|需求)"),
    ("风险", r"(坑|风险|注意|别|危险|失败|崩|违约|亏|陷阱|血亏|避)"),
    ("数据排名", r"(TOP|top|排行|榜单|排名|第[一二三四五六七八九十\d]+名|GDP|人均|增速)"),
    ("对比", r"(vs|VS|对比|区别|差别|同样|不如|胜过)"),
    ("科普", r"(为什么|起源|历史|地理|文化|人口|气候|河流|边界)"),
]

# 主要城市 → 所属国。地图号有大量「讲城市」的内容（港口/租金/仓储），
# 只认国名会把这批全判成「未判定」，白白丢掉最有商业价值的那一档。
_CITY_TO_COUNTRY = {
    "阿比让": "科特迪瓦", "亚穆苏克罗": "科特迪瓦",
    "达喀尔": "塞内加尔", "科托努": "贝宁", "洛美": "多哥",
    "拉各斯": "尼日利亚", "阿布贾": "尼日利亚", "卡诺": "尼日利亚",
    "阿克拉": "加纳", "库马西": "加纳", "瓦加杜古": "布基纳法索",
    "巴马科": "马里", "科纳克里": "几内亚", "弗里敦": "塞拉利昂",
    "蒙罗维亚": "利比里亚", "努瓦克肖特": "毛里塔尼亚", "尼亚美": "尼日尔",
    "恩贾梅纳": "乍得", "杜阿拉": "喀麦隆", "雅温得": "喀麦隆",
    "利伯维尔": "加蓬", "金沙萨": "刚果（金）", "卢本巴希": "刚果（金）",
    "布拉柴维尔": "刚果（布）", "罗安达": "安哥拉", "洛比托": "安哥拉",
    "亚的斯亚贝巴": "埃塞俄比亚", "阿斯马拉": "厄立特里亚", "吉布提市": "吉布提",
    "摩加迪沙": "索马里", "喀土穆": "苏丹", "朱巴": "南苏丹",
    "内罗毕": "肯尼亚", "蒙巴萨": "肯尼亚", "达累斯萨拉姆": "坦桑尼亚",
    "坎帕拉": "乌干达", "基加利": "卢旺达", "卢萨卡": "赞比亚",
    "哈拉雷": "津巴布韦", "利隆圭": "马拉维", "马普托": "莫桑比克",
    "塔那那利佛": "马达加斯加", "路易港": "毛里求斯",
    "开普敦": "南非", "约翰内斯堡": "南非", "德班": "南非", "比勒陀利亚": "南非",
    "温得和克": "纳米比亚", "哈博罗内": "博茨瓦纳",
    "开罗": "埃及", "亚历山大": "埃及", "的黎波里": "利比亚",
    "突尼斯市": "突尼斯", "阿尔及尔": "阿尔及利亚",
    "卡萨布兰卡": "摩洛哥", "拉巴特": "摩洛哥", "丹吉尔": "摩洛哥",
    "普拉亚": "佛得角", "马拉博": "赤道几内亚",
    # 亚洲
    "胡志明市": "越南", "河内": "越南", "雅加达": "印度尼西亚",
    "曼谷": "泰国", "吉隆坡": "马来西亚", "马尼拉": "菲律宾",
    "金边": "柬埔寨", "仰光": "缅甸", "孟买": "印度", "新德里": "印度",
    "迪拜": "阿联酋", "阿布扎比": "阿联酋", "利雅得": "沙特", "吉达": "沙特",
    "多哈": "卡塔尔", "伊斯坦布尔": "土耳其", "德黑兰": "伊朗",
    # 美洲 / 欧洲
    "圣保罗": "巴西", "里约热内卢": "巴西", "布宜诺斯艾利斯": "阿根廷",
    "圣地亚哥": "智利", "利马": "秘鲁", "波哥大": "哥伦比亚",
    "墨西哥城": "墨西哥", "巴拿马城": "巴拿马", "莫斯科": "俄罗斯",
}


def _geo_unit(text: str) -> str:
    """地图赛道专用：这条内容讲的是哪个地理尺度。

    决定流量来源：全球／区域 = 泛流量；单国 = 半精准；城市 = 精准。
    """
    text = text or ""
    if any(w in text for w in _GLOBAL_WORDS):
        return "全球"
    hits = {v for k, v in _REGION_WORDS.items() if k in text}
    countries = {c for c in _COUNTRY_NAMES if c in text}
    cities = {c for c, country in _CITY_TO_COUNTRY.items() if c in text}
    countries |= {_CITY_TO_COUNTRY[c] for c in cities}
    if hits and len(countries) >= 2:
        return "区域+多国"
    if hits:
        return f"区域（{sorted(hits)[0]}）"
    if len(countries) == 1:
        # 讲城市比讲国家更聚焦，单独标出来 —— 这是转化最强的一档
        label = f"单国（{next(iter(countries))}）"
        if cities:
            label = f"城市（{sorted(cities)[0]}）"
        return label
    if len(countries) >= 2:
        return "多国并列"
    return "未判定"


def _info_type(text: str) -> str:
    """地图赛道专用：这条内容给读者的是什么类型的信息。"""
    text = text or ""
    for name, pattern in _INFO_TYPE_RULES:
        if re.search(pattern, text):
            return name
    return "其他"


# 选题母题：这条内容「讲的是什么」。
# ⚠️ 钩子+尺度+信息类型只回答「怎么讲」，母题才回答「讲什么」——
#    而「选题方向」= 母题 × 尺度 × 钩子的组合。
#    本表同样是**未经真实样本校准**的初版；靠 [15] 的兜底桶告警自检。
_MOTIF_RULES: list[tuple[str, str]] = [
    ("资源禀赋", r"(矿产|石油|天然气|黄金|铜|钴|锂|铀|钻石|铝土|铁矿|森林|渔业|资源|稀土)"),
    ("物流通道", r"(港口|物流|走廊|铁路|公路|清关|仓储|运输|航运|海运|码头|通道)"),
    ("政策合规", r"(政策|注册|税收|关税|签证|许可证|法规|外汇管制|合规|准入|落地|门槛)"),
    ("成本要素", r"(成本|租金|价格|便宜|贵|人工|工资|运费|电费|税费|开销)"),
    ("金融汇率", r"(汇率|银行|融资|贷款|通胀|货币|支付|外汇|保险|资本)"),
    ("市场消费", r"(消费|市场|中产|零售|需求|收入|购买力|客单|渠道)"),
    ("人口人力", r"(人口|劳动力|年轻人|人力|教育|就业|用工|生育)"),
    ("地缘政治", r"(地缘|冲突|战争|制裁|安全|政局|军事|选举|政变)"),
    ("地理气候", r"(气候|沙漠|雨林|干旱|洪水|河流|海岸|纬度|地形|水土)"),
    ("产业图谱", r"(工厂|制造|农业|矿业|加工|纺织|建筑|数字|科技|IT|产业园|加工业)"),
]


def _motif(text: str) -> str:
    """地图赛道专用：选题母题。"""
    text = text or ""
    for name, pattern in _MOTIF_RULES:
        if re.search(pattern, text):
            return name
    return "其他"


def detect_track(conn: sqlite3.Connection, user_id: str) -> tuple[str, str]:
    """自动判断一个账号属于哪个赛道。

    判据：地图信号词在「标题+正文」里的命中率。> 0.35 判为地图号。
    返回 (track, 依据说明)，依据会打进报告，方便人工复核 ——
    自动判定必须可证伪，不能让沉默的分类错误污染整个矩阵。
    """
    rows = conn.execute(
        "SELECT title, content FROM notes WHERE user_id=?", (user_id,)
    ).fetchall()
    if not rows:
        return DEFAULT_TRACK, "无笔记数据，回退默认赛道"

    geo_signal = re.compile(
        r"地图|全球|各国|世界|国家|地理|排行|榜单|TOP|GDP|人口|出海口|"
        r"内陆国|海岸线|海峡|运河|边界|纬度|资源分布|港口|一带一路"
    )
    hit = sum(
        1 for r in rows if geo_signal.search(f"{r['title'] or ''} {r['content'] or ''}")
    )
    rate = hit / len(rows)
    if rate > 0.35:
        return "geo_map", f"地图信号命中 {hit}/{len(rows)} ({rate:.0%}) > 35%"
    return DEFAULT_TRACK, f"地图信号命中 {hit}/{len(rows)} ({rate:.0%}) ≤ 35%"


def _structure_of(note: sqlite3.Row, track: str = DEFAULT_TRACK) -> dict[str, Any]:
    """从一篇笔记里抽「可复用的结构参数」。

    🚫 本函数刻意**不输出原文表述**（除标题用于人工定位外），
    只输出可用于创作的抽象参数。照抄表述是平台原创度判定的高危动作。
    """
    content = note["content"] or ""
    paras = [p for p in re.split(r"\n+", content) if p.strip()]
    chars = len(content)
    role_terms = [
        t
        for t in ("我", "我们", "客户", "店", "门店", "市场", "本地", "非洲", "科特迪瓦")
        if t in content
    ]
    cta = "无"
    if re.search(r"(私信|评论|留言|扣1|联系|咨询|告诉)", content):
        cta = "明确引导"
    elif re.search(r"[？?]", content):
        cta = "提问式"

    info = {
        "title": (note["title"] or "")[:30],
        "publish_time": note["publish_time"],
        "hook": _hook_type(note["title"] or "", content, track),
        "chars": chars,
        "paras": len(paras),
        "avg_para_len": round(chars / len(paras)) if paras else 0,
        "cta": cta,
        "tags_n": len((note["tags"] or "").split(",")) if note["tags"] else 0,
        "role_terms": "、".join(role_terms[:4]) or "-",
        "note_type": note["note_type"] or "-",
        "likes": note["likes"],
        "collects": note["collects"],
        "comments_cnt": note["comments_cnt"],
    }

    if track == "geo_map":
        blob = f"{note['title'] or ''} {content}"
        info["geo_unit"] = _geo_unit(blob)
        info["info_type"] = _info_type(blob)
        info["motif"] = _motif(blob)
        info["has_img_hint"] = bool(
            re.search(r"(图|地图|一览|看懂|分布|示意)", f"{note['title'] or ''}")
        )
    return info


def cmd_matrix(args: argparse.Namespace) -> int:
    conn = connect()
    acc = conn.execute("SELECT * FROM accounts WHERE user_id=?", (args.user_id,)).fetchone()
    rows = conn.execute(
        """SELECT * FROM notes WHERE user_id=? AND likes IS NOT NULL
           ORDER BY likes DESC LIMIT ?""",
        (args.user_id, args.n),
    ).fetchall()

    # 赛道判定：显式指定优先，否则自动判
    if getattr(args, "track", "auto") == "auto":
        track, why = detect_track(conn, args.user_id)
    else:
        track, why = args.track, "命令行显式指定"
    conn.close()

    if not rows:
        print("无带数据的笔记，先跑 add/backfill。")
        return 0

    med = acc["baseline_likes"] if acc else None
    geo = track == "geo_map"
    lines = []
    lines.append(f"# 【结构拆解】 {acc['nickname'] if acc else args.user_id} — 可复用结构参数")
    lines.append("")
    lines.append(f"生成时间：{now()}　数据源：xhs-account-monitor　user_id：{args.user_id}")
    lines.append(f"**赛道判定：{TRACK_LABELS.get(track, track)}**（依据：{why}）")
    lines.append("")
    lines.append(
        "> ⚠️ **本表刻意不含原文表述与封面图，只抽抽象结构参数。**"
        "可直接复用的是「角度/句式类型/信息密度/引导方式」，"
        "**不可复用表述、标题措辞、封面图** —— 那属于原创度判定的高危区。"
    )
    lines.append("")
    lines.append(f"账号点赞中位数：{med if med is not None else 'NULL'}")
    lines.append("")

    if geo:
        lines.append(
            "| 标题(仅定位用) | 钩子类型 | 地理尺度 | 选题母题 | 信息类型 | 正文字数 | "
            "段数 | 引导 | 赞 | 倍数 | 藏赞比 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    else:
        lines.append(
            "| 标题(仅定位用) | 钩子类型 | 正文字数 | 段数 | 均段长 | 引导 | 标签数 | "
            "人称/场景词 | 赞 | 倍数 | 藏赞比 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    structs = [_structure_of(r, track) for r in rows]
    for s in structs:
        mult = f"{s['likes']/med:.1f}x" if med and s["likes"] else "-"
        ratio = (
            f"{s['collects']/s['likes']:.2f}"
            if s["collects"] and s["likes"]
            else "-"
        )
        if geo:
            lines.append(
                f"| {s['title']} | {s['hook']} | {s['geo_unit']} | {s['motif']} | "
                f"{s['info_type']} | "
                f"{s['chars']} | {s['paras']} | {s['cta']} | {s['likes']} | "
                f"{mult} | {ratio} |"
            )
        else:
            lines.append(
                f"| {s['title']} | {s['hook']} | {s['chars']} | {s['paras']} | "
                f"{s['avg_para_len']} | {s['cta']} | {s['tags_n']} | {s['role_terms']} | "
                f"{s['likes']} | {mult} | {ratio} |"
            )
    lines.append("")

    # 归纳：哪些结构参数在本账号被反复验证
    from collections import Counter

    hooks = Counter(s["hook"] for s in structs)
    lines.append("## 结构参数归纳（本账号）")
    lines.append("")
    lines.append("**钩子类型分布：**")
    for k, v in hooks.most_common():
        lines.append(f"- {k}：{v} 篇")
    lines.append("")

    # 兜底桶健康度自检 —— 分类器失效的早期信号
    fallback = hooks.get("陈述式", 0)
    if structs and fallback / len(structs) > 0.30:
        lines.append(
            f"⚠️ **分类器健康度告警**：「陈述式」兜底桶占 {fallback}/{len(structs)}"
            f"（{fallback/len(structs):.0%}）。说明本账号的真实句式没被钩子规则覆盖住，"
            "上面的分布不可信 —— 应先补规则再解读。"
        )
        lines.append("")

    if geo:
        units = Counter(s.get("geo_unit", "未判定") for s in structs)
        infos = Counter(s.get("info_type", "其他") for s in structs)
        motifs = Counter(s.get("motif", "其他") for s in structs)
        lines.append("**地理尺度分布：**")
        for k, v in units.most_common():
            lines.append(f"- {k}：{v} 篇")
        lines.append("")
        lines.append("**选题母题分布：**")
        for k, v in motifs.most_common():
            lines.append(f"- {k}：{v} 篇")
        lines.append("")
        lines.append("**信息类型分布：**")
        for k, v in infos.most_common():
            lines.append(f"- {k}：{v} 篇")
        lines.append("")
        lines.append("**尺度 × 表现对照**（决定这个账号的流量来自哪一层）：")
        lines.append("")
        lines.append("| 地理尺度 | 篇数 | 中位赞 | 中位藏赞比 |")
        lines.append("|---|---|---|---|")
        agg: dict[str, list[tuple[int | None, float | None]]] = {}
        for s in structs:
            agg.setdefault(s.get("geo_unit", "未判定"), []).append(
                (
                    s["likes"],
                    s["collects"] / s["likes"] if s["collects"] and s["likes"] else None,
                )
            )
        for unit, vals in sorted(
            agg.items(),
            key=lambda kv: -(statistics.median([v[0] or 0 for v in kv[1]])),
        ):
            lk = [v[0] for v in vals if v[0] is not None]
            rt = [v[1] for v in vals if v[1] is not None]
            lines.append(
                f"| {unit} | {len(vals)} | "
                f"{statistics.median(lk):.0f} | "
                f"{(f'{statistics.median(rt):.2f}' if rt else '-')} |"
            )
        lines.append("")
        lines.append(
            "> **怎么读这张表**：全球／区域尺度的内容通常赞数高（泛人群看热闹），"
            "但藏赞比低、转化弱；单国／城市尺度赞数低，藏赞比高 —— "
            "收藏的人是真有需求。**你要的客户在后一类里。**"
        )
        lines.append("")

    top = rows[: max(1, len(rows) // 3)]
    if top:
        top_s = [_structure_of(r, track) for r in top]
        avg_chars = sum(s["chars"] for s in top_s) / len(top_s)
        avg_paras = sum(s["paras"] for s in top_s) / len(top_s)
        lines.append(
            f"**高互动组（前 1/3）平均结构：** 正文 {avg_chars:.0f} 字 / "
            f"{avg_paras:.1f} 段"
        )
        lines.append("")

    out = "\n".join(lines)
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"matrix_{args.user_id}_{datetime.now():%Y%m%d}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(out)
    print(f"\n_(已存至 {path})_")
    return 0


def cmd_opportunities(args: argparse.Namespace) -> int:
    """跨账号汇总：哪些「结构参数」在本赛道被反复验证。

    产出喂给 xhs-note-writer 当选题输入，而不是当文案模板。
    """
    conn = connect()
    rows = conn.execute(
        """SELECT n.*, a.nickname, a.baseline_likes FROM notes n
           JOIN accounts a ON n.user_id = a.user_id
           WHERE n.likes IS NOT NULL AND a.active=1"""
    ).fetchall()

    # 赛道判定：显式指定，否则对所有活跃账号投票（多数胜出）
    if getattr(args, "track", "auto") == "auto":
        uids = [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM accounts WHERE active=1"
        ).fetchall()]
        votes: dict[str, int] = {}
        for uid in uids:
            t, _ = detect_track(conn, uid)
            votes[t] = votes.get(t, 0) + 1
        track = max(votes, key=lambda k: votes[k]) if votes else DEFAULT_TRACK
        why = f"按活跃账号投票：{votes}"
    else:
        track, why = args.track, "命令行显式指定"
    conn.close()

    if not rows:
        print("无数据。")
        return 0

    from collections import defaultdict

    geo = track == "geo_map"
    structs = {id(r): _structure_of(r, track) for r in rows}

    by_hook: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_hook[structs[id(r)]["hook"]].append(r)

    lines = ["# 【汇报】 小红书赛道结构机会汇总", ""]
    lines.append(f"生成时间：{now()}　样本：{len(rows)} 篇 / {len({r['user_id'] for r in rows})} 个账号")
    lines.append(f"**赛道：{TRACK_LABELS.get(track, track)}**（依据：{why}）")
    lines.append("")
    lines.append(
        "> 用途：给 `xhs-note-writer` 当**选题角度**输入。"
        "这里给的是「什么角度在这个赛道被反复验证」，不是「照着哪篇写」。"
    )
    lines.append("")
    lines.append("| 钩子类型 | 样本数 | 中位倍数 | 中位藏赞比 | 中位正文字数 | 代表账号 |")
    lines.append("|---|---|---|---|---|---|")

    stats = []
    for hook, items in by_hook.items():
        mults, ratios, chars = [], [], []
        for r in items:
            s = structs[id(r)]
            if r["baseline_likes"] and r["likes"]:
                mults.append(r["likes"] / r["baseline_likes"])
            if r["collects"] and r["likes"]:
                ratios.append(r["collects"] / r["likes"])
            chars.append(s["chars"])
        reps = "、".join({(r["nickname"] or "")[:10] for r in items[:8]})
        stats.append(
            {
                "hook": hook,
                "n": len(items),
                "mult": statistics.median(mults) if mults else None,
                "ratio": statistics.median(ratios) if ratios else None,
                "chars": statistics.median(chars) if chars else 0,
                "reps": reps,
            }
        )

    stats.sort(key=lambda x: (x["mult"] or 0), reverse=True)
    for s in stats:
        mult = f"{s['mult']:.2f}x" if s["mult"] else "-"
        ratio = f"{s['ratio']:.2f}" if s["ratio"] else "-"
        lines.append(
            f"| {s['hook']} | {s['n']} | {mult} | {ratio} | "
            f"{s['chars']:.0f} | {s['reps']} |"
        )

    lines.append("")

    # —— 地图赛道专属：地理尺度 × 信息类型 交叉表 ——
    if geo:
        lines.append("## 地理尺度 × 信息类型（地图赛道专属）")
        lines.append("")
        lines.append("| 地理尺度 | 信息类型 | 篇数 | 中位倍数 | 中位藏赞比 |")
        lines.append("|---|---|---|---|---|")
        cross: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            s = structs[id(r)]
            cross[(s.get("geo_unit", "未判定"), s.get("info_type", "其他"))].append(r)
        cross_rows = []
        for (unit, itype), items in cross.items():
            mults = [
                r["likes"] / r["baseline_likes"]
                for r in items
                if r["baseline_likes"] and r["likes"]
            ]
            ratios = [
                r["collects"] / r["likes"] for r in items if r["collects"] and r["likes"]
            ]
            cross_rows.append(
                (
                    unit,
                    itype,
                    len(items),
                    statistics.median(mults) if mults else None,
                    statistics.median(ratios) if ratios else None,
                )
            )
        cross_rows.sort(key=lambda x: -(x[3] or 0))
        for unit, itype, n, mult, ratio in cross_rows:
            lines.append(
                f"| {unit} | {itype} | {n} | "
                f"{(f'{mult:.2f}x' if mult else '-')} | "
                f"{(f'{ratio:.2f}' if ratio else '-')} |"
            )
        lines.append("")

        # —— 尺度 × 母题 × 钩子：这一层才是「选题方向」 ——
        combos: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            s = structs[id(r)]
            combos[
                (
                    s.get("geo_unit", "未判定"),
                    s.get("motif", "其他"),
                    s["hook"],
                )
            ].append(r)

        ranked = []
        for (unit, motif, hook), items in combos.items():
            mults = [
                r["likes"] / r["baseline_likes"]
                for r in items
                if r["baseline_likes"] and r["likes"]
            ]
            ratios = [
                r["collects"] / r["likes"] for r in items if r["collects"] and r["likes"]
            ]
            ranked.append(
                {
                    "unit": unit,
                    "motif": motif,
                    "hook": hook,
                    "n": len(items),
                    "mult": statistics.median(mults) if mults else None,
                    "ratio": statistics.median(ratios) if ratios else None,
                }
            )
        # 排序：先按藏赞比（精准度），再按倍数、样本数。
        # 破例说明：这里**故意不用点赞数排序** —— 地图赛道点赞高多来自泛流量，
        # 用点赞排序会把「看热闹」的结构排到前面，误导模仿方向。
        ranked.sort(
            key=lambda x: (x["ratio"] or 0, x["mult"] or 0, x["n"]), reverse=True
        )

        assets = _load_assets()
        lines.append("## 选题方向（可直接喂给 xhs-note-writer）")
        lines.append("")
        lines.append(
            "> **怎么用**：每条方向 = 一个「母题 × 地理尺度 × 钩子类型」的结构组合。"
            "拿这个结构 + **你自己的素材**去写。"
            "**不要**去找样本账号的原文当模板 —— 结构可借，表述不可借。"
        )
        lines.append("")
        if assets:
            lines.append(
                f"> 「素材匹配」= 你的存量报告对这条母题的支撑度"
                f"（来源：{assets.get('_source', 'assets.json')}）。"
            )
            lines.append("")
        lines.append(
            "| # | 选题方向 | 结构组合 | 样本 | 中位倍数 | 中位藏赞比 | 素材匹配 |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for i, c in enumerate(ranked[:12], 1):
            direction = f"用「{c['hook']}」切入 {c['unit']} 的「{c['motif']}」"
            combo = f"{c['hook']} × {c['unit']} × {c['motif']}"
            match = _match_assets(assets, c["motif"]) if assets else "-"
            lines.append(
                f"| {i} | {direction} | {combo} | {c['n']} | "
                f"{(f'{c[chr(39)+chr(39)]}' if False else (f'{c['mult']:.2f}x' if c['mult'] else '-'))} | "
                f"{(f'{c['ratio']:.2f}' if c['ratio'] else '-')} | {match} |"
            )
        lines.append("")
        lines.append("**钩子类型怎么写才有效（按结构给创作提示）：**")
        lines.append("")
        for hook, tip in _HOOK_TIPS.items():
            if any(c["hook"] == hook for c in ranked[:12]):
                lines.append(f"- **{hook}** —— {tip}")
        lines.append("")

    lines.append("## 使用建议")
    lines.append("")
    if geo:
        lines.append(
            "1. **别按「点赞最高」挑模仿对象** —— 地图赛道存在结构性偏差："
            "全球／区域尺度天然吃泛流量（点赞高、收藏低），单国／城市尺度吃精准流量"
            "（点赞低、收藏高）。"
        )
        lines.append(
            "2. **优先看「藏赞比」而不是点赞倍数。** 藏赞比 > 0.4 说明内容被当成"
            "「资料」存下来，这类读者的需求是真实且长期的 —— 正是你要转化的那批人。"
        )
        lines.append(
            "3. 挑「中位倍数高**且**样本数 ≥3」的钩子类型 → 说明被反复验证，不是单篇偶然。"
        )
        lines.append(
            "4. **不要**拿代表账号的原文当参照物改写；地图类内容还要额外注意其"
            "**封面图／底图不可复用**（图床指纹可查，且底图多有版权）。"
        )
    else:
        lines.append("1. 挑「中位倍数高」**且**样本数 ≥3 的钩子类型 → 说明它在赛道里被反复验证，不是单篇偶然。")
        lines.append("2. 结合你自己的独家素材（阿比让门店实战/真实客户案例）写。")
        lines.append("3. **不要**拿代表账号的原文当参照物改写。")

    out = "\n".join(lines)
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"opportunities_{datetime.now():%Y%m%d}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(out)
    print(f"\n_(已存至 {path})_")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="小红书账号持续监控（抖音监控技能的小红书适配版）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe", help="首次自检：主页到底暴露了什么字段")
    p_probe.add_argument("target")

    p_add = sub.add_parser("add", help="纳入监控并建基线")
    p_add.add_argument("target", help="主页链接 / 分享口令 / xhslink 短链 / 笔记链接")

    p_run = sub.add_parser("run", help="巡查（含同轮详情抓取）")
    p_run.add_argument("user_id", nargs="?")
    p_run.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p_run.add_argument("--scrolls", type=int, default=DEFAULT_SCROLLS)
    p_run.add_argument("--no-comments", action="store_true", help="不抓评论（快很多）")
    p_run.add_argument("--no-baseline", action="store_true", help="本轮不重算基线")
    p_run.add_argument(
        "--head-window",
        type=int,
        default=HEAD_WINDOW,
        help=f"头部位置窗口（默认 {HEAD_WINDOW}）。高频发布号可放宽，见常量处注释",
    )

    sub.add_parser("list", help="监控名单 + 最新快照")

    p_report = sub.add_parser("report", help="账号历史趋势")
    p_report.add_argument("user_id")

    p_notes = sub.add_parser("notes", help="笔记排行（含倍数）")
    p_notes.add_argument("user_id")
    p_notes.add_argument("n", nargs="?", type=int, default=20)

    p_detail = sub.add_parser("detail", help="补抓单条（自动刷新 token）")
    p_detail.add_argument("note_id")
    p_detail.add_argument("--no-comments", action="store_true")

    p_bf = sub.add_parser("backfill", help="建/重建点赞基线")
    p_bf.add_argument("user_id", nargs="?")
    p_bf.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p_bf.add_argument("--scrolls", type=int, default=DEFAULT_SCROLLS)

    p_matrix = sub.add_parser("matrix", help="结构参数拆解")
    p_matrix.add_argument("user_id")
    p_matrix.add_argument("n", nargs="?", type=int, default=15)
    p_matrix.add_argument(
        "--track",
        choices=["auto", "overseas_service", "geo_map"],
        default="auto",
        help="赛道：auto=按账号笔记自动判（默认）",
    )

    p_opp = sub.add_parser("opportunities", help="跨账号选题机会汇总")
    p_opp.add_argument(
        "--track",
        choices=["auto", "overseas_service", "geo_map"],
        default="auto",
        help="赛道：auto=按活跃账号投票（默认）",
    )

    args = parser.parse_args()

    handlers = {
        "probe": cmd_probe,
        "add": cmd_add,
        "run": cmd_run,
        "list": cmd_list,
        "report": cmd_report,
        "notes": cmd_notes,
        "detail": cmd_detail,
        "backfill": cmd_backfill,
        "matrix": cmd_matrix,
        "opportunities": cmd_opportunities,
    }
    try:
        return handlers[args.cmd](args)
    except CDPFailure as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
