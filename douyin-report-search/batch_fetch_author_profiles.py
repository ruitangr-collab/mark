"""
批量采集作者画像 — 自动重启包装器。
调用 fetch_author_profiles.py，如果因 session 过期或网络问题退出，
自动触发重新登录后重启（最多 5 次）。
"""
import subprocess, sys, time, json
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
SCRIPT = WORK_DIR / "scripts" / "fetch_author_profiles.py"
LOGIN_SCRIPT = WORK_DIR / "scripts" / "douyin_login.py"
MAX_RETRIES = 5
BASE_WAIT = 30  # 首次重试等待秒数

print(f"=== 作者画像批量采集（带自动重启 + 自动重登） ===")
print(f"脚本: {SCRIPT}")
print(f"最大重试: {MAX_RETRIES} 次\n")

for attempt in range(1, MAX_RETRIES + 1):
    print(f"[第 {attempt} 次启动] {time.strftime('%H:%M:%S')}")
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(WORK_DIR))

    if result.returncode == 0:
        print(f"\n=== 采集完成! (第 {attempt} 次运行成功) ===")
        cache_file = WORK_DIR / "author_profiles_cache.json"
        if cache_file.exists():
            cache = json.load(open(cache_file, "r", encoding="utf-8"))
            new_fmt = sum(1 for v in cache.values() if v.get("_cache_version") == 2)
            old_fmt = sum(1 for v in cache.values() if v.get("_cache_version", 1) < 2)
            total = len(cache)
            print(f"缓存: {total} 人 (新格式: {new_fmt}, 旧格式剩余: {old_fmt})")
        break

    # 退出码 2 = session 过期 / 需要重新登录
    if result.returncode == 2:
        print(f"\n[Session 过期, 请扫码重新登录...]")
        login_ret = subprocess.run([sys.executable, str(LOGIN_SCRIPT), str(WORK_DIR)])
        if login_ret.returncode != 0:
            print(f"[警告] 登录脚本返回 {login_ret.returncode}，继续重试...")
    else:
        print(f"\n[退出码 {result.returncode}]")

    if attempt < MAX_RETRIES:
        wait = BASE_WAIT * attempt
        print(f"{wait}s 后重试...\n")
        time.sleep(wait)
    else:
        print(f"\n=== 已达到最大重试次数 ({MAX_RETRIES})，请检查后手动重试 ===")
        sys.exit(1)
