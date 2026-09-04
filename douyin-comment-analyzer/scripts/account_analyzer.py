#!/usr/bin/env python3
"""
抖音账号分析脚本 - 链接入口版
用法:
  python3 account_analyzer.py "<抖音链接或分享口令>" [max_videos] [--minimized]

功能:
  1. 从任意输入（v.douyin.com 短链 / 主页链接 / 视频链接 / App 分享口令文本）提取链接
  2. 打开链接跟随重定向，自动识别是「主页」还是「视频」
     - 视频链接 → 从页面提取作者 sec_uid，再跳转作者主页
  3. 在主页提取账号信息（昵称/签名/粉丝/获赞/作品数）+ 视频列表（滚动加载）
  4. 逐个视频抓取评论，输出到 ~/.workbuddy/douyin_analysis/account_<昵称>/
  5. 数据格式兼容 analyze.py，直接跑 analyze.py account_<昵称> 出报告

手机端用法: 用户丢来抖音分享口令/链接 → 本脚本自动完成「解析账号 → 拉视频+评论」。

2026-09 验证要点:
  - 账号昵称/统计信息在 DOM（title / body 文本），不在 RENDER_DATA（那里是页面其他作者）
  - 粉丝/获赞在 DOM 文本中标签与数值可能同行("粉丝21.0万")或分行("粉丝"+"21.0万")
  - 主页视频链接为 //www.douyin.com/video/<id> 相对协议形式
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


# ─── 链接解析 ──────────────────────────────────────────────────────────
def extract_url(text: str) -> str | None:
    """从任意文本提取抖音链接（短链/主页/视频）"""
    # 优先 v.douyin.com 短链
    m = re.search(r'https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?', text)
    if m:
        return m.group(0)
    # 其次 www.douyin.com 直接链接
    m = re.search(r'https?://www\.douyin\.com/(?:user|video|note|share)/[^\s，。、；;）)】】"\'<>]+', text)
    if m:
        return m.group(0)
    # 无协议前缀的短链（口令里可能省略 https://）
    m = re.search(r'v\.douyin\.com/[A-Za-z0-9_\-]+/?', text)
    if m:
        return 'https://' + m.group(0)
    return None


def resolve_url(page, url: str) -> str:
    """打开链接并跟随重定向，返回最终 URL"""
    page.get(url)
    time.sleep(5)
    # 短链重定向可能需要时间，多等两轮
    for _ in range(3):
        if 'v.douyin.com' in page.url:
            time.sleep(3)
        else:
            break
    return page.url


def extract_author_from_video_page(page) -> dict | None:
    """视频页：提取作者信息。优先 RENDER_DATA，回退 DOM 链接"""
    author = {}
    decoded = get_render_data(page)
    if decoded:
        m = re.search(r'"author"\s*:\s*\{[^}]*?"sec_uid"\s*:\s*"([^"]+)"', decoded)
        if m:
            author['sec_uid'] = m.group(1)
        m = re.search(r'"author"\s*:\s*\{[^}]*?"nickname"\s*:\s*"([^"]+)"', decoded)
        if m:
            author['nickname'] = m.group(1)

    # fallback: DOM 中的作者主页链接（2026-09 验证有效）
    if not author.get('sec_uid'):
        html = page.html
        uids = re.findall(r'/user/([A-Za-z0-9_\-]{10,})', html)
        uids = list(dict.fromkeys(uids))
        if uids:
            author['sec_uid'] = uids[0]
    return author or None


def parse_cn_number(s: str) -> int | None:
    """解析 '21.0万' / '368' / '1.2亿' → 整数"""
    s = s.strip()
    m = re.match(r'^([\d.]+)\s*(万|亿)?$', s)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == '万':
        val *= 10000
    elif unit == '亿':
        val *= 100000000
    return int(val)


def extract_account_from_homepage(page) -> dict:
    """主页：提取账号信息 + 视频列表（统计字段从 DOM 文本，2026-09 验证）"""
    info = {}
    decoded = get_render_data(page)
    html = page.html

    # 昵称：优先 title（"xxx的抖音 - 抖音"），RENDER_DATA 里的 nickname 可能是页面其他作者
    t = re.search(r'<title>([^<]+)</title>', html)
    if t:
        name = re.sub(r'(的抖音|的主页).*$', '', t.group(1)).strip()
        if name:
            info['nickname'] = name
    if 'nickname' not in info and decoded:
        m = re.search(r'"nickname"\s*:\s*"([^"]+)"', decoded)
        if m:
            info['nickname'] = m.group(1)

    # 签名：meta description（"xxx。xxx的抖音主页..."）
    m = re.search(r'<meta[^>]*(?:name|property)="(?:description|og:description)"[^>]*content="([^"]+)"', html)
    if m:
        desc = m.group(1).split('。')[0].strip()
        if desc and desc != info.get('nickname'):
            info['signature'] = desc[:120]

    # 统计字段：DOM 文本，粉丝/获赞标签与数值可能同行("粉丝21.0万")或分行("粉丝\n21.0万")
    try:
        body_lines = [l.strip() for l in page('tag:body').text.split('\n') if l.strip()]
    except Exception:
        body_lines = []
    for label, key in [('粉丝', 'follower_count'), ('获赞', 'total_favorited')]:
        found_val = None
        # 同行匹配，优先带单位(万/亿)，跳过 0（侧边栏"粉丝0"是当前登录用户）
        joined = ' '.join(body_lines[:100])
        for pat in [label + r'\s*([\d.]+万|[\d.]+亿)',
                    label + r'\s*([\d.]+)']:
            m = re.search(pat, joined)
            if m:
                v = parse_cn_number(m.group(1))
                if v:
                    found_val = v
                    break
        if not found_val:
            # 分行: 找 "粉丝" 行，数值在下一行
            for i, l in enumerate(body_lines[:100]):
                if l == label and i + 1 < len(body_lines):
                    v = parse_cn_number(body_lines[i + 1])
                    if v:
                        found_val = v
                        break
        if found_val:
            info[key] = found_val
    # 作品数: "作品368" 同行
    for l in body_lines[:100]:
        m = re.search(r'作品\s*(\d+)', l)
        if m:
            info['aweme_count'] = int(m.group(1))
            break

    # 视频列表：滚动加载后从 DOM 提取
    info['video_ids'] = []
    for _ in range(6):
        page.scroll.down(700)
        time.sleep(0.5)
    ids = re.findall(r'/video/(\d{15,})', page.html)
    if not ids and decoded:
        ids = re.findall(r'"aweme_id"\s*:\s*"(\d{15,})"', decoded)
    info['video_ids'] = list(dict.fromkeys(ids))

    # sec_uid：从 URL 提取
    m = re.search(r'/user/([A-Za-z0-9_\-]+)', page.url)
    if m:
        info['sec_uid'] = m.group(1)
    return info


def safe_dir_name(name: str) -> str:
    """目录名安全化"""
    name = re.sub(r'[\\/:*?"<>|\s]+', '_', name)
    return name[:40] or 'unknown'


# ─── 主流程 ────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("用法: python3 account_analyzer.py \"<抖音链接或分享口令>\" [max_videos] [--minimized]")
        sys.exit(1)

    raw_input = sys.argv[1]
    max_videos = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 20
    minimized = '--minimized' in sys.argv

    url = extract_url(raw_input)
    if not url:
        print("❌ 未从输入中识别出抖音链接。支持: v.douyin.com 短链 / 主页链接 / 视频链接 / App 分享口令")
        sys.exit(1)
    print(f"[0] 识别到链接: {url}")

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
        # 1. 登录检查
        print("[1] 打开抖音首页检查登录态...")
        page.get("https://www.douyin.com")
        time.sleep(4)
        if not wait_for_login(page):
            print("无法继续，请重新运行脚本并扫码登录")
            sys.exit(1)

        # 2. 解析链接（跟随重定向）
        print("[2] 解析链接...")
        final_url = resolve_url(page, url)
        print(f"    最终地址: {final_url}")

        # 3. 判断形态：视频页 → 提取作者后跳主页；主页 → 直接解析
        sec_uid = None
        if '/user/' in final_url:
            sec_uid = re.search(r'/user/([A-Za-z0-9_\-]+)', final_url).group(1)
            print(f"    形态: 主页 (sec_uid={sec_uid})")
        elif '/video/' in final_url or '/note/' in final_url:
            print("    形态: 视频页，提取作者信息...")
            author = extract_author_from_video_page(page)
            if author and author.get('sec_uid'):
                sec_uid = author['sec_uid']
                print(f"    作者: {author.get('nickname', '?')} (sec_uid={sec_uid})")
            else:
                print("❌ 未能从视频页提取作者 sec_uid")
                sys.exit(1)
        else:
            print(f"❌ 无法识别的链接形态: {final_url}")
            sys.exit(1)

        # 4. 打开主页，提取账号信息 + 视频列表
        print("[3] 打开作者主页...")
        page.get(f"https://www.douyin.com/user/{sec_uid}")
        time.sleep(6)
        # 主页异步加载：确认 title 出现账号名再解析，否则等一轮
        for _ in range(4):
            t = re.search(r'<title>([^<]+)</title>', page.html)
            if t and ('抖音' in t.group(1) or '的主页' in t.group(1)):
                break
            time.sleep(3)
        info = extract_account_from_homepage(page)
        info['sec_uid'] = sec_uid
        print(f"    账号: {info.get('nickname', '?')}")
        if info.get('signature'):
            print(f"    签名: {info['signature'][:60]}")
        print(f"    粉丝: {info.get('follower_count', '?')} | 获赞: {info.get('total_favorited', '?')} | 作品: {info.get('aweme_count', '?')}")
        print(f"    抓到 {len(info['video_ids'])} 个视频")

        video_ids = info['video_ids'][:max_videos]
        if not video_ids:
            print("⚠️  主页未抓到视频（可能需更多滚动/私密账号），尝试直接退出")
            sys.exit(1)

        # 5. 抓评论
        dir_name = f"account_{safe_dir_name(info.get('nickname', sec_uid))}"
        OUTPUT_DIR = OUTPUT_BASE / dir_name
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_DIR / "user_info.json", 'w', encoding='utf-8') as f:
            json.dump({**info, 'sec_uid': sec_uid, 'source_url': url, 'final_url': final_url},
                      f, ensure_ascii=False, indent=2)

        all_comments = []
        print(f"\n[4] 开始提取 {len(video_ids)} 个视频的评论...")
        for i, vid in enumerate(video_ids, 1):
            print(f"\n  📹 [{i}/{len(video_ids)}] {vid}")
            page.get(f"https://www.douyin.com/video/{vid}")
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
                "account": info.get('nickname'),
                "sec_uid": sec_uid,
                "video_ids": video_ids,
                "comment_count": len(final),
                "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 完成！共提取 {len(final)} 条去重评论")
        print(f"   结果: {OUTPUT_DIR / 'all_comments.json'}")
        print(f"   下一步: analyze.py {dir_name} 生成话题报告")

    finally:
        page.quit()


if __name__ == '__main__':
    main()
