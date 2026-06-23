#!/usr/bin/env python3
"""
抖音评论提取脚本 - Skill 版
用法: python3 extract.py <douyin_unique_id> [max_videos]

功能:
  1. 通过搜索找到抖音号对应的 sec_uid 和视频列表
  2. 逐个视频滚动加载评论，从 RENDER_DATA 提取评论文本
  3. 登录态持久化到 ~/.workbuddy/douyin_chrome_profile
"""
import sys, json, re, time, base64, html as html_mod
from pathlib import Path
from DrissionPage import ChromiumPage, ChromiumOptions

# ─── 配置 ───────────────────────────────────────────────────────────────
PROFILE_DIR = Path.home() / ".workbuddy/douyin_chrome_profile"
OUTPUT_BASE = Path.home() / ".workbuddy/douyin_analysis"
# ────────────────────────────────────────────────────────────────────────────


def is_comment_text(text: str) -> bool:
    """判断是否为有效评论文本（过滤页脚/导航噪音）"""
    if len(text) < 2 or len(text) > 500:
        return False
    if not any('\u4e00' <= c <= '\u9fff' for c in text):
        return False
    skip = ['许可证', '备案', '举报', '电话', '邮箱', '京ICP', '©', '版权',
             '算法', '饭圈', '广播', '网络文化', '互联网', '药品', '器械',
             '宗教', '投诉', '客服', '登录', '注册', '搜索', '首页']
    return not any(kw in text for kw in skip)


def find_user_via_search(page, unique_id: str) -> dict | None:
    """
    通过抖音搜索找到用户，返回 {'sec_uid', 'nickname', 'video_ids': [...]}。
    返回 None 表示未找到。
    """
    print(f"[搜索] 正在搜索用户: {unique_id}")
    page.get(f"https://www.douyin.com/search/{unique_id}?type=user")
    time.sleep(6)

    html = page.html

    # 从 RENDER_DATA 提取用户数据
    match = re.search(r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        print("  ❌ RENDER_DATA 未找到，页面可能未正确加载")
        return None

    data_str = match.group(1).strip()
    data_str = html_mod.unescape(data_str)
    # 修复 base64 padding
    rem = len(data_str) % 4
    if rem:
        data_str += '=' * (4 - rem)

    try:
        decoded = base64.b64decode(data_str).decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  ❌ Base64 解码失败: {e}")
        return None

    # 提取 sec_uid 和 nickname
    sec_uids = re.findall(r'"sec_uid"\s*:\s*"([^"]+)"', decoded)
    nicknames = re.findall(r'"nickname"\s*:\s*"([^"]+)"', decoded)
    unique_ids = re.findall(r'"unique_id"\s*:\s*"([^"]+)"', decoded)

    if not sec_uids:
        print("  ❌ 未找到用户，请确认抖音号是否正确")
        return None

    # 取第一个匹配用户
    result = {
        'sec_uid': sec_uids[0],
        'nickname': nicknames[0] if nicknames else unique_id,
        'unique_id': unique_ids[0] if unique_ids else unique_id,
        'video_ids': [],
    }

    # 提取该用户的视频 ID
    aweme_ids = re.findall(r'"aweme_id"\s*:\s*"(\d+)"', decoded)
    result['video_ids'] = list(dict.fromkeys(aweme_ids))  # 去重保序

    print(f"  ✅ 找到用户: {result['nickname']} (unique_id: {result['unique_id']})")
    print(f"  sec_uid: {result['sec_uid']}")
    print(f"  视频数: {len(result['video_ids'])}")
    return result


def scroll_and_load_comments(page, video_id: str, max_scrolls: int = 60):
    """滚动页面加载评论，最多滚 max_scrolls 轮"""
    print(f"    [{video_id}] 加载评论中...", end=' ', flush=True)
    for _ in range(max_scrolls):
        page.scroll.down(400)
        time.sleep(0.2)
    print("完成")


def extract_comments_from_page(page, video_id: str) -> list[str]:
    """从当前页面提取评论文本，返回去重列表"""
    texts = []
    html = page.html

    # Method 1: RENDER_DATA
    match = re.search(r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            data_str = match.group(1).strip()
            data_str = html_mod.unescape(data_str)
            rem = len(data_str) % 4
            if rem:
                data_str += '=' * (4 - rem)
            decoded = base64.b64decode(data_str).decode('utf-8', errors='replace')

            # 提取 "text":"..." 字段
            for pat in [r'"text"\s*:\s*"((?:[^"\\]|\\.){2,})"',
                        r'"content"\s*:\s*"((?:[^"\\]|\\.){2,})"']:
                found = re.findall(pat, decoded)
                for t in found:
                    t = t.strip()
                    if t and is_comment_text(t) and t not in texts:
                        texts.append(t)
        except Exception:
            pass

    # Method 2: DOM 文本节点补充
    try:
        body_text = page('tag:body').text
        lines = [l.strip() for l in body_text.split('\n') if l.strip()]
        for line in lines:
            if is_comment_text(line) and line not in texts:
                texts.append(line)
    except Exception:
        pass

    return texts


def wait_for_login(page) -> bool:
    """检测是否需要登录，如需则等待用户扫码"""
    time.sleep(3)
    html = page.html
    needs_login = False

    if '扫码' in html or 'qrcode' in html.lower() or 'login' in page.url.lower():
        needs_login = True
    try:
        if page.ele('text=扫码登录', timeout=2):
            needs_login = True
    except Exception:
        pass

    if not needs_login:
        print("  ✅ 已登录（登录态已保存）")
        return True

    print("\n" + "="*50)
    print("⚠️  需要登录抖音！请用抖音 APP 扫码登录")
    print("="*50 + "\n")
    for _ in range(72):  # 最多等 6 分钟
        time.sleep(5)
        try:
            if 'passport' not in page.url and '扫码' not in page.html:
                print("  ✅ 登录成功！")
                time.sleep(2)
                return True
        except Exception:
            pass
    print("  ⚠️  登录等待超时")
    return False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 extract.py <douyin_unique_id> [max_videos]")
        sys.exit(1)

    unique_id = sys.argv[1]
    max_videos = int(sys.argv[2]) if len(sys.argv) > 2 else 999

    # 初始化浏览器
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--window-size=1920,1080')
    co.set_argument(f'--user-data-dir={PROFILE_DIR}')
    # 首次运行显示浏览器（用于扫码），之后可改为 headless(True)
    co.headless(False)

    page = ChromiumPage(co)

    try:
        # 1. 检查登录态
        print("[1] 正在打开抖音首页...")
        page.get("https://www.douyin.com")
        time.sleep(4)
        if not wait_for_login(page):
            print("无法继续，请重新运行脚本并扫码登录")
            sys.exit(1)

        # 2. 搜索用户
        user = find_user_via_search(page, unique_id)
        if not user:
            sys.exit(1)

        video_ids = user['video_ids'][:max_videos]
        if not video_ids:
            print("⚠️  未找到视频，可能账号设为私密或视频数为 0")
            sys.exit(1)

        # 3. 逐个视频提取评论
        OUTPUT_DIR = OUTPUT_BASE / unique_id
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # 保存用户信息
        with open(OUTPUT_DIR / "user_info.json", 'w', encoding='utf-8') as f:
            json.dump(user, f, ensure_ascii=False, indent=2)

        all_comments = []
        print(f"\n[2] 开始提取 {len(video_ids)} 个视频的评论...")

        for i, vid in enumerate(video_ids, 1):
            url = f"https://www.douyin.com/video/{vid}"
            print(f"\n  📹 [{i}/{len(video_ids)}] {vid}")

            page.get(url)
            time.sleep(5)
            scroll_and_load_comments(page, vid)
            comments = extract_comments_from_page(page, vid)
            print(f"    提取到 {len(comments)} 条")

            # 保存单视频结果
            with open(OUTPUT_DIR / f"video_{vid}_comments.json", 'w', encoding='utf-8') as f:
                json.dump(comments, f, ensure_ascii=False, indent=2)

            all_comments.extend(comments)

        # 4. 全部去重保存
        final = list(dict.fromkeys(all_comments))  # 保序去重
        with open(OUTPUT_DIR / "all_comments.json", 'w', encoding='utf-8') as f:
            json.dump(final, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 完成！共提取 {len(final)} 条去重评论")
        print(f"   结果保存在: {OUTPUT_DIR / 'all_comments.json'}")

    finally:
        page.quit()


if __name__ == '__main__':
    main()
