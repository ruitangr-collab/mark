"""
批量获取抖音作者信息（36 个核心字段）。
利用已有 session cookie 直接调用作者信息 API（使用标准库 urllib，无需 requests）。

36 字段列表（Phase 2 冻结版本）:
  基础标识: nickname, unique_id, uid, sec_uid
  个人资料: signature, country, province, city, district, store_region
  认证信息: verification_type, custom_verify, enterprise_verify_reason, is_gov_media_vip, is_star
  账号状态: secret, is_block, is_ban
  影响力: follower_count, following_count, aweme_count, total_favorited
  创作属性: is_mix_user, mix_count, series_count
  粉丝群: r_fans_group_info
  年龄: user_age
  企业信息: enterprise_user_info
  商业属性: commerce_user_level, commerce_user_info, commerce_info,
            live_commerce, with_commerce_entry, with_fusion_shop_entry
  分享: share_info
  头像: avatar_thumb

智能增量: 若缓存已有 unique_id 字段（新格式标记），则跳过；旧格式（仅7字段）自动重采。
"""

import json, time, sys, os, subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

WORK_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_VERSION = 2  # 缓存版本: 1=旧7字段, 2=新36字段
SESSION_TTL = 15 * 60  # session 最长有效时间（秒），超时自动重登

# ── 36 字段定义: (api_key, default) ──
FIELDS = [
    # 基础标识
    ("nickname", ""), ("unique_id", ""), ("uid", ""), ("sec_uid", ""),
    # 个人资料
    ("signature", ""), ("country", ""), ("province", ""), ("city", ""),
    ("district", ""), ("store_region", ""),
    # 认证信息
    ("verification_type", 0), ("custom_verify", ""), ("enterprise_verify_reason", ""),
    ("is_gov_media_vip", False), ("is_star", False),
    # 账号状态
    ("secret", False), ("is_block", False), ("is_ban", False),
    # 影响力
    ("follower_count", 0), ("following_count", 0), ("aweme_count", 0), ("total_favorited", 0),
    # 创作属性
    ("is_mix_user", False), ("mix_count", 0), ("series_count", 0),
    # 粉丝群
    ("r_fans_group_info", None),
    # 年龄
    ("user_age", None),
    # 企业信息
    ("enterprise_user_info", None),
    # 商业属性
    ("commerce_user_level", 0), ("commerce_user_info", None), ("commerce_info", None),
    ("live_commerce", False), ("with_commerce_entry", False), ("with_fusion_shop_entry", False),
    # 分享
    ("share_info", None),
    # 头像
    ("avatar_thumb", None),
]


def extract_user_info(user: dict, sec_uid: str) -> dict:
    """从 API 返回的 user 对象提取 36 个字段"""
    info = {"_cache_version": CACHE_VERSION}
    for key, default in FIELDS:
        val = user.get(key)
        if val is None:
            info[key] = default
        else:
            info[key] = val
    # 用 API 返回的 sec_uid/nickname 覆盖（可能更准确）
    info["sec_uid"] = user.get("sec_uid", sec_uid)
    info["nickname"] = user.get("nickname", "")
    return info


def empty_profile(sec_uid: str, nickname: str = "") -> dict:
    """创建空的错误占位 profile"""
    info = {"_cache_version": CACHE_VERSION, "nickname": nickname, "sec_uid": sec_uid}
    for key, default in FIELDS:
        if key not in info:
            info[key] = default
    return info


# ── 读取 session cookies ──
session_file = WORK_DIR / "douyin_session.json"
if not session_file.exists():
    sys.exit("没有 douyin_session.json，请先登录")

with open(session_file, "r", encoding="utf-8") as f:
    saved = json.load(f)

cookies_raw = saved if isinstance(saved, list) else saved.get("cookies", [])
cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_raw if "name" in c and "value" in c)

# ── 读取待获取作者列表 ──
authors_file = WORK_DIR / "authors_to_fetch.json"
with open(authors_file, "r", encoding="utf-8") as f:
    authors = json.load(f)

print(f"共 {len(authors)} 个作者待处理")

# 检查已有缓存
cache_file = WORK_DIR / "author_profiles_cache.json"
if cache_file.exists():
    with open(cache_file, "r", encoding="utf-8") as f:
        cached = json.load(f)
else:
    cached = {}

# 统计旧格式缓存数
old_format = sum(1 for v in cached.values() if "_cache_version" not in v or v.get("_cache_version", 1) < 2)
new_format = len(cached) - old_format
print(f"缓存: {len(cached)} 人 (旧格式需重采: {old_format}, 新格式已就绪: {new_format})")

# ── 逐个获取 ──
success = 0
fail = 0
skip = 0
empty_sig = 0
consecutive_fails = 0  # 连续失败计数 (检测 session 过期)
session_start = time.time()  # 当前 session 开始时间

for i, author in enumerate(authors):
    sec_uid = author["sec_uid"]
    nick = author.get("nickname", "")

    # 智能跳过: 只跳过已有新格式缓存的
    if sec_uid in cached:
        existing = cached[sec_uid]
        if existing.get("_cache_version") == CACHE_VERSION:
            skip += 1
            continue
        # 旧格式, 需要重采 (不跳过)

    try:
        url = f"https://www.douyin.com/aweme/v1/web/user/profile/other/?sec_user_id={sec_uid}"

        # 最多重试2次（原请求 + 1次重试）
        body = None
        for attempt in range(2):
            req = Request(url)
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
            req.add_header("Referer", "https://www.douyin.com/")
            req.add_header("Accept", "application/json, text/plain, */*")
            req.add_header("Cookie", cookie_str)
            try:
                with urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8")
                if body and body.strip():
                    break  # 成功拿到数据，跳出重试循环
            except Exception:
                pass
            if attempt == 0:
                time.sleep(2)  # 第一次失败，等2秒重试

        if not body or not body.strip():
            # 空响应，可能是网络抖动或用户不存在，不算连续失败
            cached[sec_uid] = empty_profile(sec_uid, nick)
            fail += 1
            if consecutive_fails < 5:
                print(f"  [{nick}] 空响应 (连续失败 {consecutive_fails})")
            time.sleep(1)
            continue

        data = json.loads(body)

        user_info = data.get("user", {})
        if not user_info:
            # 用户不存在或注销，不算连续失败
            cached[sec_uid] = empty_profile(sec_uid, nick)
            fail += 1
            time.sleep(0.5)
            continue

        cached[sec_uid] = extract_user_info(user_info, sec_uid)
        success += 1
        consecutive_fails = 0  # 成功重置计数器
        if not cached[sec_uid].get("signature"):
            empty_sig += 1

        if success % 10 == 0:
            pct = (success + skip) / len(authors) * 100 if authors else 0
            print(f"  进度: {success+skip}/{len(authors)} ({pct:.0f}%)  成功{success} 跳过{skip} 失败{fail}")

        # 每 20 次成功也保存（防止意外中断丢失进度）
        if success % 20 == 0:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cached, f, ensure_ascii=False)
            print(f"  [每20次保存 {success} 条]")

    except HTTPError as e:
        # HTTP 错误：404不算连续失败（用户不存在），其他算
        if e.code in (401, 403):
            consecutive_fails += 1
        elif e.code == 404:
            pass  # 用户不存在，不算失败
        else:
            consecutive_fails += 1
        cached[sec_uid] = empty_profile(sec_uid, nick)
        fail += 1
        if e.code not in (404,):
            print(f"  HTTP {e.code} for {nick}")
        # 每10次连续失败，打印警告
        if consecutive_fails > 0 and consecutive_fails % 10 == 0:
            print(f"  [警告] 连续失败 {consecutive_fails} 次，可能是 session 问题，继续观察...")

    except Exception as e:
        cached[sec_uid] = empty_profile(sec_uid, nick)
        fail += 1
        consecutive_fails += 1
        if consecutive_fails <= 3 or consecutive_fails % 10 == 0:
            print(f"  错误 {nick}: {e}")
        # 每10次连续失败，打印警告
        if consecutive_fails % 10 == 0:
            print(f"  [警告] 连续失败 {consecutive_fails} 次，可能是 session 问题，继续观察...")

    # 连续失败过多 → session 可能过期, 保存进度后退出让包装器重试
    if consecutive_fails >= 50:
        print(f"\n[连续失败 {consecutive_fails} 次, session 可能过期, 保存进度后退出]")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False)
        sys.exit(2)

    time.sleep(0.8)  # 稍微放慢，确保稳定

    # 每100个自动保存
    processed = success + skip + fail
    if processed % 100 == 0:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False)
        print(f"  [自动保存 {processed}/{len(authors)}]")

    # ── Session 定时刷新: 每 25 分钟自动重新登录 ──
    elapsed = time.time() - session_start
    if elapsed > SESSION_TTL:
        mins = int(elapsed / 60)
        print(f"\n[Session 已运行 {mins} 分钟, 正在自动刷新登录...]")
        # 保存进度
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False)
        print(f"  [进度已保存: {processed}/{len(authors)}]")
        # 调用登录脚本
        login_script = WORK_DIR / "scripts" / "douyin_login.py"
        ret = subprocess.run([sys.executable, str(login_script), str(WORK_DIR)])
        if ret.returncode != 0:
            print(f"  [警告] 登录脚本返回 {ret.returncode}, 继续使用当前 session")
        else:
            # 重新加载 cookies
            with open(session_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cookies_raw = saved if isinstance(saved, list) else saved.get("cookies", [])
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_raw if "name" in c and "value" in c)
            session_start = time.time()
            consecutive_fails = 0  # 重置失败计数
            print(f"  [登录刷新成功, 继续采集...]")
        print()

# ── 最终保存 ──
with open(cache_file, "w", encoding="utf-8") as f:
    json.dump(cached, f, ensure_ascii=False)

print(f"\n完成! 成功: {success}, 失败: {fail}, 跳过(已有新格式): {skip}")
print(f"缓存: {cache_file} ({len(cached)} 人)")

# 统计
has_sig = sum(1 for v in cached.values() if v.get("signature"))
has_verify = sum(1 for v in cached.values() if v.get("custom_verify") or v.get("enterprise_verify_reason"))
has_commerce = sum(1 for v in cached.values() if v.get("commerce_user_level"))
print(f"有签名: {has_sig}, 有认证: {has_verify}, 有商业等级: {has_commerce}")

# 打印 5 个样本
print("\n--- 样本 ---")
cnt = 0
for suid, info in cached.items():
    if cnt >= 5:
        break
    print(f"\n[{info.get('nickname', '?')}]")
    print(f"  uid: {info.get('uid')}  unique_id: {info.get('unique_id')}")
    print(f"  粉丝: {info.get('follower_count')}  作品: {info.get('aweme_count')}")
    print(f"  认证: {info.get('custom_verify') or info.get('enterprise_verify_reason') or '无'}")
    print(f"  商业: level={info.get('commerce_user_level')} live={info.get('live_commerce')} shop={info.get('with_commerce_entry')}")
    cnt += 1
