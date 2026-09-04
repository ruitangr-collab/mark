#!/usr/bin/env python3
"""快速登录态探针：打开抖音首页，立即检查 isLogin，几秒内返回，不等扫码。"""
import sys, time
from pathlib import Path
from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_render_data, is_logged_in

PROFILE_DIR = Path.home() / ".workbuddy/douyin_chrome_profile"

co = ChromiumOptions()
co.set_argument("--window-minimized", "true")
co.set_user_data_path(str(PROFILE_DIR))
page = ChromiumPage(co)
page.get("https://www.douyin.com/")
time.sleep(8)

if is_logged_in(page):
    print("LOGIN_OK")
else:
    print("LOGIN_EXPIRED")
page.quit()
