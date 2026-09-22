"""Quick test: intercept comment API from one video page."""
import json, sys, time, re
from pathlib import Path

WORK_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
SESSION_FILE = WORK_DIR / "douyin_session.json"
CHROMIUM_PATH = r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe"

def log(msg):
    sys.stdout.buffer.write(f"{msg}\n".encode("utf-8"))
    sys.stdout.buffer.flush()

def main():
    from playwright.sync_api import sync_playwright

    # Test video: "非洲十年" with 19568 comments
    aweme_id = "7040089226792209677"

    log(f"测试视频: https://www.douyin.com/video/{aweme_id}")

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(executable_path=CHROMIUM_PATH, headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        
        if SESSION_FILE.exists():
            saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            cookies = saved if isinstance(saved, list) else saved.get("cookies", [])
            context.add_cookies(cookies)
            log("已加载 session cookies")

        page = context.new_page()

        # Log ALL responses that match "comment"
        all_comment_urls = []
        def log_response(resp):
            url = resp.url
            if "comment" in url.lower():
                all_comment_urls.append(url)
                log(f"  [comment response] {url[:120]}")
            if "aweme/v1/web" in url:
                log(f"  [aweme web response] {url[:150]}")

        page.on("response", log_response)

        log("正在打开视频页面...")
        try:
            page.goto(f"https://www.douyin.com/video/{aweme_id}", wait_until="networkidle", timeout=30000)
        except:
            log("  页面加载超时，继续...")

        log("等待 5 秒让评论加载...")
        time.sleep(5)

        # Scroll down to trigger lazy-load
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(3)
        page.evaluate("window.scrollTo(0, 1200)")
        time.sleep(3)

        log(f"\n共捕获 {len(all_comment_urls)} 个 comment 相关请求:")
        for u in all_comment_urls:
            log(f"  {u}")

        # Also check page content for comment section
        try:
            cmt_section = page.query_selector('[class*="comment"]')
            if cmt_section:
                log(f"\n页面中有评论区块")
            else:
                log(f"\n未找到评论区块")
        except:
            pass

        input("按 Enter 关闭浏览器...")

    finally:
        browser.close()
        pw.stop()

if __name__ == "__main__":
    main()
