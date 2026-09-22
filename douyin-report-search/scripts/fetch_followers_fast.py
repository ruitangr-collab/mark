"""
fetch_followers_fast.py — 高速补采作者粉丝数（HTTP 直调 API）
读取 business_data/ 所有 JSON → 提取唯一作者 → 对未缓存的调 profile API → 写回各 JSON
"""

import json, time, os, sys, random
from pathlib import Path

WORK_DIR   = Path(r"C:\Users\53185\.workbuddy\skills\douyin-report-search")
CACHE_FILE = WORK_DIR / "author_profiles_cache.json"
DATA_DIR   = WORK_DIR / "business_data"

# ── 请求参数 ────────────────────────────────────────────────────────────
REQ_MIN_PAUSE  = 0.8   # 请求间隔下限（秒）
REQ_MAX_PAUSE  = 2.5   # 请求间隔上限（秒）
BATCH_SIZE     = 20    # 每批保存一次缓存
BATCH_PAUSE   = (8, 20)  # 批次间休息（秒）

# ── 加载 / 保存缓存 ─────────────────────────────────────────────────────
def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 从 business_data 提取唯一作者 ─────────────────────────────────────
def collect_authors(data_dir: Path):
    authors = {}
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

# ── 加载 session cookies ────────────────────────────────────────────────
def load_cookies():
    sf = WORK_DIR / "douyin_session.json"
    if not sf.exists():
        print("缺少 session 文件，请先登录"); sys.exit(1)
    raw = json.loads(sf.read_text(encoding="utf-8"))
    cookies = {}
    for c in raw:
        cookies[c["name"]] = c["value"]
    return cookies

# ── 调 profile API ───────────────────────────────────────────────────────
def fetch_one(sec_uid: str, session, headers) -> dict | None:
    url = "https://www.douyin.com/aweme/v1/web/user/profile/other/"
    params = {
        "sec_user_id": sec_uid,
        "device_platform": "webapp",
        "aid": "6383",
        "version_name": "2.0.0",
        "os_type": "0",
        "ssmix": "a",
        "timestamp": int(time.time()),
    }
    try:
        resp = session.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("user", {})
            if user:
                return {
                    "follower_count":  user.get("follower_count", 0),
                    "following_count": user.get("following_count", 0),
                    "aweme_count":    user.get("aweme_count", 0),
                    "total_favorited": user.get("total_favorited", 0),
                    "nickname":        user.get("nickname", ""),
                    "signature":       user.get("signature", ""),
                }
        elif resp.status_code == 403 or resp.status_code == 429:
            print(f"  [限流 {resp.status_code}]", end="", flush=True)
            return "rate_limited"  # 特殊标记
    except Exception as e:
        pass
    return None

# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    import requests

    cache = load_cache()
    print(f"缓存中有 {len(cache)} 个作者")

    authors = collect_authors(DATA_DIR)
    print(f"business_data 中唯一作者: {len(authors)}")

    to_fetch = {s: a for s, a in authors.items() if s not in cache}
    print(f"需补采: {len(to_fetch)} 个")
    if not to_fetch:
        print("全部已有缓存，无需补采 ✓")
        return

    cookies = load_cookies()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
    }

    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update(headers)

    ok = err = rate_limited = 0
    items = list(to_fetch.values())

    print(f"开始补采，间隔 {REQ_MIN_PAUSE}-{REQ_MAX_PAUSE}s ...")
    for i, author in enumerate(items, 1):
        sec_uid = author["sec_uid"]
        nickname = author.get("nickname", "")[:20]
        print(f"  [{i}/{len(items)}] {nickname} ... ", end="", flush=True)

        result = fetch_one(sec_uid, s, headers)
        if result == "rate_limited":
            rate_limited += 1
            print("✗ 限流")
            # 遇到限流，休息久一点
            time.sleep(random.uniform(30, 60))
        elif result:
            cache[sec_uid] = result
            ok += 1
            print(f"✓ follower={result['follower_count']}")
        else:
            err += 1
            print("✗ 失败")

        # 每 BATCH_SIZE 个保存一次
        if i % BATCH_SIZE == 0:
            save_cache(cache)
            pause = random.uniform(*BATCH_PAUSE)
            print(f"  [保存缓存 {len(cache)} 条，休息 {pause:.0f}s]")
            time.sleep(pause)
        else:
            time.sleep(random.uniform(REQ_MIN_PAUSE, REQ_MAX_PAUSE))

        # 限流太多就暂停
        if rate_limited >= 5:
            print("\n⚠️ 触发限流次数过多，暂停 5 分钟...")
            time.sleep(300)
            rate_limited = 0

    save_cache(cache)
    print(f"\n完成! 成功: {ok}, 失败: {err}, 限流: {rate_limited}, 缓存总数: {len(cache)}")

if __name__ == "__main__":
    main()
