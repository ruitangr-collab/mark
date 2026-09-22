#!/usr/bin/env python3
"""快速诊断：检查 API 拦截是否正常工作"""
import asyncio, json, sys, urllib.parse, os
from pathlib import Path
from playwright.async_api import async_playwright

WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
SESSION_FILE = WORK_DIR / "douyin_session.json"
CHROMIUM = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

def log(msg):
    sys.stdout.buffer.write(f"[DIAG] {msg}\n".encode('utf-8'))
    sys.stdout.buffer.flush()

async def main():
    if not SESSION_FILE.exists():
        log("ERROR: No session file")
        return

    async with async_playwright() as p:
        launch_kw = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled","--no-sandbox","--window-size=1440,900"],
        }
        if os.path.exists(CHROMIUM):
            launch_kw["executable_path"] = CHROMIUM
        browser = await p.chromium.launch(**launch_kw)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="zh-CN", viewport={"width": 1440, "height": 900},
        )
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        cookies = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        await ctx.add_cookies([
            {"name": c["name"], "value": c["value"],
             "domain": c.get("domain", ".douyin.com"),
             "path": c.get("path", "/")} for c in cookies
        ])
        log(f"Cookies: {len(cookies)}")

        page = await ctx.new_page()

        # Log ALL network requests to see what API is being called
        api_urls = set()
        def on_response(response):
            url = response.url
            if "aweme" in url or "search" in url:
                api_urls.add(url)

        page.on("response", on_response)

        # Route interceptor with verbose logging
        async def handle_route(route, request):
            url = request.url
            if "aweme" in url or "search" in url:
                log(f"ROUTE: {url[:120]}")
            resp = await route.fetch()
            if "search/item" in url:
                body_bytes = await resp.body()
                text = body_bytes.decode("utf-8")
                log(f"RESP: {text[:300]}")
                try:
                    body = json.loads(text)
                    data_arr = body.get("data") or []
                    log(f"  data array length: {len(data_arr)}")
                    if data_arr:
                        log(f"  first item keys: {list(data_arr[0].keys())}")
                except:
                    log(f"  PARSE FAILED")
            await route.fulfill(response=resp)

        await page.route("**/aweme/v1/web/search/item/**", handle_route)

        kw = "尼日利亚 华人"
        enc = urllib.parse.quote(kw)
        log(f"Navigating to: https://www.douyin.com/search/{enc}?type=video")
        await page.goto(f"https://www.douyin.com/search/{enc}?type=video", wait_until="commit", timeout=30000)
        
        log("Waiting 15s for API calls...")
        await asyncio.sleep(15)

        # Scroll a bit
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(2)
        
        await asyncio.sleep(5)

        log(f"\nAll captured API URLs ({len(api_urls)}):")
        for u in sorted(api_urls):
            log(f"  {u[:150]}")

        await browser.close()

asyncio.run(main())
