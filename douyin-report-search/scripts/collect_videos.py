#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频数据采集 v3 — 使用 page.route() 拦截，正确解析 data[].aweme_info
用法：python3 collect_videos.py [关键词] [采集数量] [工作目录] [输出文件名]
"""

import asyncio, json, time, random, urllib.parse, sys, io
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

KEYWORD      = sys.argv[1] if len(sys.argv) > 1 else "女性成长"
TOTAL        = int(sys.argv[2]) if len(sys.argv) > 2 else 100
WORK_DIR     = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path(".").resolve()
OUTPUT_NAME  = sys.argv[4] if len(sys.argv) > 4 else "douyin_raw_data.json"

SESSION_FILE = WORK_DIR / "douyin_session.json"
RAW_FILE     = WORK_DIR / OUTPUT_NAME
CHROMIUM     = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

def log(msg):
    sys.stdout.buffer.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n".encode('utf-8'))
    sys.stdout.buffer.flush()

async def main():
    if not SESSION_FILE.exists():
        log("ERROR: No douyin_session.json, run login first")
        return

    log("=" * 60)
    log(f"Douyin Search: [{KEYWORD}]  target={TOTAL}")
    log("=" * 60)

    collected = []
    collected_ids = set()

    async with async_playwright() as p:
        import os
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

        # ── Route-based interception: captures FULL response body ──
        def on_route_result(data_list):
            """Called from handle_route with parsed video items"""
            for vid in data_list:
                aid = vid.get("aweme_id")
                if aid and aid not in collected_ids:
                    collected_ids.add(aid)
                    collected.append(vid)

        all_intercepted = []

        async def handle_route(route, request):
            resp = await route.fetch()
            url = request.url
            if "search/item" in url:
                try:
                    body_bytes = await resp.body()
                    body = json.loads(body_bytes.decode("utf-8"))
                    items = []
                    data_arr = body.get("data") or []
                    for item in data_arr:
                        if item.get("type") == 1 and item.get("aweme_info"):
                            info = item["aweme_info"]
                            items.append({
                                "aweme_id": info.get("aweme_id", ""),
                                "desc": info.get("desc", ""),
                                "create_time": info.get("create_time", 0),
                                "author": {
                                    "uid": info.get("author", {}).get("uid", ""),
                                    "nickname": info.get("author", {}).get("nickname", ""),
                                    "sec_uid": info.get("author", {}).get("sec_uid", ""),
                                },
                                "statistics": {
                                    "digg_count": info.get("statistics", {}).get("digg_count", 0),
                                    "comment_count": info.get("statistics", {}).get("comment_count", 0),
                                    "share_count": info.get("statistics", {}).get("share_count", 0),
                                    "collect_count": info.get("statistics", {}).get("collect_count", 0),
                                    "play_count": info.get("statistics", {}).get("play_count", 0),
                                },
                                "_raw": info,
                            })
                    all_intercepted.append(len(items))
                    if items:
                        on_route_result(items)
                        log(f"  >> API: {len(items)} items (has_more={body.get('has_more',0)}, cursor={body.get('cursor',0)})")
                except Exception as e:
                    log(f"  >> API parse err: {e}")
            await route.fulfill(response=resp)

        await page.route("**/aweme/v1/web/search/item/**", handle_route)
        log("Route interceptor set up")

        # ── Navigate ──
        enc_kw = urllib.parse.quote(KEYWORD)
        log(f"Opening: https://www.douyin.com/search/{enc_kw}?type=video")
        await page.goto(
            f"https://www.douyin.com/search/{enc_kw}?type=video",
            wait_until="commit", timeout=60000,
        )
        await asyncio.sleep(random.uniform(6, 10))
        
        # Simulate human initial scroll
        try:
            await page.evaluate("window.scrollBy(0, 400)")
            await asyncio.sleep(random.uniform(3, 5))
        except:
            pass

        # ── Scroll batches ──
        for batch in range(1, 15):
            prev_count = len(collected)
            log(f"\n--- Batch {batch} (total={prev_count}) ---")
            
            for i in range(4):
                try:
                    scroll_y = random.randint(250, 500)
                    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                except:
                    await asyncio.sleep(1)
                pause = random.uniform(4, 8)
                await asyncio.sleep(pause)
            await asyncio.sleep(random.uniform(5, 8))

            new_count = len(collected) - prev_count
            log(f"  New: {new_count}, Total: {len(collected)}, API calls: {sum(all_intercepted)}")

            if len(collected) >= TOTAL:
                log(f"  Target {TOTAL} reached!")
                break
            if new_count == 0 and batch >= 4:
                log(f"  No new data for 4 batches, stopping")
                break

            await asyncio.sleep(random.uniform(8, 15))

        await browser.close()

    log(f"\n{'='*60}")
    log(f"Done: {len(collected)} videos from {len(all_intercepted)} batches")

    if collected:
        out = {
            "keyword": KEYWORD,
            "fetch_time": datetime.now().isoformat(),
            "total": len(collected),
            "videos": collected,
        }
        RAW_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"Saved: {RAW_FILE}")

        log("\n--- Sample (first 5) ---")
        for i, v in enumerate(collected[:5], 1):
            log(f"  [{i}] {v.get('desc','')[:60]}")
            a = v.get("author", {})
            s = v.get("statistics", {})
            log(f"      Author: {a.get('nickname','?')} | Likes: {s.get('digg_count',0):,} | Comments: {s.get('comment_count',0):,}")
    else:
        log("WARNING: No data collected")

if __name__ == "__main__":
    asyncio.run(main())
