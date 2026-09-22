#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工复核回滚：删除账号 + 写入黑名单（rejected_accounts.json）。
用法:
  python3 rollback_account.py <sec_uid> "<昵称>" "<回滚原因>" [--dry-run]

⚠️ 必须同步写黑名单——否则下轮搜索命中会再次自动入库（2026-09-06 教训）。
"""
import sys, json, sqlite3, os
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
DB = DATA / "monitor.db"
BL = DATA / "rejected_accounts.json"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if len(args) < 3:
        print(__doc__)
        return 1
    uid, nick, reason = args[0], args[1], args[2]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    c = sqlite3.connect(DB)
    row = c.execute("SELECT nickname FROM accounts WHERE sec_uid=?", (uid,)).fetchone()
    n_snap = c.execute("SELECT COUNT(*) FROM snapshots WHERE sec_uid=?", (uid,)).fetchone()[0]
    n_vid = c.execute("SELECT COUNT(*) FROM videos WHERE sec_uid=?", (uid,)).fetchone()[0]
    print(f"目标: {row[0] if row else '(库中无此号)'} | uid={uid[:24]}...")
    print(f"  将删除 snapshots={n_snap} videos={n_vid}")
    if dry:
        print("  [dry-run] 未执行")
        return 0

    c.execute("DELETE FROM accounts WHERE sec_uid=?", (uid,))
    c.execute("DELETE FROM snapshots WHERE sec_uid=?", (uid,))
    c.commit()
    left = c.execute("SELECT COUNT(*) FROM accounts WHERE active=1").fetchone()[0]
    c.close()

    bl = json.load(open(BL, encoding="utf-8")) if BL.exists() else {}
    bl[uid] = {"nickname": nick, "reason": reason,
               "rolled_back_at": now, "note": f"{now[:10]} 拓号人工复核回滚后补黑名单"}
    json.dump(bl, open(BL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  ✅ 已回滚并写入黑名单（黑名单共 {len(bl)} 条）；名单剩余 {left} 个")


if __name__ == "__main__":
    main()
