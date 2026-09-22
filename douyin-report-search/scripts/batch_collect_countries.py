#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量采集20个非洲国家的抖音视频数据 v2
- 先打开浏览器等待用户手动过验证码
- 验证通过后自动采集所有关键词
"""

import asyncio, json, time, random, urllib.parse, sys, os, re
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
SESSION_FILE = WORK_DIR / "douyin_session.json"
OUT_DIR = WORK_DIR / "country_data"
CHROMIUM = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

def log(msg):
    sys.stdout.buffer.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n".encode('utf-8'))
    sys.stdout.buffer.flush()

def load_keywords():
    kw_file = WORK_DIR / "scripts" / "country_keywords.json"
    return json.loads(kw_file.read_text(encoding="utf-8"))

async def collect_one_keyword(page, keyword, target_count, country, filename):
    """采集单个关键词的视频数据"""
    collected = []
    collected_ids = set()

    async def handle_route(route, request):
        resp = await route.fetch()
        url = request.url
        if "search/item" in url:
            try:
                body_bytes = await resp.body()
                body = json.loads(body_bytes.decode("utf-8"))
                data_arr = body.get("data") or []
                for item in data_arr:
                    if item.get("type") == 1 and item.get("aweme_info"):
                        info = item["aweme_info"]
                        aid = info.get("aweme_id", "")
                        if aid and aid not in collected_ids:
                            collected_ids.add(aid)
                            collected.append({
                                "aweme_id": aid,
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
            except Exception as e:
                log(f"    parse err: {e}")
        await route.fulfill(response=resp)

    await page.route("**/aweme/v1/web/search/item/**", handle_route)

    enc_kw = urllib.parse.quote(keyword)
    log(f"  Opening: {keyword}")
    
    # Retry navigation up to 3 times
    nav_ok = False
    for nav_try in range(3):
        try:
            await page.goto(f"https://www.douyin.com/search/{enc_kw}?type=video",
                           wait_until="domcontentloaded", timeout=30000)
            nav_ok = True
            break
        except:
            log(f"  Nav timeout (attempt {nav_try+1}/3), retrying...")
            await asyncio.sleep(3)
    
    if not nav_ok:
        log("  !! Navigation failed after 3 attempts, skipping")
        await page.unroute("**/aweme/v1/web/search/item/**")
        return 0
    
    # Check for captcha after navigation
    captcha_waited = 0
    while captcha_waited < 60:
        try:
            title = await page.title()
            if "验证" in title or "captcha" in title.lower() or "verify" in title.lower():
                if captcha_waited == 0:
                    log("  *** 验证码出现！请在浏览器中完成验证 ***")
                await asyncio.sleep(5)
                captcha_waited += 5
            else:
                break
        except:
            break
    
    if captcha_waited >= 60:
        log("  !! 验证码超时，跳过此关键词")
        await page.unroute("**/aweme/v1/web/search/item/**")
        return 0

    # Human-like: wait for page to fully render after navigation (conservative)
    await asyncio.sleep(random.uniform(6, 10))
    
    # Simulate human reading: slow initial scroll
    try:
        await page.evaluate("window.scrollBy(0, 400)")
        await asyncio.sleep(random.uniform(3, 5))
    except:
        pass

    for batch in range(1, 12):
        try:
            prev_count = len(collected)
            # Human-like: scroll 4 times with long random pauses
            for i in range(4):
                try:
                    scroll_y = random.randint(250, 500)
                    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                except Exception:
                    await asyncio.sleep(1)
                # Conservative pause: all scrolls at human reading speed
                pause = random.uniform(4, 8)
                await asyncio.sleep(pause)
            
            # After batch: simulate reading/thinking pause
            await asyncio.sleep(random.uniform(5, 8))
            new_count = len(collected) - prev_count
            log(f"    batch {batch}: +{new_count}, total={len(collected)}")
            if len(collected) >= target_count:
                break
            if new_count == 0 and batch >= 4:
                break
            # Long pause between batches
            await asyncio.sleep(random.uniform(8, 15))
        except Exception as e:
            log(f"  Scroll err in batch {batch}: {e}")
            break

    await page.unroute("**/aweme/v1/web/search/item/**")

    out = {
        "keyword": keyword,
        "country": country,
        "fetch_time": datetime.now().isoformat(),
        "total": len(collected),
        "videos": collected,
    }
    filepath = OUT_DIR / filename
    filepath.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  Saved: {filename} ({len(collected)} videos)")
    return len(collected)

async def main():
    if not SESSION_FILE.exists():
        log("ERROR: No session file")
        return

    OUT_DIR.mkdir(exist_ok=True)
    countries = load_keywords()
    total_kw = sum(len(c["keywords"]) for c in countries)
    log("=" * 60)
    log(f"Batch Collect: {len(countries)} countries, {total_kw} keywords")
    log("=" * 60)

    async with async_playwright() as p:
        launch_kw = {
            "headless": False,
            "args": ["--start-maximized","--disable-blink-features=AutomationControlled","--no-sandbox"],
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
        log(f"Cookies loaded: {len(cookies)}")

        page = await ctx.new_page()

        # Brief human-like delay before first navigation
        await asyncio.sleep(random.uniform(2, 4))

        # ── Step 1: Navigate to first search page and wait for manual captcha ──
        test_kw = countries[0]["keywords"][0]
        enc_test = urllib.parse.quote(test_kw)
        test_url = f"https://www.douyin.com/search/{enc_test}?type=video"
        log(f"\n>>> 打开测试页面: {test_kw}")
        log(f">>> 如果弹出验证码，请手动完成！完成后脚本会自动继续...")
        await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Poll for captcha completion (max 300 seconds = 5 min)
        waited = 0
        while waited < 300:
            title = await page.title()
            if "验证" not in title.lower() and "captcha" not in title.lower():
                # Also check that we're on a normal page
                url = page.url
                if "search" in url:
                    log(f">>> 页面正常！title='{title}' 开始采集...")
                    break
            if waited % 15 == 0 and waited > 0:
                log(f">>> 等待验证码... ({waited}s)")
            await asyncio.sleep(3)
            waited += 3
        
        if waited >= 120:
            log("ERROR: 等待验证码超时（300秒），退出")
            await browser.close()
            return

        # ── Step 2: Now collect all keywords sequentially ──
        grand_total = 0
        kw_idx = 0

        prev_country = None
        for country_entry in countries:
            country = country_entry["country"]
            tier = country_entry["tier"]
            target = {1: 80, 2: 60, 3: 50, 4: 50}.get(tier, 50)
            
            # Extra pause between countries to look like a human switching topics
            if prev_country:
                log(f"  [Country transition pause: 25-40s]")
                await asyncio.sleep(random.uniform(25, 40))
            prev_country = country
            
            log(f"\n{'='*50}")
            log(f"Tier{tier} [{country}] {len(country_entry['keywords'])} keywords, target={target}/kw")
            log(f"{'='*50}")

            for kw in country_entry["keywords"]:
                kw_idx += 1
                safe_kw = kw.replace(" ", "_")
                filename = f"{country}_{safe_kw}.json"

                if (OUT_DIR / filename).exists():
                    try:
                        existing = json.loads((OUT_DIR / filename).read_text(encoding="utf-8"))
                        grand_total += existing.get("total", 0)
                    except:
                        pass
                    log(f"  [{kw_idx}/{total_kw}] SKIP {kw}")
                    continue

                log(f"  [{kw_idx}/{total_kw}] {kw}")
                try:
                    count = await asyncio.wait_for(
                        collect_one_keyword(page, kw, target, country, filename),
                        timeout=180
                    )
                    grand_total += count
                except asyncio.TimeoutError:
                    log(f"  !! TIMEOUT on {kw}, saving empty and continuing...")
                    (OUT_DIR / filename).write_text(
                        json.dumps({"keyword": kw, "country": country, "fetch_time": datetime.now().isoformat(), "total": 0, "videos": [], "error": "timeout"}, ensure_ascii=False),
                        encoding="utf-8")
                except Exception as e:
                    log(f"  !! ERROR on {kw}: {e}, saving empty and continuing...")
                    (OUT_DIR / filename).write_text(
                        json.dumps({"keyword": kw, "country": country, "fetch_time": datetime.now().isoformat(), "total": 0, "videos": [], "error": str(e)}, ensure_ascii=False),
                        encoding="utf-8")
                await asyncio.sleep(random.uniform(22, 32))  # Conservative pause between keywords

        await browser.close()

    log(f"\n{'='*60}")
    log(f"ALL DONE! {total_kw} keywords, {grand_total} total videos")
    log(f"Output dir: {OUT_DIR}")
    log(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
