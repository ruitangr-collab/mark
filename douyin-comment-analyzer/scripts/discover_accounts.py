#!/usr/bin/env python3
"""
抖音「中国人做的非洲商贸城/中国城/产业园」账号发现脚本

用途：按关键词批量搜索抖音用户 tab，提取账号（昵称 + sec_uid + 粉丝 + 签名），
      自动识别项目名与国家，输出「账号 × 项目 × 国家」清单。

用法:
  python3 discover_accounts.py                          # 用默认关键词表
  python3 discover_accounts.py "安哥拉世纪城,非洲商贸城"   # 指定关键词
  python3 discover_accounts.py --min-fans 500           # 粉丝门槛（默认300）
  python3 discover_accounts.py --no-filter              # 不做非洲相关性过滤
  python3 discover_accounts.py --suffix reverse         # 输出文件加后缀（避免覆盖同日其他搜索）

输出:
  ~/.workbuddy/douyin_analysis/_discovery/accounts_<日期>.json
  ~/.workbuddy/douyin_analysis/_discovery/accounts_<日期>.md

2026-09 验证要点:
  - 搜索页必须用 ?type=user（用户 tab），视频 tab 的 RENDER_DATA 无作者数据
  - headless 会被风控，用 --start-minimized
  - 用户卡片：a[href*="/user/MS4w"]，取父容器文本解析昵称/抖音号/获赞/粉丝/签名
"""
import sys, json, re, time
from pathlib import Path
from urllib.parse import quote
from DrissionPage import ChromiumPage, ChromiumOptions

SKILL = Path.home() / '.workbuddy' / 'skills' / 'douyin-comment-analyzer' / 'scripts'
sys.path.insert(0, str(SKILL))
from common import is_logged_in, wait_for_login  # noqa: E402

PROFILE_DIR = Path.home() / ".workbuddy/douyin_chrome_profile"
OUTPUT_DIR = Path.home() / ".workbuddy/douyin_analysis" / "_discovery"

# 默认关键词表：中国人做的非洲商贸城/中国城/产业园
DEFAULT_KEYWORDS = [
    '安哥拉世纪城', '非洲商贸城', '非洲中国城', '中国商贸城', '非洲商城',
    '非洲产业园', '非洲工业园', '非洲唐人街', '非洲小商品城', '非洲中国商城',
    '安哥拉中国城', '尼日利亚商贸城', '坦桑尼亚工业园', '肯尼亚中国城',
    '非洲华人商城', '非洲批发市场', '出海非洲商贸城',
]

# 非洲国家词表（含主要城市）
COUNTRIES = {
    '安哥拉': ['安哥拉', '罗安达'], '尼日利亚': ['尼日利亚', '拉各斯', '卡诺', '奥尼查'],
    '肯尼亚': ['肯尼亚', '内罗毕', '蒙巴萨'], '坦桑尼亚': ['坦桑尼亚', '达累斯萨拉姆', '桑给巴尔'],
    '南非': ['南非', '约翰内斯堡', '开普敦', '德班', '约堡'], '埃及': ['埃及', '开罗', '亚历山大'],
    '埃塞俄比亚': ['埃塞俄比亚', '亚的斯亚贝巴'], '加纳': ['加纳', '阿克拉', '库马西'],
    '科特迪瓦': ['科特迪瓦', '阿比让', '象牙海岸'], '刚果金': ['刚果金', '刚果（金）', '金沙萨', '卢本巴希'],
    '刚果布': ['刚果布', '布拉柴维尔'], '乌干达': ['乌干达', '坎帕拉'],
    '赞比亚': ['赞比亚', '卢萨卡'], '津巴布韦': ['津巴布韦', '哈拉雷'],
    '莫桑比克': ['莫桑比克', '马普托'], '喀麦隆': ['喀麦隆', '杜阿拉', '雅温得'],
    '塞内加尔': ['塞内加尔', '达喀尔'], '卢旺达': ['卢旺达', '基加利'],
    '几内亚': ['几内亚', '科纳克里'], '马里': ['马里', '巴马科'],
    '布基纳法索': ['布基纳法索', '瓦加杜古'], '贝宁': ['贝宁', '科托努'],
    '多哥': ['多哥', '洛美'], '马达加斯加': ['马达加斯加', '塔那那利佛'],
    '摩洛哥': ['摩洛哥', '卡萨布兰卡'], '阿尔及利亚': ['阿尔及利亚', '阿尔及尔'],
    '纳米比亚': ['纳米比亚', '温得和克'], '博茨瓦纳': ['博茨瓦纳', '哈博罗内'],
    '加蓬': ['加蓬', '利伯维尔'], '马拉维': ['马拉维', '利隆圭'],
    '利比里亚': ['利比里亚', '蒙罗维亚'], '塞拉利昂': ['塞拉利昂', '弗里敦'],
    '毛里求斯': ['毛里求斯'], '佛得角': ['佛得角'], '吉布提': ['吉布提'],
}

# 项目类型词表
PROJECT_TYPES = {
    '商贸城': ['商贸城', '商贸中心', '商贸广场', '世纪城', '商贸'],
    '中国城': ['中国城', '中国商城', '中国商品城', '唐人街', '华人街'],
    '产业园': ['产业园', '工业园', '工业区', '开发区', '经济区', '经济特区', '园区'],
    '批发市场': ['批发市场', '小商品城', '百货城', '批城', '货源基地'],
    '商城/市场': ['商城', '市场', '商厦', '购物中心'],
    '海外仓/展厅': ['海外仓', '展厅', '选品中心', '展销中心', '仓储'],
}


def parse_count(text: str) -> int:
    """解析 '2.9万' / '1049' / '1.2亿' → 整数"""
    m = re.search(r'([\d.]+)\s*(亿|万|w|W)?', text or '')
    if not m:
        return 0
    try:
        n = float(m.group(1))
    except ValueError:
        return 0
    unit = m.group(2)
    if unit == '亿':
        n *= 100000000
    elif unit in ('万', 'w', 'W'):
        n *= 10000
    return int(n)


def detect_countries(text: str) -> list[str]:
    return [c for c, kws in COUNTRIES.items() if any(k in text for k in kws)]


def detect_projects(text: str) -> list[str]:
    return [t for t, kws in PROJECT_TYPES.items() if any(k in text for k in kws)]


def parse_card_text(text: str, sec_uid: str) -> dict:
    """解析用户卡片文本（li.innerText 结构）：
        昵称
        关注
        抖音号: <id><获赞数>获赞<粉丝数>粉丝
        签名

    【2026-09-05 修正 · 数值在前、标签在后】
    旧版按「标签在前」解析（把「获赞」前的数当成粉丝数），导致 likes / followers
    整体互换。实测：某号卡片给出 33.6万获赞 / 12.4万粉丝，旧代码存成
    粉丝 33.6万、获赞 12.4万——与主页真实值恰好对调，粉丝变化量因此出现巨额负数。
    连带影响：入库门槛 `followers >= min_fans` 一直卡的是获赞数而非粉丝数。
    """
    lines = [l.strip() for l in (text or '').split('\n') if l.strip()]
    drop = {'关注', '私信', '已关注', '私密账号', '直播中', '求更新'}
    lines = [l for l in lines if l not in drop]

    nick = lines[0] if lines else ''
    douyin_id, likes, fans = '', 0, 0
    sig_lines, hit_id_line = [], False

    UNIT = r'(?:亿|万|w|W)'

    for l in lines[1:]:
        if l.startswith('抖音号:') or l.startswith('抖音号：'):
            hit_id_line = True
            # 数值在前、标签在后：<获赞数>获赞<粉丝数>粉丝
            m = re.search(rf'([\d.]+{UNIT}?)\s*获赞\s*([\d.]+{UNIT}?)\s*粉丝', l)
            if m:
                # 无单位的裸数多半是抖音号尾数（如 ft058113903），不能当获赞数
                if re.search(rf'{UNIT}$', m.group(1) or ''):
                    likes = parse_count(m.group(1))
                # 【2026-09-14 修复 · 粉丝独立解析】
                # 旧版把粉丝解析写在「获赞带单位」这个 if 里面，导致获赞 <1万
                # （卡片显示裸数、无 万/亿 单位）的账号，粉丝被一并清零。
                # 后果：「粉丝 ≥1000」入库门槛对这类号完全失效 —— 出海服务号多为
                # 中小号，获赞常在 1万 以下，于是长期被静默漏掉。
                # 实证（2026-09-12~14 三日一致）：候选里有粉丝值的 100% 获赞 ≥1万；
                # 无粉丝值的占绝大多数，且 service 属性候选几乎全为 0。
                # 注：group(2) 位于「获赞…粉丝」之间，语义唯一，裸数也是合法粉丝数。
                fans = parse_count(m.group(2))
                # 上限校验：抖音粉丝无超过 5000万 的号
                if fans > 50000000:
                    fans = 0
                prefix = l[:m.start()]
            else:
                prefix = l
            prefix = re.sub(r'^抖音号[:：]\s*', '', prefix).strip()
            douyin_id = prefix
        elif hit_id_line and len(l) > 3:
            sig_lines.append(l)
        elif not hit_id_line and l != nick and len(l) > 6:
            sig_lines.append(l)

    # 签名：取最长的一条（通常是简介），去掉与昵称重复
    sig = ''
    cands = [s for s in sig_lines if s != nick]
    if cands:
        sig = max(cands, key=len)

    full = ' '.join([nick, sig])
    return {
        'nickname': nick, 'sec_uid': sec_uid, 'douyin_id': douyin_id,
        'likes': likes, 'followers': fans, 'signature': sig,
        'countries': detect_countries(full),
        'projects': detect_projects(full),
    }


def extract_cards(page) -> list[dict]:
    """从搜索页用户 tab 提取账号卡片。

    2026-09 验证：卡片容器是 <li>（a[href*="/user/"] 的父容器不是完整卡片），
    筛选同时含「抖音号」和「粉丝」的 li，再从内部 a 标签取 sec_uid。
    """
    cards, seen = [], set()
    for li in page.eles('css:li'):
        try:
            text = li.raw_text or ''
        except Exception:
            continue
        if '抖音号' not in text or '粉丝' not in text:
            continue
        # 取 sec_uid
        try:
            a = li.ele('css:a[href*="/user/MS4w"]', timeout=0.5)
            href = a.attr('href') or ''
        except Exception:
            continue
        m = re.search(r'/user/(MS4wLjABAAAA[A-Za-z0-9_\-]{20,})', href)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        cards.append(parse_card_text(text, m.group(1)))
    return cards


# 项目名种子清洗：从国家/城市词开始截断，去掉开头噪音
# （如「夫球场的人安哥拉世纪城」→「安哥拉世纪城」，「小刘在安哥拉中国城」→「安哥拉中国城」）
SEED_STOP = ('本地市场', '非洲市场', '东非市场', '非洲工业园', '自有海外仓',
             '非洲自营海外仓', '埃及自营海外仓', '开拓市场', '国际市场')


def clean_seed(name: str) -> str | None:
    """把抽取的项目名清洗成可用作抖音搜索的关键词"""
    n = (name or '').strip()
    if not n or len(n) < 3 or n in SEED_STOP:
        return None
    if any(w in n for w in ('打通', '开拓', '提供', '合作', '就职', '专注', '旗下')):
        return None
    # 从第一个国家/城市词开始截断
    best = None
    for kws in COUNTRIES.values():
        for k in kws:
            i = n.find(k)
            if i > 0 and (best is None or i < best):
                best = i
    if best:
        n = n[best:]
    return n if len(n) >= 3 else None


def load_project_seeds(limit: int = 20) -> list[str]:
    """从项目主清单提取搜索种子（滚雪球：用已发现的项目名反查更多关联账号）"""
    f = OUTPUT_DIR / 'projects_master.json'
    if not f.exists():
        return []
    data = json.load(open(f, encoding='utf-8'))
    items = [(p['project'], p['account_count']) for p in data.get('projects', [])]
    items.sort(key=lambda x: -x[1])          # 关联账号多的优先
    seeds = []
    for name, _ in items:
        s = clean_seed(name)
        if s and s not in seeds:
            seeds.append(s)
        if len(seeds) >= limit:
            break
    return seeds


def search_keyword(page, kw: str, scroll: int = 5) -> list[dict]:
    """搜索单个关键词的用户 tab"""
    url = f'https://www.douyin.com/search/{quote(kw)}?type=user'
    page.get(url)
    time.sleep(10)
    # 自愈：空壳页重试
    for _ in range(2):
        if len(page.html) > 100000:
            break
        page.get(url)
        time.sleep(10)
    for _ in range(scroll):
        page.scroll.down(700)
        time.sleep(0.8)
    time.sleep(2)
    cards = extract_cards(page)
    for c in cards:
        c['source_keyword'] = kw
    print(f"  「{kw}」→ {len(cards)} 个账号")
    return cards


def main():
    args = [a for a in sys.argv[1:]]
    min_fans = 300
    do_filter = True
    if '--min-fans' in args:
        i = args.index('--min-fans')
        min_fans = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    if '--no-filter' in args:
        do_filter = False
        args.remove('--no-filter')
    # 输出后缀（如 --suffix reverse → accounts_<日期>_reverse.json）
    suffix_extra = ''
    if '--suffix' in args:
        i = args.index('--suffix')
        if i + 1 < len(args):
            suffix_extra = '_' + args[i + 1].strip().lstrip('_')
        args = args[:i] + args[i + 2:]
    # 滚雪球模式：用项目库里的项目名作为搜索种子
    from_projects = '--from-projects' in args
    if from_projects:
        args.remove('--from-projects')
    seed_limit = 20
    if '--limit' in args:
        i = args.index('--limit')
        seed_limit = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    if from_projects:
        keywords = load_project_seeds(seed_limit)
        # 允许追加额外关键词（如用户指定的人名/项目名）
        if args:
            keywords += [k.strip() for k in args[0].split(',') if k.strip()]
        if not keywords:
            print('⚠️ 项目库为空或无可清洗种子，回退到默认关键词')
            keywords = DEFAULT_KEYWORDS
        else:
            print(f'滚雪球模式：从项目库提取 {len(keywords)} 个种子')
    elif args:
        keywords = [k.strip() for k in args[0].split(',') if k.strip()]
    else:
        keywords = DEFAULT_KEYWORDS

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_user_data_path(str(PROFILE_DIR))
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--start-minimized')
    co.set_argument('--no-sandbox')
    page = ChromiumPage(co)

    page.get('https://www.douyin.com/')
    time.sleep(6)
    if not is_logged_in(page):
        print('⚠️ 未登录，等待扫码...')
        wait_for_login(page)

    print(f"搜索 {len(keywords)} 个关键词（用户 tab）")
    all_cards = []
    for kw in keywords:
        try:
            all_cards.extend(search_keyword(page, kw))
        except Exception as e:
            print(f"  「{kw}」失败: {e}")
        time.sleep(2)
    page.quit()

    # 去重（按 sec_uid，保留粉丝多的）
    uniq = {}
    for c in all_cards:
        k = c['sec_uid']
        if k not in uniq or c['followers'] > uniq[k]['followers']:
            uniq[k] = c
    rows = list(uniq.values())

    # 过滤：必须命中非洲国家词（硬条件，否则会混入国内商贸城/产业园）
    # 2026-09 踩坑：若用「国家词 OR 项目词」过滤，会捞进苏州工业园区、镇雄亿联商贸城、
    # 华硕商城等大量国内账号（占 2/3）→ 国家词必须是 AND 条件。
    before = len(rows)
    if do_filter:
        rows = [r for r in rows if r['countries']]
    # 项目账号标记（命中项目类型词 = 商贸城/中国城/产业园/市场类）
    for r in rows:
        r['is_project'] = bool(r['projects'])
    if min_fans > 0:
        # 粉丝门槛只作用于有粉丝数据的账号（无数据的保留，避免误杀）
        rows = [r for r in rows if r['followers'] == 0 or r['followers'] >= min_fans]
    proj_n = sum(1 for r in rows if r['is_project'])
    print(f"\n去重 {before} → 过滤后 {len(rows)} 个（其中项目类账号 {proj_n} 个）")

    # 排序：项目账号优先，其次按粉丝
    rows.sort(key=lambda x: (not x['is_project'], -x['followers']))
    date = time.strftime('%Y-%m-%d')
    # 滚雪球模式用不同文件名，避免覆盖同日泛词搜索结果（build_project_registry 会自动合并）
    suffix = '_projects' if from_projects else ''
    suffix = suffix + suffix_extra
    base = f'accounts_{date}{suffix}'

    # JSON
    jf = OUTPUT_DIR / f'{base}.json'
    jf.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')

    # Markdown
    md = [f"# 抖音非洲商贸城/中国城 账号发现清单（{date}"
          f"{'· 项目名滚雪球' if from_projects else ''}）\n",
          f"- 搜索关键词：{len(keywords)} 个（{'、'.join(keywords)}）",
          f"- 发现账号：{len(rows)} 个，其中项目类 {sum(1 for r in rows if r['is_project'])} 个",
          f"- 排序：项目类账号优先，其次按粉丝数\n",
          "| 项目 | 账号 | 粉丝 | 获赞 | 国家 | 项目类型 | 签名 |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        fans = f"{r['followers']/10000:.1f}万" if r['followers'] >= 10000 else str(r['followers'] or '-')
        md.append(f"| {'✅' if r['is_project'] else ''} | {r['nickname']} | {fans} | {r['likes']} | "
                  f"{'/'.join(r['countries']) or '-'} | {'/'.join(r['projects']) or '-'} | "
                  f"{(r['signature'] or '')[:45]} |")
    mf = OUTPUT_DIR / f'{base}.md'
    mf.write_text('\n'.join(md), encoding='utf-8')

    print(f"\n✅ 输出：\n  {jf}\n  {mf}")
    print(f"\n=== 项目类账号 Top 20 ===")
    n = 0
    for r in rows:
        if not r['is_project']:
            continue
        n += 1
        if n > 20:
            break
        c = '/'.join(r['countries']) or '-'
        p = '/'.join(r['projects'])
        fans = f"{r['followers']/10000:.1f}万" if r['followers'] >= 10000 else str(r['followers'] or '-')
        print(f"{fans:>8} | {c:10s} | {p:12s} | {r['nickname'][:26]} | {(r['signature'] or '')[:34]}")


if __name__ == '__main__':
    main()
