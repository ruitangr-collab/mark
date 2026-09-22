#!/usr/bin/env python3
"""深度诊断：捕获所有 API 响应，找出搜索用的真实 API"""
import asyncio, json, sys, urllib.parse, os, re
from pathlib import Path
from playwright.async_api import async_playwright

WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
SESSION_FILE = WORK_DIR / "douyin_session.json"
CHROMIUM = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

def log(msg):
    sys.stdout.buffer.write(f"{msg}\n".encode('utf-8'))
    sys.stdout.buffer.flush()

async def main():
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

        # Capture ALL XHR/fetch responses (not static resources)
        api_responses = []

        def on_response(response):
            url = response.url
            # Only capture API calls (not static resources)
            if any(x in url for x in ["/aweme/", "/api/", "/search/", "douyin.com/aweme", "douyin.com/webcast"]):
                if not url.endswith(('.js','.css','.png','.jpg','.svg','.woff','.ico','.gif')):
                    try:
                        ct = response.headers.get('content-type','')
                        if 'json' in ct or 'javascript' in ct:
                            api_responses.append({
                                "url": url[:200],
                                "status": response.status,
                            })
                            # For search-related ones, get body
                            if any(kw in url for kw in ['search/item','search/stream','search/general','search/video','search/aweme','search/feed']):
                                log(f"\n*** SEARCH API: {url[:200]}")
                    except:
                        pass

        page.on("response", on_response)

        # Also use route interceptor without modification (pass through)
        async def handle_route(route, request):
            resp = await route.fetch()
            url = request.url
            if "aweme" in url and "search" in url:
                body_bytes = await resp.body()
                try:
                    text = body_bytes.decode("utf-8")[:500]
                    log(f"\n>>> ROUTE [{url[:150]}]\n    {text}")
                except:
                    log(f"\n>>> ROUTE [{url[:150]}] (binary)")
            await route.fulfill(response=resp)

        # Route ALL aweme APIs
        await page.route("**/aweme/**", handle_route)

        kw = "尼日利亚 华人"
        enc = urllib.parse.quote(kw)
        log(f"\nNavigating: https://www.douyin.com/search/{enc}?type=video")
        await page.goto(f"https://www.douyin.com/search/{enc}?type=video", wait_until="commit", timeout=30000)
        
        log("Waiting 20s...")
        await asyncio.sleep(20)

        # Scroll
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 600)")
            await asyncio.sleep(2)

        await asyncio.sleep(5)

        log(f"\n=== ALL search-related APIs ({len(api_responses)}) ===")
        for r in api_responses:
            if any(kw in r['url'] for kw in ['search','aweme','video','feed','stream']):
                log(f"  [{r['status']}] {r['url'][:180]}")

        # Also check page content for login wall
        title = await page.title()
        log(f"\nPage title: {title}")
        current_url = page.url
        log(f"Current URL: {current_url}")

        # Take a screenshot to see what's on screen
        await page.screenshot(path=str(WORK_DIR / "debug_screenshot.png"))
        log(f"Screenshot saved to debug_screenshot.png")

        await browser.close()

asyncio.run(main())
