#!/usr/bin/env python3
"""
抖音账号持续监控 - 主脚本（2026-09 建）

职责边界：本脚本只做「账号级周期性增量监控」。
一次性深度评论分析请用 douyin-comment-analyzer。

用法:
  python3 monitor.py add "<抖音链接/分享口令>"   # 解析并注册账号 + 首次快照
  python3 monitor.py run [--no-comments]          # 巡查全部账号，输出增量变化
  python3 monitor.py run <sec_uid>                # 只巡查指定账号
  python3 monitor.py list                         # 查看监控名单 + 最新数据
  python3 monitor.py report <sec_uid>             # 输出该账号历史趋势
  python3 monitor.py videos <sec_uid> [N]         # 作品数据排行（按点赞降序，看哪条爆了）
  python3 monitor.py detail <aweme_id>            # 手动补抓单条视频的数据与评论

设计要点（踩坑记录）:
  - 账号统计（粉丝/获赞/作品数）在 DOM 文本，不在 RENDER_DATA
  - 标签与数值可能同行("粉丝21.0万")也可能分行("粉丝\n21.0万")，需双路匹配
  - 主页视频链接为 //www.douyin.com/video/<id> 相对协议形式
  - 必须复用 ~/.workbuddy/douyin_chrome_profile 登录态，无头模式易被识别
"""
import sys
import re
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime

from DrissionPage import ChromiumPage, ChromiumOptions

# ─── 路径配置（与 douyin-comment-analyzer 共用登录态 profile）─────────────
SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
DB_PATH = DATA_DIR / "monitor.db"
PROFILE_DIR = Path.home() / ".workbuddy/douyin_chrome_profile"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 单次巡查最多抓取多少条新作品的详情（含评论），防止任务被拖到不可控长度
MAX_DETAIL_FETCH = 20

# 评论过滤规则复用 douyin-comment-analyzer 的 common.py（避免两套噪音词表漂移）
_COMMON_DIR = Path.home() / ".workbuddy/skills/douyin-comment-analyzer/scripts"
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))
try:
    from common import extract_comments_from_page  # noqa: E402
    HAS_COMMON = True
except ImportError:
    HAS_COMMON = False

    def is_comment_text(text: str) -> bool:
        """降级版评论区过滤（common.py 不可用时使用）"""
        if len(text) < 2 or len(text) > 500:
            return False
        if not any('\u4e00' <= c <= '\u9fff' for c in text):
            return False
        if re.match(r'^\d+(小时|分钟|天|周|月|年)前(·\S+)?$', text):
            return False
        return text not in ('评论', '点赞', '收藏', '分享', '转发', '关注', '展开', '收起',
                            '举报', '作者', '回复', '推荐', '举报')

    def extract_comments_from_page(page) -> list:
        texts = []
        try:
            body_lines = [l.strip() for l in page('tag:body').text.split('\n') if l.strip()]
            for line in body_lines:
                if is_comment_text(line) and line not in texts:
                    texts.append(line)
        except Exception:
            pass
        return texts


# ─── 数据库 ────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS accounts (
        sec_uid TEXT PRIMARY KEY,
        nickname TEXT,
        signature TEXT,
        source_url TEXT,
        added_at TEXT,
        last_check TEXT,
        active INTEGER DEFAULT 1,
        baselined INTEGER DEFAULT 0,
        douyin_id TEXT,
        ip_location TEXT,
        age INTEGER,
        region TEXT,
        baseline_digg INTEGER
    )""")
    # 兼容旧表：baselined=0 表示首次巡查（基线补全轮），该轮只建基线不报警
    acols = {r[1] for r in c.execute("PRAGMA table_info(accounts)").fetchall()}
    for col, ddl in [('baselined', 'INTEGER DEFAULT 0'), ('douyin_id', 'TEXT'),
                     ('ip_location', 'TEXT'), ('age', 'INTEGER'),
                     ('region', 'TEXT'), ('baseline_digg', 'INTEGER')]:
        if col not in acols:
            c.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sec_uid TEXT,
        checked_at TEXT,
        follower_count INTEGER,
        total_favorited INTEGER,
        aweme_count INTEGER,
        video_count_seen INTEGER,
        ok INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS videos (
        aweme_id TEXT PRIMARY KEY,
        sec_uid TEXT,
        discovered_at TEXT,
        seen_count INTEGER DEFAULT 1,
        notified INTEGER DEFAULT 0,
        title TEXT,
        publish_time TEXT,
        digg_count INTEGER,
        comment_count INTEGER,
        collect_count INTEGER,
        share_count INTEGER,
        detail_fetched_at TEXT
    )""")
    # 兼容旧表：补列
    cols = {r[1] for r in c.execute("PRAGMA table_info(videos)").fetchall()}
    for col, ddl in [('seen_count', 'INTEGER DEFAULT 2'), ('title', 'TEXT'),
                     ('publish_time', 'TEXT'), ('digg_count', 'INTEGER'),
                     ('comment_count', 'INTEGER'), ('collect_count', 'INTEGER'),
                     ('share_count', 'INTEGER'), ('detail_fetched_at', 'TEXT')]:
        if col not in cols:
            c.execute(f"ALTER TABLE videos ADD COLUMN {col} {ddl}")
    c.execute("""CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        aweme_id TEXT,
        content TEXT,
        fetched_at TEXT,
        UNIQUE(aweme_id, content)
    )""")
    conn.commit()
    return conn


# ─── 工具函数 ──────────────────────────────────────────────────────────
def extract_url(text: str) -> str | None:
    """从任意文本提取抖音链接（短链/主页/视频）"""
    m = re.search(r'https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?', text)
    if m:
        return m.group(0)
    m = re.search(r'https?://www\.douyin\.com/(?:user|video|note|share)/[^\s，。、；;）)】"\'"<>]+', text)
    if m:
        return m.group(0)
    m = re.search(r'v\.douyin\.com/[A-Za-z0-9_\-]+/?', text)
    if m:
        return 'https://' + m.group(0)
    return None


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


def safe_dir_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\s]+', '_', name)
    return name[:40] or 'unknown'


# ─── 浏览器 ────────────────────────────────────────────────────────────
def open_browser(headless: bool = False):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--window-size=1920,1080')
    co.set_argument(f'--user-data-dir={PROFILE_DIR}')
    co.set_argument('--start-minimized')
    co.headless(headless)
    return ChromiumPage(co)


def get_render_data(page) -> str:
    from urllib.parse import unquote
    import base64
    html = page.html
    m = re.search(r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1).strip()
    if raw.startswith('%'):
        return unquote(raw)
    rem = len(raw) % 4
    if rem:
        raw += '=' * (4 - rem)
    try:
        return base64.b64decode(raw).decode('utf-8', errors='replace')
    except Exception:
        return unquote(raw)


def is_logged_in(page) -> bool:
    decoded = get_render_data(page)
    if decoded:
        m = re.search(r'"isLogin"\s*:\s*(true|false)', decoded)
        if m:
            return m.group(1) == 'true'
    return 'passport' not in page.url


def ensure_login(page) -> bool:
    page.get("https://www.douyin.com")
    time.sleep(4)
    if is_logged_in(page):
        return True
    print("\n" + "=" * 50)
    print("⚠️  需要登录抖音！请在弹出的浏览器里用抖音 APP 扫码")
    print("=" * 50 + "\n")
    for _ in range(72):  # 最多等 6 分钟
        time.sleep(5)
        if is_logged_in(page):
            print("  ✅ 登录成功！")
            time.sleep(2)
            return True
    return False


def resolve_url(page, url: str) -> str:
    """打开链接并跟随重定向，返回最终 URL"""
    page.get(url)
    time.sleep(5)
    for _ in range(3):
        if 'v.douyin.com' in page.url:
            time.sleep(3)
        else:
            break
    return page.url


def extract_author_from_video_page(page) -> dict | None:
    """视频页：提取作者 sec_uid。优先 RENDER_DATA，回退 DOM 链接"""
    author = {}
    decoded = get_render_data(page)
    if decoded:
        m = re.search(r'"author"\s*:\s*\{[^}]*?"sec_uid"\s*:\s*"([^"]+)"', decoded)
        if m:
            author['sec_uid'] = m.group(1)
        m = re.search(r'"author"\s*:\s*\{[^}]*?"nickname"\s*:\s*"([^"]+)"', decoded)
        if m:
            author['nickname'] = m.group(1)
    if not author.get('sec_uid'):
        uids = re.findall(r'/user/([A-Za-z0-9_\-]{10,})', page.html)
        uids = list(dict.fromkeys(uids))
        if uids:
            author['sec_uid'] = uids[0]
    return author or None


def extract_account_from_homepage(page) -> dict:
    """主页：提取账号信息 + 视频列表（统计字段从 DOM 文本，2026-09 验证）"""
    info = {}
    html = page.html

    # 昵称：优先 title（"xxx的抖音 - 抖音"）
    t = re.search(r'<title>([^<]+)</title>', html)
    if t:
        name = re.sub(r'(的抖音|的主页).*$', '', t.group(1)).strip()
        if name:
            info['nickname'] = name

    # 签名：meta description
    m = re.search(r'<meta[^>]*(?:name|property)="(?:description|og:description)"[^>]*content="([^"]+)"', html)
    if m:
        desc = m.group(1).split('。')[0].strip()
        if desc and desc != info.get('nickname'):
            info['signature'] = desc[:120]

    # 统计字段：粉丝/获赞（同行 or 分行双路匹配）
    try:
        body_lines = [l.strip() for l in page('tag:body').text.split('\n') if l.strip()]
    except Exception:
        body_lines = []
    for label, key in [('粉丝', 'follower_count'), ('获赞', 'total_favorited')]:
        found_val = None
        joined = ' '.join(body_lines[:100])
        for pat in [label + r'\s*([\d.]+万|[\d.]+亿)', label + r'\s*([\d.]+)']:
            m = re.search(pat, joined)
            if m:
                v = parse_cn_number(m.group(1))
                if v:
                    found_val = v
                    break
        if not found_val:
            for i, l in enumerate(body_lines[:100]):
                if l == label and i + 1 < len(body_lines):
                    v = parse_cn_number(body_lines[i + 1])
                    if v:
                        found_val = v
                        break
        if found_val:
            info[key] = found_val

    # 作品数
    for l in body_lines[:100]:
        m = re.search(r'作品\s*(\d+)', l)
        if m:
            info['aweme_count'] = int(m.group(1))
            break

    # 抖音号 / IP属地 / 年龄 / 地区
    # DOM 里挤在一行：「抖音号：25931495118IP属地：科特迪瓦39岁香港」
    # 但格式不统一：有账号没有年龄，属地后直接跟性别（「IP属地：浙江男 安哥拉」）。
    # 属地必须用 lookahead 限定结束位置，否则会一路吞掉后面的签名
    # （实测黄云丰的属地被抓成「浙江男安哥拉 我是黄云丰 | 合作/咨询…拥有非洲安哥拉30…」）。
    joined_all = ' '.join(body_lines[:200])
    m = re.search(r'抖音号[：:]\s*([^\s]{1,30}?)\s*IP属地[：:]\s*([^\s]{1,10}?)'
                  r'(?=\d{1,3}岁|男|女|\s|$)', joined_all)
    if m:
        info['douyin_id'] = m.group(1)
        info['ip_location'] = m.group(2).strip()
        rest = joined_all[m.end():m.end() + 40]
        # 地区是短地名，且其后必有空白或结束 —— 否则会把签名开头吞进来
        # （实测贺总的地区被抓成「凡我所失，皆非我所有，凡我所求…」）
        m2 = re.match(r'\s*(?:(\d{1,3})岁)?\s*(?:男|女)?\s*([^\s|，。、#,]{2,10})?(?=\s|$)', rest)
        if m2:
            if m2.group(1):
                info['age'] = int(m2.group(1))
            if m2.group(2):
                info['region'] = m2.group(2)

    # 视频列表：滚动加载后从 DOM 提取
    # 滚动次数要够（主页异步加载），否则覆盖率不足，新作品可能漏抓
    for _ in range(12):
        page.scroll.down(700)
        time.sleep(0.5)
    ids = re.findall(r'/video/(\d{15,})', page.html)
    if not ids:
        decoded = get_render_data(page)
        if decoded:
            ids = re.findall(r'"aweme_id"\s*:\s*"(\d{15,})"', decoded)
    info['video_ids'] = list(dict.fromkeys(ids))

    m = re.search(r'/user/([A-Za-z0-9_\-]+)', page.url)
    if m:
        info['sec_uid'] = m.group(1)
    return info


def extract_homepage_videos(page) -> list:
    """从主页作品卡片批量提取 aweme_id + 点赞数 + 文案

    2026-09 实测：每个作品是一个 <li>，内部文本节点顺序固定为
        [可选「置顶」] → 点赞数 → 文案 → 文案(重复一次)
    且 `<a href="/video/<id>">` 与 `<img alt="作者名：文案">` 在同一个 li 内，
    因此可以在 li 级别精确关联三者 —— 一次主页访问就能拿到全部作品的点赞数，
    无需逐个打开视频页（成本从 ~1 小时降到 ~13 次主页访问）。
    """
    results = []
    try:
        lis = page.eles('tag:li')
    except Exception:
        return results
    for li in lis:
        try:
            h = li.html
        except Exception:
            continue
        m_id = re.search(r'href="/video/(\d{15,})"', h)
        if not m_id:
            continue
        aweme_id = m_id.group(1)

        # 文本节点序列：置顶(可选) → 点赞数 → 文案
        nodes = [l.strip() for l in re.sub(r'<[^>]+>', '\n', h).split('\n') if l.strip()]
        digg, title = None, None
        for n in nodes:
            if n == '置顶':
                continue
            if digg is None:
                v = parse_cn_number(n)
                if v is not None:
                    digg = v
                    continue
            if title is None and parse_cn_number(n) is None:
                title = n
                break

        # 文案优先取 alt（更完整），需剥掉「作者名：」前缀
        m_alt = re.search(r'alt="([^"]*)"', h)
        if m_alt:
            a = m_alt.group(1)
            if '：' in a:
                a = a.split('：', 1)[1]
            if a.strip():
                title = a.strip()

        if digg is not None:
            results.append({'aweme_id': aweme_id, 'digg_count': digg,
                            'title': (title or '')[:200]})
    return results


def sync_homepage_videos(c, items: list, sec_uid: str, now: str, insert_new: bool = False) -> int:
    """用主页作品卡片数据刷新库中作品的点赞数（零额外成本，主页已经打开了）

    insert_new=False（巡查中用）：只更新已存在的记录。
        —— 必须如此。若允许新增，真新作品会被标成「已确认基线」从而永远漏报。
    insert_new=True（backfill 补数据时用）：允许新增，用于首次批量建立作品数据。
    """
    if not items:
        return 0
    updated = 0
    for it in items:
        if insert_new:
            c.execute("""INSERT INTO videos (aweme_id, sec_uid, discovered_at, seen_count, notified,
                                             digg_count, title)
                         VALUES (?,?,?,2,1,?,?)
                         ON CONFLICT(aweme_id) DO UPDATE SET
                             digg_count=excluded.digg_count,
                             title=COALESCE(videos.title, excluded.title)""",
                      (it['aweme_id'], sec_uid, now, it['digg_count'], it['title']))
            updated += 1
        else:
            cur = c.execute("UPDATE videos SET digg_count=?, title=COALESCE(title, ?) WHERE aweme_id=?",
                            (it['digg_count'], it['title'], it['aweme_id']))
            updated += cur.rowcount or 0
    return updated


def extract_video_detail(page) -> dict:
    """视频页：提取 点赞/评论/收藏/转发 + 文案 + 发布时间

    2026-09 实测：这四项数值在 DOM 文本中以**裸数字**出现，无标签，
    固定顺序 点赞 → 评论 → 收藏 → 转发，紧邻「举报」锚点之前。
    页面上方播放器控件区会重复出现同一组数字，因此必须以「举报」为锚点往前定位，
    不能简单地全文搜数字。
    """
    detail = {}
    try:
        lines = [l.strip() for l in page('tag:body').text.split('\n') if l.strip()]
    except Exception:
        return detail

    # 互动按钮区会出现纯标签行（「分享」等），收集数字时必须跳过，
    # 否则会把标签当成结构异常而整体放弃解析。
    LABELS = {'举报', '分享', '转发', '收藏', '评论', '点赞', '不喜欢', '展开'}
    for i, l in enumerate(lines):
        if l == '举报' and i >= 3:
            # 往前收最多 4 个数字（从后往前收集），跳过纯标签行
            cands = []
            j = i - 1
            while j >= 0 and len(cands) < 4:
                if lines[j] in LABELS:
                    j -= 1
                    continue
                v = parse_cn_number(lines[j])
                if v is None:
                    break  # 遇到非数字非标签 → 结构边界，停止
                cands.append(v)
                j -= 1
            # 顺序（从后往前）：转发 / 收藏 / 评论 / 点赞
            # 实测转发数有时不渲染（只剩 3 个数：收藏 / 评论 / 点赞），需兼容。
            if len(cands) == 4:
                detail['share_count'] = cands[0]
                detail['collect_count'] = cands[1]
                detail['comment_count'] = cands[2]
                detail['digg_count'] = cands[3]
            elif len(cands) == 3:
                detail['collect_count'] = cands[0]
                detail['comment_count'] = cands[1]
                detail['digg_count'] = cands[2]
            # 发布时间：锚点之后 1-3 行
            for k in range(i + 1, min(i + 4, len(lines))):
                m = re.search(r'发布时间[：:]\s*(.+)', lines[k])
                if m:
                    detail['publish_time'] = m.group(1).strip()
                    break
            # 文案：锚点往前跳过数字与标签后的第一行有效文本
            j = i - 1
            floor = max(0, i - 12)
            while j >= floor:
                if (lines[j] not in LABELS and lines[j] != '举报'
                        and parse_cn_number(lines[j]) is None):
                    detail['title'] = lines[j][:200]
                    break
                j -= 1
            break

    if not detail.get('title'):
        m = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"', page.html)
        if m and m.group(1).strip():
            detail['title'] = m.group(1).strip()[:200]
    return detail


def fetch_video_comments(page, vid: str, max_scroll: int = 60) -> list:
    """打开视频页滚动加载并提取评论文本"""
    page.get(f"https://www.douyin.com/video/{vid}")
    time.sleep(5)
    for _ in range(max_scroll):
        page.scroll.down(400)
        time.sleep(0.2)
    return extract_comments_from_page(page)


# ─── 业务逻辑 ──────────────────────────────────────────────────────────
def resolve_account(page, raw_input: str) -> dict | None:
    """输入链接/口令 → 解析出账号信息（含主页视频列表）"""
    url = extract_url(raw_input)
    if not url:
        print("❌ 未从输入中识别出抖音链接")
        return None
    print(f"[0] 识别到链接: {url}")

    final_url = resolve_url(page, url)
    print(f"[1] 最终地址: {final_url}")

    sec_uid = None
    if '/user/' in final_url:
        sec_uid = re.search(r'/user/([A-Za-z0-9_\-]+)', final_url).group(1)
        print(f"    形态: 主页 (sec_uid={sec_uid})")
    elif '/video/' in final_url or '/note/' in final_url:
        print("    形态: 视频页，提取作者信息...")
        author = extract_author_from_video_page(page)
        if author and author.get('sec_uid'):
            sec_uid = author['sec_uid']
            print(f"    作者: {author.get('nickname', '?')}")
        else:
            print("❌ 未能从视频页提取作者 sec_uid")
            return None
    else:
        print(f"❌ 无法识别的链接形态: {final_url}")
        return None

    print("[2] 打开作者主页...")
    page.get(f"https://www.douyin.com/user/{sec_uid}")
    time.sleep(6)
    for _ in range(4):
        t = re.search(r'<title>([^<]+)</title>', page.html)
        if t and ('抖音' in t.group(1) or '的主页' in t.group(1)):
            break
        time.sleep(3)

    info = extract_account_from_homepage(page)
    info['sec_uid'] = sec_uid
    info['source_url'] = url
    return info


def cmd_add(raw_input: str):
    page = open_browser()
    conn = init_db()
    try:
        if not ensure_login(page):
            print("❌ 登录失败，无法继续")
            return 1
        info = resolve_account(page, raw_input)
        if not info:
            return 1
        sec_uid = info['sec_uid']
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO accounts
                     (sec_uid, nickname, signature, source_url, added_at, last_check, active)
                     VALUES (?,?,?,?, COALESCE((SELECT added_at FROM accounts WHERE sec_uid=?), ?), ?, 1)""",
                  (sec_uid, info.get('nickname'), info.get('signature'), info.get('source_url'),
                   sec_uid, now, now))
        # 首次快照
        c.execute("""INSERT INTO snapshots
                     (sec_uid, checked_at, follower_count, total_favorited, aweme_count, video_count_seen, ok)
                     VALUES (?,?,?,?,?,?,1)""",
                  (sec_uid, now, info.get('follower_count'), info.get('total_favorited'),
                   info.get('aweme_count'), len(info.get('video_ids', []))))
        # 基线视频视为「已确认且已报警」(seen_count=2, notified=1)。
        # notified 必须显式置 1：否则 confirmed 逻辑会在该账号作品数首次增长时，
        # 把这些老视频当成新作品误报（实测 非洲于哥 有 24 条这样的存量行）。
        for vid in info.get('video_ids', []):
            c.execute("""INSERT OR IGNORE INTO videos (aweme_id, sec_uid, discovered_at, seen_count, notified)
                         VALUES (?,?,?,2,1)""", (vid, sec_uid, now))
        conn.commit()

        print(f"\n✅ 已纳入监控")
        print(f"   账号: {info.get('nickname', '?')}")
        if info.get('signature'):
            print(f"   签名: {info['signature'][:60]}")
        print(f"   粉丝: {info.get('follower_count', '?')} | 获赞: {info.get('total_favorited', '?')} | 作品: {info.get('aweme_count', '?')}")
        print(f"   已录入库 {len(info.get('video_ids', []))} 个视频作为基线")
        print(f"   sec_uid: {sec_uid}")
        return 0
    finally:
        page.quit()
        conn.close()


def cmd_run(only_sec_uid: str | None = None, fetch_comments: bool = True):
    conn = init_db()
    c = conn.cursor()
    if only_sec_uid:
        c.execute("SELECT sec_uid, nickname FROM accounts WHERE active=1 AND sec_uid=?", (only_sec_uid,))
    else:
        c.execute("SELECT sec_uid, nickname FROM accounts WHERE active=1")
    targets = c.fetchall()
    if not targets:
        print("监控名单为空。先用 add 添加账号。")
        conn.close()
        return 1

    page = open_browser()
    try:
        if not ensure_login(page):
            print("❌ 登录失败，无法继续")
            return 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        changes = []
        for sec_uid, nickname in targets:
            print(f"\n🔍 巡查: {nickname or sec_uid}")
            page.get(f"https://www.douyin.com/user/{sec_uid}")
            time.sleep(6)
            for _ in range(4):
                t = re.search(r'<title>([^<]+)</title>', page.html)
                if t and ('抖音' in t.group(1) or '的主页' in t.group(1)):
                    break
                time.sleep(3)
            info = extract_account_from_homepage(page)
            info['sec_uid'] = sec_uid
            # page 此刻仍停留在主页，顺手把作品卡片的点赞数取走（零额外成本）
            homepage_items = extract_homepage_videos(page)

            if not info.get('nickname') and not info.get('follower_count'):
                print("   ⚠️  页面异常，可能触发风控或登录态失效，跳过")
                c.execute("""INSERT INTO snapshots (sec_uid, checked_at, ok) VALUES (?,?,0)""", (sec_uid, now))
                conn.commit()
                continue

            # ── 新作品判定的依据（必须在插入本次快照前取上次数据）──────────
            c.execute("""SELECT aweme_count FROM snapshots WHERE sec_uid=? AND ok=1
                         ORDER BY id DESC LIMIT 1""", (sec_uid,))
            _row = c.fetchone()
            prev_aweme = _row[0] if _row else None
            cur_aweme = info.get('aweme_count')
            # 【硬约束】作品总数没增加 → 绝对不可能有新作品
            expected_new = 0
            if prev_aweme is not None and cur_aweme is not None and cur_aweme > prev_aweme:
                expected_new = cur_aweme - prev_aweme
            c.execute("SELECT COALESCE(baselined,0) FROM accounts WHERE sec_uid=?", (sec_uid,))
            _r = c.fetchone()
            baselined = bool(_r[0]) if _r else False
            if not baselined:
                print(f"   （首次巡查：本轮只建基线，不报警）")

            c.execute("""INSERT INTO snapshots
                         (sec_uid, checked_at, follower_count, total_favorited, aweme_count, video_count_seen, ok)
                         VALUES (?,?,?,?,?,?,1)""",
                      (sec_uid, now, info.get('follower_count'), info.get('total_favorited'),
                       info.get('aweme_count'), len(info.get('video_ids', []))))

            # ── 新作品 diff：三重约束 ──────────────────────────────────
            # 1) 作品总数硬约束：aweme_count 没增加就绝无新作品。主页一次只能加载几十条，
            #    而账号可能有几千个作品，基线永远不完整；滚动深度一变，加载到的老视频
            #    就会被误判成新作品（实测一次涌出 112 条）。这是最有效的过滤器。
            # 2) 二次确认：新 ID 连续 2 次巡查都出现，过滤异步加载抖动。
            # 3) 基线轮不报警：首次巡查（baselined=0）只建基线。
            c.execute("SELECT aweme_id, seen_count, notified FROM videos WHERE sec_uid=?", (sec_uid,))
            known = {r[0]: (r[1], r[2]) for r in c.fetchall()}
            new_videos = []
            pending_cnt = 0
            for vid in info.get('video_ids', []):
                if vid not in known:
                    if expected_new > 0 and pending_cnt < expected_new:
                        # 作品数确实涨了 → 有可能是真新作品，进入二次确认队列
                        c.execute("""INSERT OR IGNORE INTO videos
                                     (aweme_id, sec_uid, discovered_at, seen_count, notified)
                                     VALUES (?,?,?,1,0)""", (vid, sec_uid, now))
                        pending_cnt += 1
                    else:
                        # 作品数没涨（或名额已用尽）→ 这是基线缺失的老视频，直接标为已确认
                        c.execute("""INSERT OR IGNORE INTO videos
                                     (aweme_id, sec_uid, discovered_at, seen_count, notified)
                                     VALUES (?,?,?,2,1)""", (vid, sec_uid, now))
                else:
                    seen, notified = known[vid]
                    c.execute("UPDATE videos SET seen_count=? WHERE aweme_id=?", (seen + 1, vid))
                    # 注意：不要再要求 expected_new > 0。插入队列时已经用「作品数确实涨了」
                    # 过滤过一次；这里若再要求一次，账号发完就停（下轮作品数不再涨）时，
                    # 真新作品会永久卡在未报警状态（实测：非洲蔡 2026-09-02 那条被卡死）。
                    # 只需二次确认 + 已建基线即可放行，队列规模本身已被插入时的配额限死。
                    if (seen + 1 >= 2 and not notified and baselined
                            and len(new_videos) < 5):
                        new_videos.append(vid)
                        c.execute("UPDATE videos SET notified=1 WHERE aweme_id=?", (vid,))

            # 新作品判定已完成后，才允许刷新主页作品数据（否则会漏报新作品）
            synced = sync_homepage_videos(c, homepage_items, sec_uid, now, insert_new=False)

            # 粉丝变化
            c.execute("""SELECT follower_count FROM snapshots WHERE sec_uid=? AND ok=1
                         ORDER BY id DESC LIMIT 2""", (sec_uid,))
            rows = [r[0] for r in c.fetchall()]
            delta = (rows[0] - rows[1]) if len(rows) >= 2 and rows[0] is not None and rows[1] is not None else None

            # 常态基线：已采作品点赞数的中位数，用于判断「疑似爆款」
            c.execute("SELECT digg_count FROM videos WHERE sec_uid=? AND digg_count IS NOT NULL",
                      (sec_uid,))
            diggs = sorted(r[0] for r in c.fetchall())
            baseline = diggs[len(diggs) // 2] if diggs else None

            c.execute("""UPDATE accounts SET last_check=?, baselined=1,
                         nickname=COALESCE(?, nickname),
                         douyin_id=COALESCE(?, douyin_id), ip_location=COALESCE(?, ip_location),
                         age=COALESCE(?, age), region=COALESCE(?, region),
                         baseline_digg=?
                         WHERE sec_uid=?""",
                      (now, info.get('nickname'), info.get('douyin_id'), info.get('ip_location'),
                       info.get('age'), info.get('region'), baseline, sec_uid))
            conn.commit()

            line = f"   {info.get('nickname', '?')}: 粉丝 {info.get('follower_count', '?')}"
            if delta is not None and delta != 0:
                line += f" ({'+' if delta > 0 else ''}{delta})"
            print(line + f" | 获赞 {info.get('total_favorited', '?')} | 作品 {info.get('aweme_count', '?')}")
            if new_videos:
                print(f"   🆕 新增 {len(new_videos)} 个作品")
                video_details = []
                # 单次巡查抓取上限，避免账号批量更新时任务无限拉长
                to_fetch = new_videos[:MAX_DETAIL_FETCH]
                if len(new_videos) > MAX_DETAIL_FETCH:
                    print(f"      （本次仅处理前 {MAX_DETAIL_FETCH} 条，其余下轮继续）")
                for vid in to_fetch:
                    try:
                        page.get(f"https://www.douyin.com/video/{vid}")
                        time.sleep(5)
                        det = extract_video_detail(page)
                        comments = []
                        if fetch_comments:
                            for _ in range(60):
                                page.scroll.down(400)
                                time.sleep(0.2)
                            comments = extract_comments_from_page(page)
                        # 注意：详情抓取可能部分字段为 None（风控/渲染失败）。
                        # 必须用 COALESCE 保留主页同步来的旧值，否则会把已知点赞数抹成 NULL。
                        c.execute("""UPDATE videos SET
                                       title=COALESCE(NULLIF(?, ''), title),
                                       publish_time=COALESCE(NULLIF(?, ''), publish_time),
                                       digg_count=COALESCE(?, digg_count),
                                       comment_count=COALESCE(?, comment_count),
                                       collect_count=COALESCE(?, collect_count),
                                       share_count=COALESCE(?, share_count),
                                       detail_fetched_at=?
                                     WHERE aweme_id=?""",
                                  (det.get('title'), det.get('publish_time'), det.get('digg_count'),
                                   det.get('comment_count'), det.get('collect_count'),
                                   det.get('share_count'), now, vid))
                        for cm in comments:
                            c.execute("""INSERT OR IGNORE INTO comments (aweme_id, content, fetched_at)
                                         VALUES (?,?,?)""", (vid, cm, now))
                        conn.commit()
                        video_details.append({'aweme_id': vid, **det,
                                              'comments_collected': len(comments)})
                        print(f"      📊 {vid} 赞{det.get('digg_count')} 评{det.get('comment_count')} "
                              f"藏{det.get('collect_count')} 转{det.get('share_count')} "
                              f"| 评论 {len(comments)} 条")
                        if det.get('title'):
                            print(f"         {det['title'][:60]}")
                    except Exception as e:
                        print(f"      ⚠️  {vid} 抓取失败: {e}")
                        video_details.append({'aweme_id': vid, 'error': str(e)})
                changes.append({'sec_uid': sec_uid, 'nickname': info.get('nickname'),
                                'new_videos': new_videos, 'video_details': video_details,
                                'follower_delta': delta})
            else:
                print("   无新作品")

        if changes:
            out = DATA_DIR / f"changes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(changes, f, ensure_ascii=False, indent=2)
            print(f"\n📝 变化明细: {out}")
        return 0
    finally:
        page.quit()
        conn.close()


def cmd_list():
    conn = init_db()
    c = conn.cursor()
    c.execute("""SELECT a.sec_uid, a.nickname, a.added_at, a.last_check, s.follower_count,
                        s.total_favorited, s.aweme_count, s.checked_at
                 FROM accounts a LEFT JOIN snapshots s ON s.id = (
                    SELECT id FROM snapshots WHERE sec_uid=a.sec_uid AND ok=1 ORDER BY id DESC LIMIT 1)
                 WHERE a.active=1 ORDER BY a.added_at""")
    rows = c.fetchall()
    if not rows:
        print("监控名单为空。")
    for r in rows:
        print(f"• {r[1] or '?'}  ({r[0]})")
        print(f"  粉丝 {r[4]} | 获赞 {r[5]} | 作品 {r[6]}")
        print(f"  加入 {r[2]} | 上次巡查 {r[3]} | 数据时间 {r[7]}")
    conn.close()
    return 0


def cmd_report(sec_uid: str):
    conn = init_db()
    c = conn.cursor()
    c.execute("SELECT nickname FROM accounts WHERE sec_uid=?", (sec_uid,))
    row = c.fetchone()
    nickname = row[0] if row else sec_uid
    c.execute("""SELECT checked_at, follower_count, total_favorited, aweme_count
                 FROM snapshots WHERE sec_uid=? AND ok=1 ORDER BY id""", (sec_uid,))
    snaps = c.fetchall()
    print(f"# {nickname} 监控趋势 ({sec_uid})")
    print(f"共 {len(snaps)} 次快照\n")
    print("| 时间 | 粉丝 | 获赞 | 作品 |")
    print("|---|---|---|---|")
    for s in snaps:
        print(f"| {s[0]} | {s[1]} | {s[2]} | {s[3]} |")
    if len(snaps) >= 2:
        first, last = snaps[0], snaps[-1]
        if first[1] is not None and last[1] is not None:
            print(f"\n粉丝变化: {last[1] - first[1]:+d}（{first[1]} → {last[1]}）")
        if first[3] is not None and last[3] is not None:
            print(f"作品变化: {last[3] - first[3]:+d}（{first[3]} → {last[3]}）")
    conn.close()
    return 0


def cmd_detail(vid: str, fetch_comments: bool = True):
    """手动补抓单个视频的详情与评论（未自动抓到时用）"""
    conn = init_db()
    page = open_browser()
    try:
        if not ensure_login(page):
            print("❌ 登录失败")
            return 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        page.get(f"https://www.douyin.com/video/{vid}")
        time.sleep(5)
        det = extract_video_detail(page)
        comments = []
        if fetch_comments:
            for _ in range(60):
                page.scroll.down(400)
                time.sleep(0.2)
            comments = extract_comments_from_page(page)

        c = conn.cursor()
        c.execute("""INSERT OR IGNORE INTO videos (aweme_id, sec_uid, discovered_at, seen_count, notified)
                     VALUES (?,?,?,2,1)""", (vid, 'manual', now))
        # 同上：COALESCE 保护，避免 None 覆盖已有数值。
        c.execute("""UPDATE videos SET
                       title=COALESCE(NULLIF(?, ''), title),
                       publish_time=COALESCE(NULLIF(?, ''), publish_time),
                       digg_count=COALESCE(?, digg_count),
                       comment_count=COALESCE(?, comment_count),
                       collect_count=COALESCE(?, collect_count),
                       share_count=COALESCE(?, share_count),
                       detail_fetched_at=?
                     WHERE aweme_id=?""",
                  (det.get('title'), det.get('publish_time'), det.get('digg_count'),
                   det.get('comment_count'), det.get('collect_count'), det.get('share_count'),
                   now, vid))
        for cm in comments:
            c.execute("""INSERT OR IGNORE INTO comments (aweme_id, content, fetched_at)
                         VALUES (?,?,?)""", (vid, cm, now))
        conn.commit()
        print(f"✅ {vid}")
        print(f"   文案: {det.get('title', '?')[:80]}")
        print(f"   点赞 {det.get('digg_count')} | 评论 {det.get('comment_count')} | "
              f"收藏 {det.get('collect_count')} | 转发 {det.get('share_count')}")
        print(f"   发布: {det.get('publish_time', '?')} | 抓到评论 {len(comments)} 条")
        return 0
    finally:
        page.quit()
        conn.close()


def cmd_backfill(only_sec_uid: str | None = None):
    """批量补抓已有作品的点赞数（从主页卡片读取，不需要逐个打开视频页）

    用途：为监控名单建立「常态数据基线」。没有基线就无法判断什么叫爆款。
    成本：13 个账号约 6-8 分钟（若逐个打开视频页则要 1 小时以上）。
    """
    conn = init_db()
    c = conn.cursor()
    if only_sec_uid:
        c.execute("SELECT sec_uid, nickname FROM accounts WHERE active=1 AND sec_uid=?", (only_sec_uid,))
    else:
        c.execute("SELECT sec_uid, nickname FROM accounts WHERE active=1 ORDER BY added_at")
    targets = c.fetchall()
    if not targets:
        print("监控名单为空。")
        conn.close()
        return 1

    page = open_browser()
    try:
        if not ensure_login(page):
            print("❌ 登录失败")
            return 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for sec_uid, nickname in targets:
            print(f"\n📥 补数据: {nickname or sec_uid}")
            page.get(f"https://www.douyin.com/user/{sec_uid}")
            time.sleep(6)
            for _ in range(4):
                t = re.search(r'<title>([^<]+)</title>', page.html)
                if t and ('抖音' in t.group(1) or '的主页' in t.group(1)):
                    break
                time.sleep(3)
            info = extract_account_from_homepage(page)   # 内部已滚动加载
            items = extract_homepage_videos(page)
            n = sync_homepage_videos(c, items, sec_uid, now, insert_new=True)

            c.execute("SELECT digg_count FROM videos WHERE sec_uid=? AND digg_count IS NOT NULL",
                      (sec_uid,))
            diggs = sorted(r[0] for r in c.fetchall())
            baseline = diggs[len(diggs) // 2] if diggs else None
            c.execute("""UPDATE accounts SET nickname=COALESCE(?, nickname),
                         douyin_id=COALESCE(?, douyin_id), ip_location=COALESCE(?, ip_location),
                         age=COALESCE(?, age), region=COALESCE(?, region),
                         baseline_digg=? WHERE sec_uid=?""",
                      (info.get('nickname'), info.get('douyin_id'), info.get('ip_location'),
                       info.get('age'), info.get('region'), baseline, sec_uid))
            conn.commit()

            extra = []
            if info.get('ip_location'):
                extra.append(f"IP {info['ip_location']}")
            if info.get('douyin_id'):
                extra.append(f"抖音号 {info['douyin_id']}")
            print(f"   补入 {n} 条作品 | 点赞中位数 {baseline}"
                  + (f" | {' | '.join(extra)}" if extra else ""))
            if diggs:
                print(f"   点赞区间 {diggs[0]} ~ {diggs[-1]}")
        return 0
    finally:
        page.quit()
        conn.close()


def cmd_import_existing():
    """从 douyin-comment-analyzer 已分析过的账号批量导入，复用其 user_info.json 建立基线

    好处：零浏览器开销。这些账号主页已被抓过，直接拿历史数据当基线，
    新增作品只可能出现在基线之后的巡查中。
    """
    base = Path.home() / ".workbuddy/douyin_analysis"
    if not base.exists():
        print("❌ 未找到 ~/.workbuddy/douyin_analysis")
        return 1
    conn = init_db()
    c = conn.cursor()
    imported, skipped = 0, 0
    for d in sorted(base.glob("account_*")):
        f = d / "user_info.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"  ⚠️  读取失败 {d.name}: {e}")
            continue
        sec_uid = data.get('sec_uid')
        if not sec_uid:
            print(f"  ⚠️  {d.name} 无 sec_uid，跳过")
            continue
        c.execute("SELECT 1 FROM accounts WHERE sec_uid=?", (sec_uid,))
        if c.fetchone():
            skipped += 1
            print(f"  ⏭  已在名单: {data.get('nickname', sec_uid)}")
            continue
        # 用文件修改时间作为该快照的时间点（即当初那次分析的时刻）
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""INSERT INTO accounts (sec_uid, nickname, signature, source_url, added_at, last_check, active)
                     VALUES (?,?,?,?,?,?,1)""",
                  (sec_uid, data.get('nickname'), data.get('signature'),
                   data.get('source_url'), ts, ts))
        c.execute("""INSERT INTO snapshots
                     (sec_uid, checked_at, follower_count, total_favorited, aweme_count, video_count_seen, ok)
                     VALUES (?,?,?,?,?,?,1)""",
                  (sec_uid, ts, data.get('follower_count'), data.get('total_favorited'),
                   data.get('aweme_count'), len(data.get('video_ids', []))))
        # 基线视频：全部标记为已确认，避免首次巡查误报
        for vid in data.get('video_ids', []):
            c.execute("""INSERT OR IGNORE INTO videos (aweme_id, sec_uid, discovered_at, seen_count, notified)
                         VALUES (?,?,?,2,1)""", (vid, sec_uid, ts))
        imported += 1
        print(f"  ✅ {data.get('nickname', sec_uid)}: 粉丝 {data.get('follower_count')} | "
              f"作品 {data.get('aweme_count')} | 基线 {len(data.get('video_ids', []))} 条 "
              f"(数据时间 {ts})")
    conn.commit()
    print(f"\n导入 {imported} 个账号，跳过 {skipped} 个（已在名单中）")
    conn.close()
    return 0


def cmd_videos(sec_uid: str, top: int = 20):
    """列出该账号已采集数据的作品，按点赞降序 —— 看哪条爆了"""
    conn = init_db()
    c = conn.cursor()
    c.execute("""SELECT aweme_id, title, publish_time, digg_count, comment_count,
                        collect_count, share_count, discovered_at
                 FROM videos WHERE sec_uid=? AND digg_count IS NOT NULL
                 ORDER BY COALESCE(digg_count, 0) DESC LIMIT ?""", (sec_uid, top))
    rows = c.fetchall()
    if not rows:
        print("该账号暂无作品数据。跑一次 backfill 补数据：")
        print(f"  python3 monitor.py backfill {sec_uid}")
    else:
        # 常态基线，便于对照判断爆款
        c.execute("SELECT baseline_digg FROM accounts WHERE sec_uid=?", (sec_uid,))
        br = c.fetchone()
        base = br[0] if br and br[0] else None
        print("| 点赞 | 倍数 | 评论 | 收藏 | 转发 | 发布 | 文案 |")
        print("|---|---|---|---|---|---|---|")
        for r in rows:
            title = (r[1] or '').replace('|', '/')[:40]
            ratio = f"{r[3] / base:.1f}x" if base and r[3] else "-"
            print(f"| {r[3]} | {ratio} | {r[4] or '-'} | {r[5] or '-'} | {r[6] or '-'} | "
                  f"{r[2] or '?'} | {title} |")
        print(f"\n共 {len(rows)} 条（按点赞降序）")
        if base:
            print(f"常态基线（中位数）：{base} 赞")
    conn.close()
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    no_comments = '--no-comments' in args
    args = [a for a in args if not a.startswith('--')]
    if cmd == 'add' and args:
        sys.exit(cmd_add(args[0]))
    elif cmd == 'run':
        sys.exit(cmd_run(args[0] if args else None, fetch_comments=not no_comments))
    elif cmd == 'list':
        sys.exit(cmd_list())
    elif cmd == 'report' and args:
        sys.exit(cmd_report(args[0]))
    elif cmd == 'detail' and args:
        sys.exit(cmd_detail(args[0], fetch_comments=not no_comments))
    elif cmd == 'backfill':
        sys.exit(cmd_backfill(args[0] if args else None))
    elif cmd == 'import-existing':
        sys.exit(cmd_import_existing())
    elif cmd == 'videos' and args:
        sys.exit(cmd_videos(args[0], int(args[1]) if len(args) > 1 and args[1].isdigit() else 20))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
