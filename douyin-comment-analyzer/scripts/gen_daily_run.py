#!/usr/bin/env python3
"""由 s_watchlist.json 生成当日串行抓取驱动脚本（zsh）。

用法:
    python3 scripts/gen_daily_run.py [YYYY-MM-DD]

设计目标：S 级监控名单只维护 _archive/s_watchlist.json 一个文件，
每日自动化调用本脚本生成 run_daily_<date>.sh，不需要改自动化任务本身。

严格串行：一次一个浏览器进程，避免共享 Chrome profile 导致账号串号。
"""
import json
import sys
from datetime import date
from pathlib import Path

WATCHLIST = Path.home() / ".workbuddy/douyin_analysis/_archive/s_watchlist.json"
RUNTIME = Path.home() / ".workbuddy/douyin_analysis/_runtime"
SKILL_DIR = "/Users/goterra/.workbuddy/skills/douyin-comment-analyzer"
PY = "/Users/goterra/.workbuddy/binaries/python/envs/default/bin/python3"
KEYWORD = "非洲出海"
VIDEO_N = 10


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")
    data = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    accounts = data.get("accounts", [])
    if not accounts:
        print("ERROR: s_watchlist.json 中 accounts 为空", file=sys.stderr)
        return 1

    RUNTIME.mkdir(parents=True, exist_ok=True)
    out = RUNTIME / f"run_daily_{day}.sh"
    log = RUNTIME / f"daily_run_{day}.log"
    result = RUNTIME / f"daily_run_{day}.result"

    lines = [
        "#!/bin/zsh",
        f"# 抖音出海非洲每日监控 - 串行抓取驱动脚本 ({day})",
        "# 本文件由 scripts/gen_daily_run.py 依据 _archive/s_watchlist.json 自动生成，请勿手改。",
        "# 严格串行：一次一个浏览器进程，避免共享 Chrome profile 导致账号串号。",
        "set -u",
        "",
        f"cd {SKILL_DIR} || exit 1",
        f"PY={PY}",
        f"LOG={log}",
        f"RESULT={result}",
        "",
        "echo \"===== RUN START $(date '+%F %T') =====\" > \"$LOG\"",
        "echo \"\" > \"$RESULT\"",
        "",
        "run_one() {",
        "  local label=\"$1\"; shift",
        "  echo \"\" >> \"$LOG\"",
        "  echo \"----- [$label] START $(date '+%T') -----\" >> \"$LOG\"",
        "  \"$@\" >> \"$LOG\" 2>&1",
        "  local rc=$?",
        "  echo \"----- [$label] END $(date '+%T') rc=$rc -----\" >> \"$LOG\"",
        "  echo \"$label|$rc\" >> \"$RESULT\"",
        "  return 0",
        "}",
        "",
    ]

    for acc in accounts:
        nick = acc["nickname"]
        url = acc["url"]
        lines.append(
            f'run_one "account_{nick}" "$PY" scripts/account_analyzer.py "{url}" {VIDEO_N} '
            f'--minimized --expect "{nick}"'
        )

    lines.append(
        f'run_one "keyword_{KEYWORD}"    "$PY" scripts/keyword_extract.py {KEYWORD} {VIDEO_N} --minimized'
    )
    lines += [
        "",
        "echo \"\" >> \"$LOG\"",
        "echo \"===== RUN END $(date '+%F %T') =====\" >> \"$LOG\"",
        "echo \"ALLDONE\" >> \"$RESULT\"",
        "",
    ]

    out.write_text("\n".join(lines), encoding="utf-8")
    out.chmod(0o755)
    print(f"generated: {out}")
    print(f"accounts : {len(accounts)} -> {', '.join(a['nickname'] for a in accounts)}")
    print(f"log      : {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
