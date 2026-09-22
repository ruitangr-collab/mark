"""
fetch_followers.py — 补采作者粉丝数
读取 business_data/ 所有 JSON，提取唯一作者，
对未缓存的作者调用用户主页 API 获取粉丝数，写回各 JSON。
"""

import json, time, re, os, sys
from pathlib import Path

WORK_DIR   = Path(r"C:\Users\53185\.workbuddy\skills\douyin-report-search")
CACHE_FILE = WORK_DIR / "author_profiles_cache.json"
DATA_DIR   = WORK_DIR / "business_data"

# ── 加载 Playwright ──────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("请先安装 playwright: pip install playwright"); sys.exit(1)

# ── 参数 ──────────────────────────────────────────────────────────────────
AUTHOR_MIN_PAUSE = 3
AUTHOR_MAX_PAUSE = 7
BATCH_SIZE       = 10
BATCH_PAUSE_MIN  = 15
BATCH_PAUSE_MAX  = 30

# ── 读取缓存 ─────────────────────────────────────────────────────────────
def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 从 business_data 提取唯一作者 ───────────────────────────────────────
def collect_authors(data_dir: Path):
    authors = {}  # sec_uid -> {sec_uid, uid, nickname}
    for fpath in sorted(data_dir.glob("*.json")):
        try:
            d = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        for v in d.get("videos", []):
            a = v.get("author", {})
            sid = a.get("sec_uid", "")
            if sid and sid not in authors:
                authors[sid] = {
                    "sec_uid": sid,
                    "uid": a.get("uid", ""),
                    "nickname": a.get("nickname", ""),
                }
    return authors

# ── 从用户主页 HTML 解析粉丝数 ────────────────────────────────────────
def fetch_author(sec_uid: str, context) -> dict | None:
    """访问用户主页，从 HTML 中解析 follower_count 等字段。"""
    url = f"https://www.douyin.com/user/{sec_uid}"
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        html = page.content()
        page.close()

        # 尝试从 __NEXT_DATA__ 或 RENDER_DATA 解析
        data = None
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                pass

        # 回退：从 API 直接拿
        api_url = f"https://www.douyin.com/aweme/v1/web/user/profile/other/?sec_user_id={sec_uid}&device_platform=webapp&aid=6383"
        page2 = context.new_page()
        page2.goto(api_url, wait_until="domcontentloaded", timeout=20000)
        page2.wait_for_timeout(1500)
        try:
            api_json = json.loads(page2.content().replace("&&(", "").replace(");", ""))
            user = api_json.get("user", {})
            return {
                "follower_count": user.get("follower_count", 0),
                "following_count": user.get("following_count", 0),
                "aweme_count": user.get("aweme_count", 0),
                "total_favorited": user.get("total_favorited", 0),
                "nickname": user.get("nickname", ""),
                "signature": user.get("signature", ""),
            }
        except Exception:
            pass
        page2.close()
        return None
    except Exception as e:
        return None

# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    cache = load_cache()
    print(f"缓存中有 {len(cache)} 个作者")

    authors = collect_authors(DATA_DIR)
    print(f"business_data 中唯一作者: {len(authors)}")

    # 只保留未缓存的
    to_fetch = {s: a for s, a in authors.items() if s not in cache}
    print(f"需补采: {len(to_fetch)} 个")
    if not to_fetch:
        print("全部已有缓存，无需补采 ✓")
        return

    # 加载 session
    session_file = WORK_DIR / "douyin_session.json"
    if not session_file.exists():
        print("缺少 session 文件，请先登录"); sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            executable_path=r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe")
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        # 写入 cookies
        sdata = json.loads(session_file.read_text(encoding="utf-8"))
        for c in sdata:
            try:
                ctx.add_cookies([c])
            except Exception:
                pass

        ok = err = 0
        items = list(to_fetch.values())
        for i, author in enumerate(items, 1):
            sec_uid = author["sec_uid"]
            nickname = author.get("nickname", "")[:20]
            print(f"  [{i}/{len(items)}] {nickname} ... ", end="", flush=True)

            result = fetch_author(sec_uid, ctx)
            if result:
                cache[sec_uid] = result
                ok += 1
                print(f"✓ follower={result['follower_count']}")
            else:
                err += 1
                print("✗ 失败")

            # 每 BATCH_SIZE 个保存一次
            if i % BATCH_SIZE == 0:
                save_cache(cache)
                pause = __import__("random").uniform(BATCH_PAUSE_MIN, BATCH_PAUSE_MAX)
                print(f"  [保存缓存，休息 {pause:.0f}s]")
                time.sleep(pause)

            else:
                time.sleep(__import__("random").uniform(AUTHOR_MIN_PAUSE, AUTHOR_MAX_PAUSE))

        save_cache(cache)
        browser.close()
        print(f"\n完成! 成功: {ok}, 失败: {err}, 缓存总数: {len(cache)}")

if __name__ == "__main__":
    main()
