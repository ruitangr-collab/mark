#!/usr/bin/env python3
"""
抖音关键词/话题评论提取脚本
用法: python3 keyword_extract.py <关键词> [max_videos] [--minimized]

功能:
  1. 访问抖音搜索页（视频 tab），提取视频列表
  2. 逐个视频滚动加载评论
  3. 输出到 ~/.workbuddy/douyin_analysis/keyword_<关键词>/，兼容 analyze.py

兼容性说明（2026-09 验证）:
  - RENDER_DATA 已从 base64 改为 URL 编码，自动兼容两种格式
  - 登录态判断用 RENDER_DATA 的 app.user.isLogin 字段，避免"扫码"字样误判
  - 未登录时搜索结果为异步接口加载，RENDER_DATA 无视频数据 → 必须登录
  - 视频链接为 //www.douyin.com/video/<id> 相对协议形式
  - headless 会被风控拿不到数据，定时任务用 --minimized
"""
import sys, json, re, time
from pathlib import Path
from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    get_render_data, is_logged_in, wait_for_login,
    extract_comments_from_page,
)

PROFILE_DIR = Path.home() / ".workbuddy/douyin_chrome_profile"
OUTPUT_BASE = Path.home() / ".workbuddy/douyin_analysis"


def find_videos_via_search(page, keyword: str, max_videos: int) -> list[str]:
    """从搜索页提取视频 aweme_id 列表（含加载失败自愈）"""
    print(f"[搜索] 关键词: {keyword}")
    page.get(f"https://www.douyin.com/search/{keyword}?type=video")
    time.sleep(12)

    # 自愈：空壳页(只有导航+页脚, HTML<100KB)则重新打开重试（2026-09 遇偶发加载失败）
    for attempt in range(2):
        if len(page.html) > 100000:
            break
        print(f"  ⚠️ 搜索页未加载完整(HTML {len(page.html)//1024}KB)，重试({attempt + 1}/2)...")
        page.get(f"https://www.douyin.com/search/{keyword}?type=video")
        time.sleep(12)

    # 滚动几轮让视频加载
    for _ in range(6):
        page.scroll.down(600)
        time.sleep(0.6)

    # 路径1: DOM 中的 /video/<id> 链接（2026-09 验证有效）
    html = page.html
    aweme_ids = re.findall(r'/video/(\d{15,})', html)
    if not aweme_ids:
        # 路径2: RENDER_DATA 中的 aweme_id（旧版）
        decoded = get_render_data(page)
        if decoded:
            aweme_ids = re.findall(r'"aweme_id"\s*:\s*"(\d{15,})"', decoded)

    aweme_ids = list(dict.fromkeys(aweme_ids))[:max_videos]
    print(f"  ✅ 找到 {len(aweme_ids)} 个视频: {aweme_ids[:5]}{'...' if len(aweme_ids) > 5 else ''}")
    return aweme_ids


def main():
    if len(sys.argv) < 2:
        print("用法: python3 keyword_extract.py <关键词> [max_videos] [--minimized]")
        sys.exit(1)

    keyword = sys.argv[1]
    max_videos = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    minimized = '--minimized' in sys.argv

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--window-size=1920,1080')
    co.set_argument(f'--user-data-dir={PROFILE_DIR}')
    if minimized:
        co.set_argument('--start-minimized')
    co.headless(False)

    page = ChromiumPage(co)
    try:
        print("[1] 打开抖音首页检查登录态...")
        page.get("https://www.douyin.com")
        time.sleep(4)
        if not wait_for_login(page):
            print("无法继续，请重新运行脚本并扫码登录")
            sys.exit(1)

        video_ids = find_videos_via_search(page, keyword, max_videos)
        if not video_ids:
            sys.exit(1)

        dir_name = f"keyword_{keyword}"
        OUTPUT_DIR = OUTPUT_BASE / dir_name
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        all_comments = []
        print(f"\n[2] 开始提取 {len(video_ids)} 个视频的评论...")

        for i, vid in enumerate(video_ids, 1):
            url = f"https://www.douyin.com/video/{vid}"
            print(f"\n  📹 [{i}/{len(video_ids)}] {vid}")
            page.get(url)
            time.sleep(5)
            for _ in range(60):
                page.scroll.down(400)
                time.sleep(0.2)
            comments = extract_comments_from_page(page)
            print(f"    提取到 {len(comments)} 条")

            with open(OUTPUT_DIR / f"video_{vid}_comments.json", 'w', encoding='utf-8') as f:
                json.dump(comments, f, ensure_ascii=False, indent=2)

            all_comments.extend(comments)

        final = list(dict.fromkeys(all_comments))
        with open(OUTPUT_DIR / "all_comments.json", 'w', encoding='utf-8') as f:
            json.dump(final, f, ensure_ascii=False, indent=2)

        with open(OUTPUT_DIR / "meta.json", 'w', encoding='utf-8') as f:
            json.dump({
                "keyword": keyword,
                "video_ids": video_ids,
                "comment_count": len(final),
                "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 完成！共提取 {len(final)} 条去重评论")
        print(f"   结果: {OUTPUT_DIR / 'all_comments.json'}")
    finally:
        page.quit()


if __name__ == '__main__':
    main()
