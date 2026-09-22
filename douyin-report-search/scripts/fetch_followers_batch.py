"""
fetch_followers_batch.py — 分批补采作者粉丝数（自动重登录）

用法:
  python fetch_followers_batch.py           # 默认每批 500 个
  python fetch_followers_batch.py --batch-size 300  # 自定义批次大小
"""

import json, time, os, sys, subprocess, argparse, random
from pathlib import Path

WORK_DIR   = Path(r"C:\Users\53185\.workbuddy\skills\douyin-report-search")
SCRIPTS_DIR = WORK_DIR / "scripts"
CACHE_FILE = WORK_DIR / "author_profiles_cache.json"
DATA_DIR   = WORK_DIR / "business_data"

# ── 请求参数（和 fetch_followers_fast.py 一致）────────────────────────
REQ_MIN_PAUSE  = 0.8
REQ_MAX_PAUSE  = 2.5
BATCH_SIZE     = 20
BATCH_PAUSE   = (8, 20)

def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def collect_authors(data_dir: Path):
    """从 business_data 提取唯一作者"""
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

def load_cookies():
    sf = WORK_DIR / "douyin_session.json"
    if not sf.exists():
        print("缺少 session 文件，请先登录"); sys.exit(1)
    raw = json.loads(sf.read_text(encoding="utf-8"))
    cookies = {}
    for c in raw:
        cookies[c["name"]] = c["value"]
    return cookies

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
        elif resp.status_code in (403, 429):
            return "rate_limited"
    except Exception:
        pass
    return None

def re_login():
    """重新登录刷新 session"""
    print("\n" + "="*60)
    print("🔄 重新登录刷新 session ...")
    print("="*60)
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "douyin_login.py"), str(WORK_DIR)],
            cwd=str(SCRIPTS_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
        )
        if result.returncode == 0 and "登录成功" in result.stdout:
            print("✓ 重新登录成功")
            return True
        else:
            print(f"✗ 登录失败: {result.stdout[-200:]}")
            return False
    except Exception as e:
        print(f"✗ 登录异常: {e}")
        return False

def run_batch(batch_size: int):
    """运行一个批次，最多处理 batch_size 个作者"""
    cache = load_cache()
    authors = collect_authors(DATA_DIR)
    
    to_fetch = {s: a for s, a in authors.items() if s not in cache}
    
    if not to_fetch:
        print("✓ 全部已有缓存，无需补采")
        return 0, 0, 0  # ok, err, remaining
    
    # 只取前 batch_size 个
    items = list(to_fetch.values())[:batch_size]
    
    print(f"缓存: {len(cache)} | 待补: {len(to_fetch)} | 本批: {len(items)}")
    
    cookies = load_cookies()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
    }
    
    import requests
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update(headers)
    
    ok = err = rate_limited = 0
    
    print(f"开始补采 (间隔 {REQ_MIN_PAUSE}-{REQ_MAX_PAUSE}s) ...")
    for i, author in enumerate(items, 1):
        sec_uid = author["sec_uid"]
        nickname = author.get("nickname", "")[:20]
        print(f"  [{i}/{len(items)}] {nickname} ... ", end="", flush=True)
        
        result = fetch_one(sec_uid, s, headers)
        if result == "rate_limited":
            rate_limited += 1
            print("✗ 限流")
            time.sleep(random.uniform(30, 60))
        elif result:
            cache[sec_uid] = result
            ok += 1
            print(f"✓ follower={result['follower_count']}")
        else:
            err += 1
            print("✗ 失败")
        
        if i % BATCH_SIZE == 0:
            save_cache(cache)
            pause = random.uniform(*BATCH_PAUSE)
            print(f"  [保存缓存 {len(cache)} 条，休息 {pause:.0f}s]")
            time.sleep(pause)
        else:
            time.sleep(random.uniform(REQ_MIN_PAUSE, REQ_MAX_PAUSE))
        
        if rate_limited >= 5:
            print("\n⚠️ 触发限流次数过多，暂停 5 分钟...")
            time.sleep(300)
            rate_limited = 0
    
    save_cache(cache)
    
    # 计算剩余
    remaining = len(to_fetch) - len(items)
    
    print(f"\n批次完成! 成功: {ok}, 失败: {err}, 限流: {rate_limited}")
    print(f"缓存总数: {len(cache)} | 剩余: {remaining}")
    
    return ok, err, remaining

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500, help="每批处理作者数 (默认 500)")
    args = parser.parse_args()
    
    batch_size = args.batch_size
    total_ok = total_err = 0
    batch_num = 0
    
    print("="*60)
    print("分批补采作者粉丝数")
    print(f"批次大小: {batch_size}")
    print("="*60)
    
    while True:
        batch_num += 1
        
        # 检查剩余
        cache = load_cache()
        authors = collect_authors(DATA_DIR)
        to_fetch_count = sum(1 for s in authors if s not in cache)
        
        if to_fetch_count == 0:
            print("\n" + "="*60)
            print("✓ 全部补采完成!")
            print(f"总成功: {total_ok}, 总失败: {total_err}")
            print("="*60)
            break
        
        print(f"\n{'='*60}")
        print(f"批次 #{batch_num} (剩余 {to_fetch_count} 个)")
        print("="*60)
        
        # 如果剩余少于 batch_size，直接跑完
        actual_batch = min(batch_size, to_fetch_count)
        
        ok, err, remaining = run_batch(actual_batch)
        total_ok += ok
        total_err += err
        
        if remaining > 0:
            # 需要继续，先重新登录
            if not re_login():
                print("✗ 重新登录失败，停止")
                break
            # 短暂休息
            rest = random.uniform(10, 20)
            print(f"休息 {rest:.0f}s 后继续下一批次...")
            time.sleep(rest)
        else:
            print("\n✓ 本批次已全部完成!")
            # 再检查一次是否还有剩余（可能上一批没跑完）
            cache = load_cache()
            authors = collect_authors(DATA_DIR)
            to_fetch_count = sum(1 for s in authors if s not in cache)
            if to_fetch_count > 0:
                print(f"还有 {to_fetch_count} 个未缓存，继续...")
                if not re_login():
                    print("✗ 重新登录失败，停止")
                    break
            else:
                print("\n" + "="*60)
                print("✓ 全部补采完成!")
                print(f"总成功: {total_ok}, 总失败: {total_err}")
                print("="*60)
                break

if __name__ == "__main__":
    main()
