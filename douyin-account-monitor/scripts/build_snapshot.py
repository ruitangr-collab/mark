#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并「上一日【监控对象】清单」的分级/备注 + 监控库最新快照 → 生成新清单的数据骨架。
用法: python3 build_snapshot.py <上一日清单.md> [--json]

输出 TSV: grade, nickname, followers, favorited, aweme, added_at, note
分级/备注从上一日清单继承；新账号（不在上一日清单）grade 留空待人工判定。
"""
import re, sys, sqlite3, os, json

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "monitor.db")


def fmt(n):
    if n is None:
        return "?"
    n = int(n)
    if n >= 100000000:
        return f"{n/100000000:.1f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"


def parse_prev(path):
    """解析上一日清单的账号全表 -> {nickname: (grade, note)}"""
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 9:
            continue
        grade, nick, note = cells[0], cells[1], cells[-1]
        if grade in ("分级", "---") or set(grade) <= set("- "):
            continue
        if not re.match(r"^[SAB?]", grade):
            continue
        out[nick] = (grade, note)
    return out


def main():
    prev_path = sys.argv[1]
    prev = parse_prev(prev_path)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT a.sec_uid, a.nickname, a.added_at,
               s.follower_count, s.total_favorited, s.aweme_count, s.checked_at
        FROM accounts a
        LEFT JOIN snapshots s ON a.sec_uid = s.sec_uid
          AND s.checked_at = (SELECT MAX(checked_at) FROM snapshots s2 WHERE s2.sec_uid = a.sec_uid)
        WHERE a.active = 1
        ORDER BY a.added_at ASC, a.nickname ASC
    """).fetchall()
    out = []
    for r in rows:
        g, note = prev.get(r["nickname"], ("", ""))
        out.append({
            "sec_uid": r["sec_uid"], "nickname": r["nickname"], "grade": g, "note": note,
            "followers": fmt(r["follower_count"]), "favorited": fmt(r["total_favorited"]),
            "aweme": fmt(r["aweme_count"]), "added_at": (r["added_at"] or "")[:10],
            "checked_at": (r["checked_at"] or "")[:16],
        })
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print("total\t%d\tprev_matched\t%d" % (len(out), sum(1 for o in out if o["grade"])))
    print("grade\tnickname\tfollowers\tfavorited\taweme\tadded_at\tnote")
    for o in out:
        print("%s\t%s\t%s\t%s\t%s\t%s\t%s" % (o["grade"] or "?NEW", o["nickname"], o["followers"],
                                              o["favorited"], o["aweme"], o["added_at"], o["note"]))


if __name__ == "__main__":
    main()
