"""
v2: 收紧分类逻辑，区分核心非洲创作者 vs 泛涉及非洲话题的账号
分类规则：
- 核心泛非：昵称含"非洲" OR 覆盖5+国家 AND 非新闻
- 核心单国：昵称含具体国名 OR 该国有3+视频 AND 非新闻
- 其他涉及非洲话题的账号归入"泛涉及"
"""
import json, os, re, sys
from collections import defaultdict, Counter
from statistics import median
sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = 'C:/Users/53185/.workbuddy/skills/douyin-report-search/country_data'
OUTPUT = 'C:/Users/53185/.workbuddy/skills/douyin-report-search/非洲抖音头部账号清单.xlsx'

# ── News/Official/Government filter (aggressive) ──
NEWS_KEYWORDS = [
    # Media / Publishing
    '新闻', '日报', '晚报', '报社', '杂志', '周刊', '早报', '快报',
    'TV', '卫视', '资讯', '网', '广播', '频道', 'CCTV', 'cctv',
    '新华社', '人民日报', '环球', '参考消息', '中国日报', '凤凰', '观察者',
    '头条', '官方发布', '电视台', '传媒', '报道', '时报', '央视频',
    '央视', '观察', '财经网', '新媒体', '融媒体', '融媒',
    '客户端', '官方账号', '发布厅', '发布中心',
    # Financial news
    '财经', '证券', '股市', '金融',
    # Sports media
    '体育', '足球', '懂球帝', '咪咕',
    # Military / Government
    '军事', '国防', '应急管理', '中华人民共和国',
    # Entertainment/other media
    '放映厅', '综艺',
]
# Keywords that ONLY count when in enterprise_verify (not nickname alone)
VERIFY_ONLY_KW = [
    '官方账号', '官方抖音', '融媒体', '融媒', '客户端', '发布厅', '发布中心',
    '中华人民共和国', '放映厅', '综艺', '证券',
]
# Keywords that count in nickname even without enterprise verify
NICKNAME_ONLY_KW = [
    '新闻', '日报', '晚报', 'TV', '卫视', 'cctv', 'CCTV', '广播',
    '新华社', '人民日报', '环球', '参考消息', '中国日报', '凤凰',
]

def is_news(author):
    nickname = (author.get('nickname') or '')
    nickname_lower = nickname.lower()
    enterprise_verify = (author.get('enterprise_verify_reason') or '')
    custom_verify = (author.get('custom_verify') or '')
    ev_lower = enterprise_verify.lower()
    cv_lower = custom_verify.lower()
    combined = (nickname_lower + ' ' + ev_lower + ' ' + cv_lower)

    # 1. Enterprise verify with news/government keyword → filter
    if enterprise_verify:
        for kw in NEWS_KEYWORDS:
            if kw.lower() in ev_lower:
                return True

    # 2. Custom verify with news keyword → filter
    if custom_verify:
        for kw in NEWS_KEYWORDS:
            if kw.lower() in cv_lower:
                return True

    # 3. Nickname has strong news keywords (even without verify) → filter
    for kw in NICKNAME_ONLY_KW:
        if kw.lower() in nickname_lower:
            return True

    # 4. Government/party official: Chinese department naming pattern
    if enterprise_verify:
        gov_patterns = ['中华人民共和国', '部官方', '局官方', '委官方', '应急管理']
        for p in gov_patterns:
            if p in ev_lower:
                return True

    return False

# ── Country names for matching ──
COUNTRY_MAP = {
    '尼日利亚': ['尼日利亚', 'nigeria'],
    '南非': ['南非', 'south africa'],
    '肯尼亚': ['肯尼亚', 'kenya'],
    '埃及': ['埃及', 'egypt'],
    '埃塞俄比亚': ['埃塞俄比亚', 'ethiopia'],
    '加纳': ['加纳', 'ghana'],
    '坦桑尼亚': ['坦桑尼亚', 'tanzania'],
    '乌干达': ['乌干达', 'uganda'],
    '赞比亚': ['赞比亚', 'zambia'],
    '津巴布韦': ['津巴布韦', 'zimbabwe'],
    '莫桑比克': ['莫桑比克', 'mozambique'],
    '安哥拉': ['安哥拉', 'angola'],
    '刚果金': ['刚果金', '刚果', 'congo'],
    '喀麦隆': ['喀麦隆', 'cameroon'],
    '科特迪瓦': ['科特迪瓦', 'cote divoire'],
    '塞内加尔': ['塞内加尔', 'senegal'],
    '几内亚': ['几内亚', 'guinea'],
    '摩洛哥': ['摩洛哥', 'morocco'],
    '阿尔及利亚': ['阿尔及利亚', 'algeria'],
    '卢旺达': ['卢旺达', 'rwanda'],
}

PAN_AFRICA_KW_STRONG = ['非洲', 'africa']

def match_country_in_text(text, country):
    """Check if country name appears in text"""
    t = text.lower()
    for kw in COUNTRY_MAP.get(country, [country]):
        if kw.lower() in t:
            return True
    return False

def match_pan_africa(text):
    t = text.lower()
    return any(kw.lower() in t for kw in PAN_AFRICA_KW_STRONG)

# ── Load data ──
print("Loading data...")
all_videos = []

for fname in sorted(os.listdir(DATA_DIR)):
    if not fname.endswith('.json'):
        continue
    parts = fname.replace('.json', '').split('_')
    country = parts[0]
    keyword = parts[-1] if len(parts) >= 3 else parts[1]
    fpath = os.path.join(DATA_DIR, fname)
    try:
        data = json.loads(open(fpath, encoding='utf-8').read())
    except:
        continue
    for v in data.get('videos', []):
        raw = v.get('_raw') or {}
        author = raw.get('author') or {}
        all_videos.append((v, author, country, keyword, raw))

print(f"Total videos: {len(all_videos)}")

# ── Group by author ──
authors = defaultdict(lambda: {
    'nickname': '',
    'uid': '',
    'follower_count': 0,
    'enterprise_verify_reason': '',
    'custom_verify': '',
    'videos': [],
    'countries': set(),
    'country_video_count': Counter(),  # per-country video count
    'total_likes': 0,
    'total_comments': 0,
    'total_shares': 0,
    'total_collects': 0,
    'descs': [],
    'names_country_match': set(),  # which country names appear in descs
    'africa_mention_count': 0,  # how many videos mention "非洲"
})

news_count = 0
for v, author, country, keyword, raw in all_videos:
    uid = str(author.get('uid', ''))
    if not uid:
        continue
    if is_news(author):
        news_count += 1
        continue

    a = authors[uid]
    a['nickname'] = author.get('nickname', '') or a['nickname']
    a['uid'] = uid
    a['follower_count'] = max(a['follower_count'], author.get('follower_count', 0) or 0)
    a['enterprise_verify_reason'] = author.get('enterprise_verify_reason', '') or a['enterprise_verify_reason']
    a['custom_verify'] = author.get('custom_verify', '') or a['custom_verify']
    a['countries'].add(country)
    a['country_video_count'][country] += 1
    a['videos'].append(v)

    s = v.get('statistics', {})
    a['total_likes'] += s.get('digg_count', 0) or 0
    a['total_comments'] += s.get('comment_count', 0) or 0
    a['total_shares'] += s.get('share_count', 0) or 0
    a['total_collects'] += s.get('collect_count', 0) or 0

    desc = (raw.get('desc') or '')
    a['descs'].append(desc[:120])
    if match_pan_africa(desc):
        a['africa_mention_count'] += 1
    for cname in COUNTRY_MAP:
        if match_country_in_text(desc, cname):
            a['names_country_match'].add(cname)

print(f"News filtered: {news_count}")
print(f"Unique creator authors: {len(authors)}")

# ── Classify into 3 tiers ──
core_pan = []      # Core pan-Africa creators
core_country = []  # Core single-country creators
general_africa = [] # General accounts that touch Africa but aren't focused

for uid, a in authors.items():
    nickname = a['nickname']
    all_descs = ' '.join(a['descs'])
    n_videos = len(a['videos'])
    n_countries = len(a['countries'])
    followers = a['follower_count']
    total_eng = a['total_likes'] + a['total_comments'] + a['total_shares'] + a['total_collects']

    avg_likes = a['total_likes'] / n_videos if n_videos > 0 else 0
    avg_comments = a['total_comments'] / n_videos if n_videos > 0 else 0
    avg_shares = a['total_shares'] / n_videos if n_videos > 0 else 0
    avg_eng = total_eng / n_videos if n_videos > 0 else 0
    epf = avg_eng / followers if followers > 0 else 0
    clr = a['total_comments'] / a['total_likes'] if a['total_likes'] > 0 else 0

    countries_str = '、'.join(sorted(a['countries']))
    verify = a['enterprise_verify_reason'] or a['custom_verify'] or '无认证'
    sample_desc = a['descs'][0][:100] if a['descs'] else ''

    # Determine primary country (most videos)
    primary = a['country_video_count'].most_common(1)
    primary_country = primary[0][0] if primary else '未知'
    primary_n = primary[0][1] if primary else 0

    # Africa relevance: what % of sampled videos mention Africa?
    africa_relevance = a['africa_mention_count'] / n_videos if n_videos > 0 else 0

    # Country relevance: what % of sampled videos mention the primary country?
    country_mentions = 0
    for desc in a['descs']:
        if match_country_in_text(desc, primary_country):
            country_mentions += 1
    country_relevance = country_mentions / n_videos if n_videos > 0 else 0

    # ── Classification logic ──
    has_africa_in_name = match_pan_africa(nickname)

    # Core pan-Africa: nickname contains "非洲" AND (covers 3+ countries OR 50%+ videos mention Africa)
    is_core_pan = has_africa_in_name and (n_countries >= 3 or africa_relevance >= 0.5)

    # Core single-country: nickname contains country name AND has 3+ videos in that country
    has_country_in_name = False
    matched_country = None
    for cname in COUNTRY_MAP:
        if match_country_in_text(nickname, cname):
            has_country_in_name = True
            matched_country = cname
            break

    is_core_country = has_country_in_name and primary_n >= 3

    tier = 'general'
    tier_reason = ''

    if is_core_pan:
        tier = '核心泛非'
        tier_reason = f'昵称含非洲 + 覆盖{n_countries}国'
        if africa_relevance >= 0.5:
            tier_reason += f' + {africa_relevance:.0%}视频提及非洲'
    elif is_core_country:
        tier = '核心单国'
        tier_reason = f'昵称含"{matched_country}" + 该国{primary_n}条视频'
    elif has_africa_in_name:
        tier = '泛非洲相关'
        tier_reason = f'昵称含非洲但覆盖{n_countries}国(<3)'
    elif n_countries >= 5:
        tier = '多国旅行'
        tier_reason = f'覆盖{n_countries}国(旅行博主)'
    elif africa_relevance >= 0.5 or country_relevance >= 0.5:
        tier = '高相关'
        tier_reason = f'非洲相关度{africa_relevance:.0%} / {primary_country}相关度{country_relevance:.0%}'
    else:
        tier = '泛涉及'
        tier_reason = f'非洲相关度{africa_relevance:.0%}'

    record = {
        'nickname': nickname,
        'uid': uid,
        'follower_count': followers,
        'n_videos_in_sample': n_videos,
        'n_countries': n_countries,
        'countries': countries_str,
        'primary_country': primary_country,
        'primary_country_videos': primary_n,
        'tier': tier,
        'tier_reason': tier_reason,
        'africa_relevance': round(africa_relevance, 3),
        'country_relevance': round(country_relevance, 3),
        'verify': verify,
        'total_likes': a['total_likes'],
        'total_comments': a['total_comments'],
        'total_shares': a['total_shares'],
        'total_eng': total_eng,
        'avg_likes': round(avg_likes, 1),
        'avg_comments': round(avg_comments, 1),
        'avg_eng': round(avg_eng, 1),
        'avg_clr': round(clr, 4),
        'epf': round(epf, 6),
        'sample_desc': sample_desc,
    }

    if is_core_pan:
        core_pan.append(record)
    elif is_core_country:
        core_country.append(record)
    else:
        general_africa.append(record)

# Sort
core_pan.sort(key=lambda x: (-x['follower_count'], -x['total_eng']))
core_country.sort(key=lambda x: (-x['follower_count'], -x['total_eng']))

# Group country authors by their primary country
country_groups_core = defaultdict(list)
for a in core_country:
    country_groups_core[a['primary_country']].append(a)

# Group general accounts by country too
country_groups_general = defaultdict(list)
for a in general_africa:
    country_groups_general[a['primary_country']].append(a)

print(f"\nCore Pan-Africa: {len(core_pan)}")
print(f"Core Single-Country: {len(core_country)}")
print(f"General Africa-related: {len(general_africa)}")

# ── Excel output ──
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

wb = Workbook()

header_font = Font(name='微软雅黑', bold=True, size=11, color='FFFFFF')
header_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
pan_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
country_fill = PatternFill(start_color='DAEEF3', end_color='DAEEF3', fill_type='solid')
general_fill = PatternFill(start_color='FDE9D9', end_color='FDE9D9', fill_type='solid')
header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
cell_align = Alignment(vertical='center', wrap_text=True)
thin_border = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9'),
)

def write_header(ws, headers, widths, start_row=1):
    for col_idx, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=start_row, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = w

def write_row(ws, row_idx, data, fill=None):
    for col_idx, val in enumerate(data, 1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.alignment = cell_align
        cell.border = thin_border
        cell.font = Font(name='微软雅黑', size=10)
        if fill:
            cell.fill = fill

def fmt_num(n):
    if n >= 100000000:
        return f'{n/100000000:.1f}亿'
    elif n >= 10000:
        return f'{n/10000:.1f}万'
    else:
        return str(int(n))

# ── Sheet 1: 核心泛非账号 ──
ws1 = wb.active
ws1.title = '核心泛非账号'

headers = ['排名', '账号昵称', '抖音UID', '粉丝数', '样本视频数', '覆盖国家数',
           '覆盖国家', '分类理由', '非洲相关度', '认证', '均赞', '均评',
           '均互动', '评赞比', '粉均互动率', '简介摘要']
widths = [6, 18, 20, 12, 10, 10, 28, 30, 10, 14, 10, 10, 10, 10, 12, 45]
write_header(ws1, headers, widths)

for i, a in enumerate(core_pan):
    row = i + 2
    write_row(ws1, row, [
        i + 1, a['nickname'], a['uid'], fmt_num(a['follower_count']),
        a['n_videos_in_sample'], a['n_countries'], a['countries'],
        a['tier_reason'], f"{a['africa_relevance']:.0%}",
        a['verify'], fmt_num(a['avg_likes']), fmt_num(a['avg_comments']),
        fmt_num(a['avg_eng']), a['avg_clr'], a['epf'], a['sample_desc'],
    ], fill=pan_fill if i % 2 == 0 else None)
ws1.freeze_panes = 'A2'

# ── Sheet 2: 核心单国账号 ──
ws2 = wb.create_sheet(title='核心单国账号')
headers2 = ['排名', '账号昵称', '抖音UID', '粉丝数', '主要国家', '该国视频数',
            '样本视频数', '分类理由', '国名相关度', '认证', '均赞', '均评',
            '均互动', '评赞比', '粉均互动率', '简介摘要']
widths2 = [6, 18, 20, 12, 10, 10, 10, 30, 10, 14, 10, 10, 10, 10, 12, 45]
write_header(ws2, headers2, widths2)

rank = 0
for a in core_country:
    rank += 1
    write_row(ws2, rank + 1, [
        rank, a['nickname'], a['uid'], fmt_num(a['follower_count']),
        a['primary_country'], a['primary_country_videos'],
        a['n_videos_in_sample'], a['tier_reason'],
        f"{a['country_relevance']:.0%}",
        a['verify'], fmt_num(a['avg_likes']), fmt_num(a['avg_comments']),
        fmt_num(a['avg_eng']), a['avg_clr'], a['epf'], a['sample_desc'],
    ], fill=country_fill if rank % 2 == 0 else None)
ws2.freeze_panes = 'A2'

# ── Sheet 3-7: 各国高相关账号 (按国别) ──
# Combine core_country + high-relevance general accounts
all_countries = sorted(set(
    list(country_groups_core.keys()) + list(country_groups_general.keys())
))

# Create one sheet per country for the major ones
# For countries with many accounts, show top 30
for country in all_countries:
    combined = []
    seen = set()

    # Core accounts first
    for a in country_groups_core.get(country, []):
        if a['uid'] not in seen:
            seen.add(a['uid'])
            combined.append((a, '核心'))

    # Then high-relevance general accounts (africa_relevance >= 0.3 or country_relevance >= 0.3)
    for a in sorted(country_groups_general.get(country, []), key=lambda x: -x['follower_count']):
        if a['uid'] not in seen and (a['africa_relevance'] >= 0.3 or a['country_relevance'] >= 0.3):
            seen.add(a['uid'])
            combined.append((a, '相关'))

    if not combined:
        continue

    # Sort: core first, then by followers
    combined.sort(key=lambda x: (0 if x[1] == '核心' else 1, -x[0]['follower_count']))

    sheet_name = country[:31]
    try:
        ws = wb.create_sheet(title=sheet_name)
    except:
        ws = wb.create_sheet(title=f'{country[:28]}_2')

    ctry_headers = ['排名', '类型', '账号昵称', '抖音UID', '粉丝数', '视频数',
                    '认证', '均赞', '均评', '均互动', '评赞比', '简介摘要']
    ctry_widths = [6, 8, 18, 20, 12, 8, 14, 10, 10, 10, 10, 50]
    write_header(ws, ctry_headers, ctry_widths)

    for i, (a, typ) in enumerate(combined[:50]):
        row = i + 2
        fill = country_fill if typ == '核心' else None
        write_row(ws, row, [
            i + 1, typ, a['nickname'], a['uid'], fmt_num(a['follower_count']),
            a['n_videos_in_sample'], a['verify'],
            fmt_num(a['avg_likes']), fmt_num(a['avg_comments']),
            fmt_num(a['avg_eng']), a['avg_clr'], a['sample_desc'],
        ], fill=fill)
    ws.freeze_panes = 'A2'

# ── Sheet: 汇总统计 ──
ws_s = wb.create_sheet(title='汇总统计')
ws_s.cell(row=1, column=1, value='非洲抖音赛道账号分类汇总').font = Font(name='微软雅黑', bold=True, size=14, color='2F5496')

sum_headers = ['分类', '账号数', '粉丝中位数', '均赞中位数', '均评中位数', '评赞比中位数', '说明']
sum_widths = [16, 10, 14, 14, 14, 14, 40]
write_header(ws_s, sum_headers, sum_widths, start_row=2)

# Stats per tier
def tier_stats(accounts, tier_name, desc, row_start):
    if not accounts:
        return row_start
    fcs = [a['follower_count'] for a in accounts if a['follower_count'] > 0]
    als = [a['avg_likes'] for a in accounts]
    acs = [a['avg_comments'] for a in accounts]
    clrs = [a['avg_clr'] for a in accounts if a['avg_clr'] > 0]
    write_row(ws_s, row_start, [
        tier_name, len(accounts),
        fmt_num(median(fcs)) if fcs else '-',
        fmt_num(median(als)) if als else '-',
        fmt_num(median(acs)) if acs else '-',
        round(median(clrs), 4) if clrs else '-',
        desc,
    ])
    return row_start + 1

r = 4
r = tier_stats(core_pan, '核心泛非', '昵称含"非洲" + 覆盖3+国家或高非洲相关度', r)
r = tier_stats(core_country, '核心单国', '昵称含具体国名 + 该国有3+视频', r)

general_tiers = defaultdict(list)
for a in general_africa:
    general_tiers[a['tier']].append(a)
for tname in ['泛非洲相关', '多国旅行', '高相关', '泛涉及']:
    if general_tiers[tname]:
        desc_map = {
            '泛非洲相关': '昵称含非洲但覆盖<3国',
            '多国旅行': '覆盖5+国的旅行博主',
            '高相关': '50%+视频提及非洲或特定国家',
            '泛涉及': '偶尔提及非洲话题',
        }
        r = tier_stats(general_tiers[tname], tname, desc_map.get(tname, ''), r)

# Grand total
ws_s.merge_cells(f'A{r}:G{r}')
total_unique = len(core_pan) + len(core_country) + len(general_africa)
ws_s.cell(row=r, column=1, value=f'总计 {total_unique} 个创作者账号（核心泛非{len(core_pan)} + 核心单国{len(core_country)} + 泛涉及{len(general_africa)}）').font = Font(name='微软雅黑', bold=True, size=11)

ws_s.freeze_panes = 'A3'

# ── Save ──
wb.save(OUTPUT)
print(f"\nSaved to: {OUTPUT}")

# ── Print summary ──
print("\n" + "="*70)
print("🔴 核心泛非账号 (真正深耕非洲赛道的创作者)")
print("="*70)
for i, a in enumerate(core_pan):
    print(f"{i+1:2d}. {a['nickname']:20s} | 粉:{fmt_num(a['follower_count']):>8s} | {a['n_countries']}国 | 均赞:{fmt_num(a['avg_likes']):>8s} | CLR:{a['avg_clr']:.4f} | {a['tier_reason']}")

print("\n" + "="*70)
print("🟢 核心单国账号 TOP 15 (昵称含国名的专注创作者)")
print("="*70)
for i, a in enumerate(core_country[:15]):
    print(f"{i+1:2d}. {a['nickname']:20s} | 粉:{fmt_num(a['follower_count']):>8s} | {a['primary_country']} | 均赞:{fmt_num(a['avg_likes']):>8s} | 该国{a['primary_country_videos']}条")

print(f"\n总计: 核心泛非{len(core_pan)} + 核心单国{len(core_country)} = {len(core_pan)+len(core_country)}个核心非洲赛道账号")
print(f"泛涉及账号: {len(general_africa)}个")
