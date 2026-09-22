#!/usr/bin/env python3
"""小红书笔记数据快照与归因。

上游 cdp_publish.py 的 content-data 命令只能给出**当前累计值**（曝光/观看/点赞…），
拿不到历史。本脚本在它外面包一层：每次抓取都落一条带日期的快照进 SQLite，
从而得到「趋势」与「单篇归因」——这是回答「Day 3 那篇为什么比 Day 5 好」的唯一前提。

用法：
    python xhs_snapshot.py collect [--date YYYY-MM-DD] [--pages N]
    python xhs_snapshot.py ingest --csv PATH [--date YYYY-MM-DD]
    python xhs_snapshot.py report [--days N] [--top N]
    python xhs_snapshot.py trend --note-id ID | --title KEYWORD

数据落在 ~/.workbuddy/runtime/xhs-data/（刻意放在 git 仓库之外）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_ROOT = os.environ.get(
    "XHS_RUNTIME_DIR",
    os.path.expanduser("~/.workbuddy/runtime/xhs-data"),
)
CSV_DIR = os.path.join(RUNTIME_ROOT, "csv")
REPORT_DIR = os.path.join(RUNTIME_ROOT, "reports")
DB_PATH = os.path.join(RUNTIME_ROOT, "xhs.sqlite3")

# 上游脚本的 Python 解释器（隔离 venv）
PYTHON = os.environ.get(
    "XHS_PYTHON",
    os.path.expanduser("~/.workbuddy/binaries/python/envs/default/bin/python"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_date  TEXT NOT NULL,
    note_key       TEXT NOT NULL,
    note_id        TEXT,
    title          TEXT,
    post_time      TEXT,
    imp            INTEGER,
    read_cnt       INTEGER,
    cover_ctr      REAL,
    like_cnt       INTEGER,
    comment_cnt    INTEGER,
    fav_cnt        INTEGER,
    fans_delta     INTEGER,
    share_cnt      INTEGER,
    view_time_avg  TEXT,
    danmaku        INTEGER,
    captured_at    TEXT,
    PRIMARY KEY (snapshot_date, note_key)
);
CREATE INDEX IF NOT EXISTS idx_note_key ON snapshots(note_key);
CREATE INDEX IF NOT EXISTS idx_post_time ON snapshots(post_time);
"""

# CSV 列名 -> DB 列名
COL_MAP = {
    "标题": "title",
    "发布时间": "post_time",
    "曝光": "imp",
    "观看": "read_cnt",
    "封面点击率": "cover_ctr",
    "点赞": "like_cnt",
    "评论": "comment_cnt",
    "收藏": "fav_cnt",
    "涨粉": "fans_delta",
    "分享": "share_cnt",
    "人均观看时长": "view_time_avg",
    "弹幕": "danmaku",
}


def _ensure_dirs() -> None:
    for d in (RUNTIME_ROOT, CSV_DIR, REPORT_DIR):
        os.makedirs(d, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def _parse_int(value: str | None) -> int | None:
    """'1,234' / '1234' / '-' -> int | None"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("+", "")
    if text in ("", "-", "--", "null", "None"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    return int(float(m.group(0)))


def _parse_rate(value: str | None) -> float | None:
    """'3.21%' -> 0.0321；'0.0321' -> 0.0321"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "--", "null", "None"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    num = float(m.group(0))
    if "%" in text:
        return num / 100.0
    return num


def _note_key(note_id: str | None, title: str | None, post_time: str | None) -> str:
    """优先用 _id；缺失时退化为 标题+发布时间 的哈希，保证同一篇笔记跨天可比。"""
    if note_id and note_id.strip() and note_id.strip() != "-":
        return f"id:{note_id.strip()}"
    raw = f"{(title or '').strip()}|{(post_time or '').strip()}"
    return "h:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def ingest_csv(csv_path: str, snapshot_date: str) -> int:
    """把一份 content-data CSV 写入快照表（同日期重复抓取则覆盖）。"""
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV 不存在: {csv_path}")

    conn = _connect()
    captured_at = datetime.now().isoformat(timespec="seconds")
    written = 0

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title = (row.get("标题") or "").strip()
            post_time = (row.get("发布时间") or "").strip()
            note_id = (row.get("_id") or "").strip()
            if not title and not note_id:
                continue

            record = {
                "snapshot_date": snapshot_date,
                "note_key": _note_key(note_id, title, post_time),
                "note_id": note_id or None,
                "title": title or None,
                "post_time": post_time or None,
                "captured_at": captured_at,
            }
            for csv_col, db_col in COL_MAP.items():
                raw = row.get(csv_col)
                # 文本列已在上面显式赋值，不能走数值解析
                if db_col in ("title", "post_time"):
                    continue
                if db_col == "cover_ctr":
                    record[db_col] = _parse_rate(raw)
                elif db_col == "view_time_avg":
                    record[db_col] = (raw or "").strip() or None
                else:
                    record[db_col] = _parse_int(raw)

            cols = ", ".join(record.keys())
            placeholders = ", ".join("?" for _ in record)
            conn.execute(
                f"INSERT OR REPLACE INTO snapshots ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            written += 1

    conn.commit()
    conn.close()
    return written


def collect(snapshot_date: str, pages: int) -> tuple[str, int]:
    """调用上游 content-data 抓取当日快照并入库。"""
    _ensure_dirs()
    csv_path = os.path.join(CSV_DIR, f"{snapshot_date}.csv")
    cmd = [
        PYTHON,
        os.path.join(SKILL_DIR, "scripts", "cdp_publish.py"),
        "content-data",
        "--page-num",
        "1",
        "--page-size",
        str(max(10, pages * 10)),
        "--csv-file",
        csv_path,
    ]
    env = dict(os.environ)
    # 让 Chrome profile 落在 runtime 目录，而不是污染 ~/Google
    env["LOCALAPPDATA"] = RUNTIME_ROOT
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(
            "content-data 抓取失败（通常是创作者中心登录态失效，先跑 login）：\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    count = ingest_csv(csv_path, snapshot_date)
    return csv_path, count


def _fetch_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM snapshots ORDER BY snapshot_date, post_time"
    ).fetchall()


def _fmt_delta(cur: int | None, first: int | None) -> str:
    if cur is None or first is None:
        return "-"
    d = cur - first
    if d == 0:
        return "0"
    return f"{d:+,}"


def report(days: int, top: int) -> str:
    conn = _connect()
    rows = _fetch_rows(conn)
    conn.close()

    if not rows:
        return "暂无快照数据。先跑 `collect`。"

    by_note: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_note.setdefault(row["note_key"], []).append(row)

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    latest_date = max(r["snapshot_date"] for r in rows)

    summary = []
    for note_key, snaps in by_note.items():
        snaps.sort(key=lambda r: r["snapshot_date"])
        first, last = snaps[0], snaps[-1]
        post_time = last["post_time"] or first["post_time"] or ""
        is_new = post_time[:10] >= cutoff if post_time else False
        summary.append(
            {
                "key": note_key,
                "title": last["title"] or first["title"] or "(无标题)",
                "post_time": post_time,
                "snapshots": len(snaps),
                "days_tracked": (
                    date.fromisoformat(last["snapshot_date"])
                    - date.fromisoformat(first["snapshot_date"])
                ).days,
                "imp": last["imp"],
                "imp_gain": (
                    (last["imp"] or 0) - (first["imp"] or 0)
                    if last["imp"] is not None and first["imp"] is not None
                    else None
                ),
                "read_cnt": last["read_cnt"],
                "cover_ctr": last["cover_ctr"],
                "like_cnt": last["like_cnt"],
                "comment_cnt": last["comment_cnt"],
                "fav_cnt": last["fav_cnt"],
                "fans_delta": last["fans_delta"],
                "share_cnt": last["share_cnt"],
                "view_time_avg": last["view_time_avg"],
                "is_new": is_new,
            }
        )

    lines: list[str] = []
    lines.append(f"# 小红书账号数据快照报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 最新快照日期：{latest_date}")
    lines.append(f"- 累计快照天数：{len({r['snapshot_date'] for r in rows})}")
    lines.append(f"- 追踪笔记数：{len(summary)}")
    lines.append("")

    new_notes = [s for s in summary if s["is_new"]]
    if new_notes:
        lines.append(f"## 近 {days} 天新发布笔记（{len(new_notes)} 篇）")
        lines.append("")
        lines.append(
            "| 标题 | 发布时间 | 曝光 | 观看 | 封面点击率 | 点赞 | 评论 | 收藏 | 涨粉 | 分享 | 人均观看时长 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for s in sorted(new_notes, key=lambda x: (x["imp"] or 0), reverse=True):
            ctr = f"{s['cover_ctr']*100:.2f}%" if s["cover_ctr"] is not None else "-"
            lines.append(
                f"| {s['title']} | {s['post_time']} | {s['imp'] if s['imp'] is not None else '-'} "
                f"| {s['read_cnt'] if s['read_cnt'] is not None else '-'} | {ctr} "
                f"| {s['like_cnt'] if s['like_cnt'] is not None else '-'} "
                f"| {s['comment_cnt'] if s['comment_cnt'] is not None else '-'} "
                f"| {s['fav_cnt'] if s['fav_cnt'] is not None else '-'} "
                f"| {s['fans_delta'] if s['fans_delta'] is not None else '-'} "
                f"| {s['share_cnt'] if s['share_cnt'] is not None else '-'} "
                f"| {s['view_time_avg'] or '-'} |"
            )
        lines.append("")

    multi = [s for s in summary if s["snapshots"] > 1]
    if multi:
        lines.append(f"## 跨天增量（已追踪 ≥2 次快照，{len(multi)} 篇）")
        lines.append("")
        lines.append("| 标题 | 追踪天数 | 曝光 | 曝光增量 | 最新观看 | 最新点赞 | 最新涨粉 |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in sorted(multi, key=lambda x: (x["imp_gain"] or 0), reverse=True):
            lines.append(
                f"| {s['title']} | {s['days_tracked']} | "
                f"{s['imp'] if s['imp'] is not None else '-'} | "
                f"{s['imp_gain'] if s['imp_gain'] is not None else '-'} | "
                f"{s['read_cnt'] if s['read_cnt'] is not None else '-'} | "
                f"{s['like_cnt'] if s['like_cnt'] is not None else '-'} | "
                f"{s['fans_delta'] if s['fans_delta'] is not None else '-'} |"
            )
        lines.append("")

    def rank_block(title: str, key: str, n: int, reverse: bool = True) -> None:
        pool = [s for s in summary if s.get(key) is not None]
        if not pool:
            return
        pool.sort(key=lambda x: x[key], reverse=reverse)
        lines.append(f"## {title}")
        lines.append("")
        for s in pool[:n]:
            v = s[key]
            if key == "cover_ctr":
                v = f"{v*100:.2f}%"
            lines.append(f"- {s['title']} — {v}")
        lines.append("")

    rank_block(f"曝光 TOP {top}", "imp", top)
    rank_block(f"封面点击率 TOP {top}", "cover_ctr", top)
    rank_block(f"涨粉 TOP {top}", "fans_delta", top)
    rank_block(f"曝光 BOTTOM {top}（最值得复盘）", "imp", top, reverse=False)

    if len(multi) < 2:
        lines.append("> ⚠️ 跨天趋势尚未形成。快照需要**每天至少跑一次**，累积 3 天以上才能看出判读性差异。")
        lines.append("")

    output = "\n".join(lines)
    _ensure_dirs()
    out_path = os.path.join(REPORT_DIR, f"report_{date.today().isoformat()}.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(output)
    return output + f"\n\n_(报告已存至 {out_path})_"


def trend(note_id: str | None, title_kw: str | None) -> str:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    if note_id:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE note_id = ? OR note_key = ? ORDER BY snapshot_date",
            (note_id, f"id:{note_id}"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE title LIKE ? ORDER BY snapshot_date",
            (f"%{title_kw}%",),
        ).fetchall()
    conn.close()

    if not rows:
        return "未找到匹配快照。"

    lines = [f"# 单篇趋势：{rows[0]['title']}", ""]
    lines.append("| 快照日期 | 曝光 | 观看 | 封面点击率 | 点赞 | 评论 | 收藏 | 涨粉 | 分享 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    prev = None
    for r in rows:
        ctr = f"{r['cover_ctr']*100:.2f}%" if r["cover_ctr"] is not None else "-"
        lines.append(
            f"| {r['snapshot_date']} | {r['imp'] if r['imp'] is not None else '-'} "
            f"| {r['read_cnt'] if r['read_cnt'] is not None else '-'} | {ctr} "
            f"| {r['like_cnt'] if r['like_cnt'] is not None else '-'} "
            f"| {r['comment_cnt'] if r['comment_cnt'] is not None else '-'} "
            f"| {r['fav_cnt'] if r['fav_cnt'] is not None else '-'} "
            f"| {r['fans_delta'] if r['fans_delta'] is not None else '-'} "
            f"| {r['share_cnt'] if r['share_cnt'] is not None else '-'} |"
        )
        prev = r
    lines.append("")
    if len(rows) > 1:
        first, last = rows[0], rows[-1]
        lines.append("## 区间增量")
        lines.append("")
        for label, col in [
            ("曝光", "imp"),
            ("观看", "read_cnt"),
            ("点赞", "like_cnt"),
            ("评论", "comment_cnt"),
            ("收藏", "fav_cnt"),
            ("涨粉", "fans_delta"),
            ("分享", "share_cnt"),
        ]:
            lines.append(f"- {label}：{_fmt_delta(last[col], first[col])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="小红书笔记数据快照与归因")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_collect = sub.add_parser("collect", help="抓取当日快照并入库")
    p_collect.add_argument("--date", default=date.today().isoformat())
    p_collect.add_argument("--pages", type=int, default=3, help="期望页数（每页 10 条）")

    p_ingest = sub.add_parser("ingest", help="把已有 CSV 入库")
    p_ingest.add_argument("--csv", required=True)
    p_ingest.add_argument("--date", default=date.today().isoformat())

    p_report = sub.add_parser("report", help="出账号级快照报告")
    p_report.add_argument("--days", type=int, default=30)
    p_report.add_argument("--top", type=int, default=5)

    p_trend = sub.add_parser("trend", help="看单篇笔记的趋势")
    p_trend.add_argument("--note-id")
    p_trend.add_argument("--title")

    args = parser.parse_args()

    if args.cmd == "collect":
        try:
            csv_path, count = collect(args.date, args.pages)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {exc}", file=sys.stderr)
            return 1
        print(f"✅ 已抓取 {count} 条笔记 -> {csv_path}")
        print()
        print(report(30, 5))
    elif args.cmd == "ingest":
        count = ingest_csv(args.csv, args.date)
        print(f"✅ 已入库 {count} 条（快照日期 {args.date}）-> {DB_PATH}")
    elif args.cmd == "report":
        print(report(args.days, args.top))
    elif args.cmd == "trend":
        if not args.note_id and not args.title:
            print("需提供 --note-id 或 --title", file=sys.stderr)
            return 1
        print(trend(args.note_id, args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
