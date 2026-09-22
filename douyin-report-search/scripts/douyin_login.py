#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音登录 & 保存 Session
用法：python3 douyin_login.py [工作目录]

执行后：
  1. 打开抖音首页（Chromium）
  2. 用户手动扫码登录
  3. 检测到登录成功后，自动保存 cookies 到 douyin_session.json
"""
import asyncio, json, sys
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

WORK_DIR     = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()
SESSION_FILE = WORK_DIR / "douyin_session.json"

def log(msg):
    import sys as _sys
    _sys.stdout.buffer.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n".encode('utf-8'))
    _sys.stdout.buffer.flush()

CHROMIUM_PATH = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

async def login():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        launch_kwargs = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox",
                      "--window-size=1440,900", "--window-position=0,0"],
        }
        # 优先使用已下载的 Playwright Chromium
        import os
        if os.path.exists(CHROMIUM_PATH):
            launch_kwargs["executable_path"] = CHROMIUM_PATH
            log(f"使用 Playwright Chromium: {CHROMIUM_PATH}")
        else:
            log("未找到 Playwright Chromium，尝试使用系统 Edge...")

        browser = await p.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = await ctx.new_page()

        log("导航到抖音首页...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        log("请在浏览器中扫码/点击登录。等待登录成功（最多 120 秒）...")

        # 轮询检测登录状态：cookie 中出现 passport_csrf_token 或 sessionid
        for i in range(120):
            await asyncio.sleep(1)
            cookies = await ctx.cookies()
            cookie_names = {c["name"] for c in cookies}
            if "passport_csrf_token" in cookie_names or "sessionid" in cookie_names:
                log(f"检测到登录成功（{i+1}s）")
                break
        else:
            log("超时，请检查是否已登录")

        cookies = await ctx.cookies()
        SESSION_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8')
        log(f"Session 已保存到 {SESSION_FILE}（共 {len(cookies)} 个 cookie）")

        await browser.close()

asyncio.run(login())
