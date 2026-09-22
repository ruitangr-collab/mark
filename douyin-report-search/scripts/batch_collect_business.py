#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对标矩阵 — R1 线索采集脚本（有人值守加速版）

与 batch_collect_countries.py 的核心区别:
  1. 速度加快: 词间 8-15s, 滚动 2-5s, 批次间 5-10s
  2. 验证码 = 暂停等待用户手动完成（有人值守所以等）
  3. 连续零结果 → 放宽至 20 次才退出
  4. 每轮最多 100 个关键词后自动停止（防反爬）
  5. 已采集文件自动跳过，支持断续运行
"""

import asyncio, json, time, random, urllib.parse, sys, os, re
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

# ── Paths ──
WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
SESSION_FILE = WORK_DIR / "douyin_session.json"
KW_FILE = WORK_DIR / "scripts" / "business_keywords.json"
OUT_DIR = WORK_DIR / "business_data"
CHROMIUM = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

# ── 慢速防限流参数（搜索过于频繁触发限速后已调慢）──
KW_PAUSE_MIN, KW_PAUSE_MAX = 30, 45           # 词间延迟（秒）
GROUP_PAUSE_MIN, GROUP_PAUSE_MAX = 45, 70     # 分组间延迟（秒）
SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX = 5, 10    # 每次滚动后等待
BATCH_PAUSE_MIN, BATCH_PAUSE_MAX = 8, 15      # 每批滚动后等待
BETWEEN_BATCH_MIN, BETWEEN_BATCH_MAX = 10, 20 # 批次之间等待
INITIAL_WAIT_MIN, INITIAL_WAIT_MAX = 4, 8     # 导航后首次等待
FIRST_SCROLL_MIN, FIRST_SCROLL_MAX = 2, 5     # 首次微滚动后等待
SCROLLS_PER_BATCH = 4                          # 每批滚动次数（减少）
MAX_BATCHES = 10                               # 最多批次数
MAX_KW_PER_RUN = 100                           # 单次运行最多关键词数（加速后可多跑）
EMPTY_STREAK_QUIT = 20                         # 连续零结果→退出（有人值守放宽）
NAV_TIMEOUT = 30000                            # 导航超时(ms)
CAPTCHA_MAX_WAIT = 300                          # 验证码最多等5分钟（有人值守）

# ── Utils ──
def log(msg):
    sys.stdout.buffer.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n".encode("utf-8"))
    sys.stdout.buffer.flush()

def load_keywords():
    data = json.loads(KW_FILE.read_text(encoding="utf-8"))
    return data["keywords"]

def safe_filename(kw):
    return kw.replace(" ", "_").replace("/", "_") + ".json"

# ── Core: collect one keyword ──
async def collect_one_keyword(page, keyword, target_count, filename):
    collected = []
    collected_ids = set()
    response_cnt = [0]  # mutable counter for debug

    async def handle_response(response):
        url = response.url
        if "aweme/v1/web/search/item" in url and "search/item" in url:
            response_cnt[0] += 1
            try:
                body = await response.json()
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
                            })
            except Exception:
                pass  # non-JSON responses are fine

    page.on("response", handle_response)
    enc_kw = urllib.parse.quote(keyword)

    # ── Navigate ──
    log(f"  Opening: {keyword}")
    nav_url = f"https://www.douyin.com/search/{enc_kw}?type=video"
    try:
        await page.goto(nav_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    except Exception:
        log("  !! Navigation failed, saving empty and skipping")
        return 0

    # ── Captcha check (有人值守: 等待用户手动完成) ──
    await asyncio.sleep(3)
    try:
        title = await page.title()
        if "验证" in title or "captcha" in title.lower() or "verify" in title.lower():
            log("  *** 验证码出现！等待手动完成（5分钟内）***")
            waited = 0
            while waited < 300:
                await asyncio.sleep(5)
                waited += 5
                try:
                    title2 = await page.title()
                    url2 = page.url
                    if "验证" not in title2 and "captcha" not in title2.lower() and "search" in url2:
                        log("  >>> 验证码已完成，继续采集")
                        break
                except:
                    pass
                if waited % 30 == 0:
                    log(f"  >>> 等待验证码... ({waited}s)")
            else:
                log("  !! 验证码超时 300s，跳过此词")
                return 0
    except SystemExit:
        raise
    except:
        pass

    # ── Human-like initial wait ──
    await asyncio.sleep(random.uniform(INITIAL_WAIT_MIN, INITIAL_WAIT_MAX))

    # ── First tiny scroll ──
    try:
        await page.evaluate("window.scrollBy(0, 300)")
    except:
        pass
    await asyncio.sleep(random.uniform(FIRST_SCROLL_MIN, FIRST_SCROLL_MAX))

    # ── Batch scroll loop ──
    batch = 0
    estimated_total = 0  # track estimated total results

    for batch in range(1, MAX_BATCHES + 1):
        try:
            prev_count = len(collected)

            # Check estimated total results (抖音搜索页的计数)
            try:
                total_text = await page.evaluate("""
                    () => {
                        const el = document.querySelector('[data-e2e="search-result-count"]');
                        if (el) return el.textContent;
                        const spans = document.querySelectorAll('span');
                        for (const s of spans) {
                            if (s.textContent.includes('条结果') || s.textContent.includes('条视频')) {
                                return s.textContent;
                            }
                        }
                        return '';
                    }
                """)
                if total_text:
                    log(f"    page info: {total_text.strip()}")
            except:
                pass

            # Slow human-like scrolls
            for i in range(SCROLLS_PER_BATCH):
                try:
                    scroll_y = random.randint(200, 450)
                    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                except:
                    await asyncio.sleep(2)
                # 每次滚动后较长停顿
                pause = random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)
                await asyncio.sleep(pause)

            # 模拟阅读停留
            await asyncio.sleep(random.uniform(BATCH_PAUSE_MIN, BATCH_PAUSE_MAX))

            new_count = len(collected) - prev_count
            log(f"    batch {batch}/{MAX_BATCHES}: +{new_count}, total={len(collected)}")

            if len(collected) >= target_count:
                log(f"    target reached ({target_count})")
                break
            if new_count == 0 and batch >= 5:
                log(f"    no new results in 2+ batches, stopping")
                break

            # 批次间较长停顿
            between_pause = random.uniform(BETWEEN_BATCH_MIN, BETWEEN_BATCH_MAX)
            log(f"    pausing {between_pause:.0f}s...")
            await asyncio.sleep(between_pause)

        except SystemExit:
            raise
        except Exception as e:
            log(f"  Scroll err in batch {batch}: {e}")
            break

    # ── Save ──
    out = {
        "keyword": keyword,
        "fetch_time": datetime.now().isoformat(),
        "total": len(collected),
        "videos": collected,
    }
    filepath = OUT_DIR / filename
    filepath.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  Saved: {filename} ({len(collected)} videos, {response_cnt[0]} API calls)")
    return len(collected)

# ── Main ──
async def main():
    if not SESSION_FILE.exists():
        log("ERROR: No session file. Run douyin_login.py first.")
        return

    OUT_DIR.mkdir(exist_ok=True)
    all_keywords = load_keywords()
    total_kw = len(all_keywords)

    # ── Build run queue: skip only if already has data ──
    queue = []
    skipped = 0
    for kw_entry in all_keywords:
        fname = safe_filename(kw_entry["keyword"])
        fpath = OUT_DIR / fname
        if fpath.exists():
            try:
                existing = json.loads(fpath.read_text(encoding="utf-8"))
                if existing.get("total", 0) > 0:
                    skipped += 1  # 有数据，跳过
                else:
                    log(f"  [空结果，重新采集] {fname}")
                    queue.append(kw_entry)
            except Exception:
                queue.append(kw_entry)  # 读取出错，重新采集
        else:
            queue.append(kw_entry)

    run_count = min(len(queue), MAX_KW_PER_RUN)
    log("=" * 60)
    log(f"对标矩阵 R1 线索采集 — 有人值守加速模式")
    log(f"总关键词: {total_kw} | 已完成: {skipped} | 本轮: {run_count}/{len(queue)}")
    log(f"词间延迟: {KW_PAUSE_MIN}-{KW_PAUSE_MAX}s | 组间延迟: {GROUP_PAUSE_MIN}-{GROUP_PAUSE_MAX}s")
    log(f"最大连续零结果退出: {EMPTY_STREAK_QUIT} | 自动停止上线: {MAX_KW_PER_RUN}词/轮")
    log("=" * 60)

    if not queue:
        log("All keywords collected! Nothing to do.")
        return

    # ── Launch browser ──
    async with async_playwright() as p:
        launch_kw = {
            "headless": False,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        }
        if os.path.exists(CHROMIUM):
            launch_kw["executable_path"] = CHROMIUM
        browser = await p.chromium.launch(**launch_kw)

        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        cookies = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        await ctx.add_cookies([
            {"name": c["name"], "value": c["value"],
             "domain": c.get("domain", ".douyin.com"),
             "path": c.get("path", "/")} for c in cookies
        ])
        log(f"Session loaded: {len(cookies)} cookies")

        page = await ctx.new_page()
        await asyncio.sleep(random.uniform(3, 6))

        # ── Initial navigation & captcha check ──
        first_kw = queue[0]["keyword"]
        enc_first = urllib.parse.quote(first_kw)
        log(f"\n>>> 打开首个搜索页: {first_kw}")
        log(f">>> 有人值守模式，如出现验证码请手动完成（等最多5分钟）")
        await page.goto(
            f"https://www.douyin.com/search/{enc_first}?type=video",
            wait_until="domcontentloaded", timeout=NAV_TIMEOUT
        )

        # Wait for manual captcha (max 5 min)
        captcha_waited = 0
        while captcha_waited < 300:
            try:
                title = await page.title()
                url = page.url
                if "验证" not in title and "captcha" not in title.lower() and "search" in url:
                    log(f">>> 页面正常，开始采集")
                    break
            except:
                pass
            if captcha_waited % 30 == 0 and captcha_waited > 0:
                log(f">>> 等待验证码... ({captcha_waited}s)")
            await asyncio.sleep(5)
            captcha_waited += 5

        if captcha_waited >= 300:
            log("ERROR: 验证码超时（300s），退出")
            await browser.close()
            return

        # ── Collect loop ──
        grand_total = 0
        kw_idx = 0
        zero_streak = 0
        prev_group = None

        for entry in queue[:run_count]:
            kw_idx += 1
            keyword = entry["keyword"]
            group = entry["group"]
            target = entry["target"]
            filename = safe_filename(keyword)

            # Group transition pause
            if prev_group and group != prev_group:
                gp = random.uniform(GROUP_PAUSE_MIN, GROUP_PAUSE_MAX)
                log(f"\n  [切换分组: {prev_group} → {group}, 等待 {gp:.0f}s]")
                await asyncio.sleep(gp)
            prev_group = group

            log(f"\n  [{kw_idx}/{run_count}] group={group} | {keyword} | target={target}")

            try:
                count = await asyncio.wait_for(
                    collect_one_keyword(page, keyword, target, filename),
                    timeout=600  # 10分钟，加速后足够
                )
                grand_total += count

                if count == 0:
                    zero_streak += 1
                    log(f"  empty streak: {zero_streak}/{EMPTY_STREAK_QUIT}")
                    if zero_streak >= EMPTY_STREAK_QUIT:
                        log(f"  !! 连续 {EMPTY_STREAK_QUIT} 个关键词零结果，session 可能过期，退出")
                        break
                else:
                    zero_streak = 0

            except SystemExit:
                log("  Captcha detected, exiting gracefully...")
                await browser.close()
                log(f"Progress saved. {kw_idx - 1}/{run_count} keywords collected this run.")
                log(f"Next time: delete the captcha-triggered keyword's .json file and restart.")
                return

            except asyncio.TimeoutError:
                log(f"  !! TIMEOUT (15min)")
                # 检查是否已有有效数据（collect_one_keyword 可能在超时前保存了部分）
                filepath = OUT_DIR / filename
                if filepath.exists():
                    try:
                        existing = json.loads(filepath.read_text(encoding="utf-8"))
                        if existing.get("videos") and len(existing["videos"]) > 0:
                            log(f"  Found {len(existing['videos'])} already-saved videos, keeping")
                            grand_total += len(existing["videos"])
                            zero_streak = 0
                            continue
                    except:
                        pass
                # 确实没数据才写空文件
                log(f"  No data captured, saving empty")
                zero_streak += 1
                filepath.write_text(
                    json.dumps({
                        "keyword": keyword, "fetch_time": datetime.now().isoformat(),
                        "total": 0, "videos": [], "error": "timeout"
                    }, ensure_ascii=False),
                    encoding="utf-8")
                if zero_streak >= EMPTY_STREAK_QUIT:
                    log(f"  !! 连续 {EMPTY_STREAK_QUIT} 超时/零结果，退出")
                    break

            except Exception as e:
                log(f"  !! ERROR: {e}")
                zero_streak += 1
                (OUT_DIR / filename).write_text(
                    json.dumps({
                        "keyword": keyword, "fetch_time": datetime.now().isoformat(),
                        "total": 0, "videos": [], "error": str(e)
                    }, ensure_ascii=False),
                    encoding="utf-8")

            # Word-level pause
            kw_pause = random.uniform(KW_PAUSE_MIN, KW_PAUSE_MAX)
            log(f"  [词间等待 {kw_pause:.0f}s]")
            await asyncio.sleep(kw_pause)

        await browser.close()

    # ── Final report ──
    remaining = len(queue) - run_count
    log(f"\n{'='*60}")
    log(f"本轮完成: {kw_idx}/{run_count} 关键词, {grand_total} 条视频")
    log(f"剩余: {remaining} 关键词 (下次自动接续)")
    log(f"输出目录: {OUT_DIR}")
    log(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
