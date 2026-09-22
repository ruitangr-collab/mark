#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出监控名单全量快照（accounts + 最新 snapshot）为 TSV，供生成【监控对象】清单。
用法: python3 dump_list.py [--json]
"""
import sqlite3, sys, json, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "monitor.db")


def fmt(n):
    if n is None:
        return "?"
    return f"{n:,}"


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        SELECT a.sec_uid, a.nickname, a.signature, a.added_at, a.last_check,
               a.douyin_id, a.ip_location, a.region,
               s.follower_count, s.total_favorited, s.aweme_count, s.checked_at
        FROM accounts a
        LEFT JOIN snapshots s ON a.sec_uid = s.sec_uid
          AND s.checked_at = (SELECT MAX(checked_at) FROM snapshots s2 WHERE s2.sec_uid = a.sec_uid)
        WHERE a.active = 1
        ORDER BY a.added_at ASC, a.nickname ASC
    """).fetchall()
    out = []
    for r in rows:
        out.append({
            "sec_uid": r["sec_uid"],
            "nickname": r["nickname"],
            "signature": (r["signature"] or "").replace("\n", " "),
            "douyin_id": r["douyin_id"],
            "ip_location": r["ip_location"],
            "region": r["region"],
            "added_at": r["added_at"],
            "followers": r["follower_count"],
            "favorited": r["total_favorited"],
            "aweme": r["aweme_count"],
            "checked_at": r["checked_at"],
        })
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("total\t%d" % len(out))
        print("nickname\tfollowers\tfavorited\taweme\tdouyin_id\tip\tadded_at\tchecked_at\tsignature")
        for o in out:
            print("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (
                o["nickname"], fmt(o["followers"]), fmt(o["favorited"]),
                fmt(o["aweme"]), o["douyin_id"] or "-", o["ip_location"] or "-",
                (o["added_at"] or "")[:10], (o["checked_at"] or "")[:16],
                o["signature"][:120]))


if __name__ == "__main__":
    main()
