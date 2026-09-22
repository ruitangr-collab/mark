#!/usr/bin/env python3
"""Fetch comments: intercept comment/list API with page.route(), bump count to 20."""

import json, re, sys, time
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse, urlunparse

WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
RAW_FILE = WORK_DIR / "douyin_raw_data.json"
SESSION_FILE = WORK_DIR / "douyin_session.json"
COMMENT_CACHE = WORK_DIR / "comment_cache.json"
CHROMIUM_PATH = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"
MAX_VIDEOS = 30
DELAY = 2.5

def log(msg):
    sys.stdout.buffer.write(f"{msg}\n".encode("utf-8"))
    sys.stdout.buffer.flush()

def clean_text(s):
    if not s: return ""
    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("\n"," ").replace("\r"," ").strip()

def main():
    from playwright.sync_api import sync_playwright

    log("加载视频数据...")
    d = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    videos = d.get("videos", [])
    sorted_videos = sorted(videos,
        key=lambda v: int(v.get("_raw",{}).get("statistics",{}).get("comment_count",0)),
        reverse=True)[:MAX_VIDEOS]
    log(f"待处理: {len(sorted_videos)} 条")

    # 缓存
    if COMMENT_CACHE.exists():
        cached = json.loads(COMMENT_CACHE.read_text(encoding="utf-8"))
        cached = {k:v for k,v in cached.items() if v and len(v)>0}
    else:
        cached = {}
    log(f"有效缓存: {len(cached)}")

    todo = [v for v in sorted_videos if v.get("aweme_id") not in cached]
    log(f"需获取: {len(todo)}")

    if not todo:
        log("全部已缓存")
        return

    log("启动浏览器...")
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(executable_path=CHROMIUM_PATH, headless=False)
        ctx = browser.new_context(viewport={"width":1280,"height":800})
        if SESSION_FILE.exists():
            saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            cookies = saved if isinstance(saved, list) else saved.get("cookies",[])
            ctx.add_cookies(cookies)

        page = ctx.new_page()

        # Per-video comment store
        current_aweme_id = [None]
        current_comments = [[]]

        def handle_route(route):
            url = route.request.url
            if "/comment/list/" in url:
                # Parse URL, bump count to 20
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                qs["count"] = ["20"]
                new_qs = urlencode(qs, doseq=True)
                new_url = urlunparse(parsed._replace(query=new_qs))
                try:
                    resp = route.fetch(url=new_url) if new_url != url else route.fetch()
                    body_text = resp.body().decode("utf-8")
                    data = json.loads(body_text)
                    comments_raw = data.get("comments",[]) or []
                    # Parse and store per aweme_id
                    for cmt in comments_raw:
                        user = cmt.get("user",{})
                        current_comments[0].append({
                            "nickname": user.get("nickname",""),
                            "text": clean_text(cmt.get("text","")),
                            "digg_count": cmt.get("digg_count",0),
                            "reply_count": cmt.get("reply_comment_total",0),
                        })
                    route.fulfill(response=resp)
                except Exception:
                    route.continue_()
            else:
                route.continue_()

        page.route("**/aweme/v1/web/comment/list/**", handle_route)

        new_count = 0
        for i, v in enumerate(todo):
            aweme_id = v.get("aweme_id","")
            if not aweme_id: continue

            nickname = v.get("_raw",{}).get("author",{}).get("nickname","?")
            cmt_count = int(v.get("_raw",{}).get("statistics",{}).get("comment_count",0))
            desc = clean_text(v.get("_raw",{}).get("desc",""))[:50]

            log(f"[{i+1}/{len(todo)}] {nickname} | {desc} | {cmt_count}评")

            current_comments[0] = []

            try:
                page.goto(f"https://www.douyin.com/video/{aweme_id}",
                          wait_until="domcontentloaded", timeout=20000)
                time.sleep(3)
                # Scroll to comment section
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.4)")
                time.sleep(2)
                # Scroll more
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
                time.sleep(2)

                if current_comments[0]:
                    cached[aweme_id] = current_comments[0]
                    new_count += 1
                    log(f"  ✓ {len(current_comments[0])} 条评论")
                else:
                    cached[aweme_id] = []
                    log(f"  ⚠ 无评论")

            except Exception as e:
                log(f"  ❌ {e}")
                cached[aweme_id] = []

            if (i+1) % 5 == 0:
                COMMENT_CACHE.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding="utf-8")
                log(f"  💾 ({len(cached)} v, {new_count} new)")

            time.sleep(DELAY)

        COMMENT_CACHE.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding="utf-8")
        total = sum(len(vlist) for vlist in cached.values())
        log(f"\n完成！{len(cached)}视频 | {new_count}新 | {total}条评论")

    finally:
        browser.close()
        pw.stop()

if __name__ == "__main__":
    main()
