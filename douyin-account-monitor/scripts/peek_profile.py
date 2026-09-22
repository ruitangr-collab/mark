#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复核辅助：打开指定 sec_uid 的主页，打印昵称/签名/统计（复用 monitor.py 登录态与解析原语）。
用法: python3 peek_profile.py <sec_uid> [<sec_uid> ...]
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import monitor  # noqa: E402


def main():
    uids = sys.argv[1:]
    page = monitor.open_browser(headless=False)
    for uid in uids:
        url = f"https://www.douyin.com/user/{uid}"
        try:
            page.get(url)
            time.sleep(6)
            info = monitor.extract_account_from_homepage(page)
            print("=" * 60)
            print("uid:", uid)
            for k in ("nickname", "signature", "follower_count", "total_favorited", "aweme_count"):
                if k in info:
                    print(f"  {k}: {info[k]}")
        except Exception as e:
            print("uid:", uid, "ERROR", repr(e))
    page.quit()


if __name__ == "__main__":
    main()
