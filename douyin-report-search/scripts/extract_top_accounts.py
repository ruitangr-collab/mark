"""
从20国采集数据中提取泛非/各国头部账号清单
分类逻辑：
- 泛非：在3个及以上国家出现，或昵称/描述含泛非关键词
- 单国：仅在1-2个国家出现
- 自动过滤新闻/官方账号（复用v4过滤逻辑）
"""
import json, os, re, sys
from collections import defaultdict, Counter
from statistics import median
sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = 'C:/Users/53185/.workbuddy/skills/douyin-report-search/country_data'
OUTPUT = 'C:/Users/53185/.workbuddy/skills/douyin-report-search/非洲抖音头部账号清单.xlsx'

# ── News filter (same as v4/v5) ──
NEWS_KEYWORDS_VERIFY = [
    '新闻', '日报', 'TV', '卫视', '资讯', '网', '广播', '频道', 'CCTV', 'cctv',
    '新华社', '人民日报', '环球', '参考消息', '中国日报', '凤凰', '观察者',
    '头条', '快报', '官方发布', '电视台', '传媒', '报道', '时报', '央视频',
    '央视', '观察', '财经网', '新媒体',
]

def is_news(author):
    nickname = (author.get('nickname') or '').lower()
    enterprise_verify = (author.get('enterprise_verify_reason') or '')
    custom_verify = (author.get('custom_verify') or '')
    if enterprise_verify:
        for kw in NEWS_KEYWORDS_VERIFY:
            if kw.lower() in enterprise_verify.lower():
                return True
    if custom_verify:
        for kw in NEWS_KEYWORDS_VERIFY:
            if kw.lower() in custom_verify.lower():
                return True
    if enterprise_verify:
        for kw in ['新闻', '日报', 'TV', '卫视', '资讯', '广播', '频道', 'CCTV', 'cctv',
                    '新华社', '人民日报', '环球', '参考消息', '中国日报', '凤凰', '观察者',
                    '头条', '快报', '报道', '时报', '央视频', '央视']:
            if kw.lower() in nickname:
                return True
    return False

# ── Pan-Africa keywords ──
PAN_AFRICA_KW = ['非洲', 'africa', '泛非', '全非', '东非', '西非', '北非', '南非',
                  '中非', '撒哈拉', '黑人', '非洲人', '走进非洲', '非洲故事',
                  '非洲生活', '非洲见闻', '非洲旅游', '非洲创业', '非洲生意',
                  '非洲商机', '非洲贸易', '非洲投资', '出海非洲']

def is_pan_africa_desc(desc):
    d = desc.lower()
    return any(kw.lower() in d for kw in PAN_AFRICA_KW)

def is_pan_africa_name(nickname):
    n = nickname.lower()
    return any(kw.lower() in n for kw in PAN_AFRICA_KW)

# ── Load all data ──
print("Loading data...")
all_videos = []  # (video_dict, author_dict, country, keyword)

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

# ── Group by author uid ──
authors = defaultdict(lambda: {
    'nickname': '',
    'uid': '',
    'follower_count': 0,
    'enterprise_verify_reason': '',
    'custom_verify': '',
    'videos': [],
    'countries': set(),
    'keywords': set(),
    'total_likes': 0,
    'total_comments': 0,
    'total_shares': 0,
    'total_collects': 0,
    'descs': [],
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
    a['keywords'].add(keyword)
    a['videos'].append(v)

    s = v.get('statistics', {})
    a['total_likes'] += s.get('digg_count', 0) or 0
    a['total_comments'] += s.get('comment_count', 0) or 0
    a['total_shares'] += s.get('share_count', 0) or 0
    a['total_collects'] += s.get('collect_count', 0) or 0
    a['descs'].append((raw.get('desc') or '')[:120])

print(f"News filtered: {news_count}")
print(f"Unique creator authors: {len(authors)}")

# ── Classify: Pan-Africa vs Single Country ──
pan_authors = []
country_authors = []

for uid, a in authors.items():
    n_countries = len(a['countries'])
    nickname = a['nickname']
    all_descs = ' '.join(a['descs'])

    # Pan-Africa logic: 3+ countries OR name/desc contains pan-Africa keywords
    has_pan_name = is_pan_africa_name(nickname)
    has_pan_desc = is_pan_africa_desc(all_descs)

    is_pan = (n_countries >= 3) or has_pan_name or has_pan_desc

    # Compute metrics
    n_videos = len(a['videos'])
    followers = a['follower_count']
    total_eng = a['total_likes'] + a['total_comments'] + a['total_shares'] + a['total_collects']
    avg_likes = a['total_likes'] / n_videos if n_videos > 0 else 0
    avg_comments = a['total_comments'] / n_videos if n_videos > 0 else 0
    avg_shares = a['total_shares'] / n_videos if n_videos > 0 else 0
    avg_collects = a['total_collects'] / n_videos if n_videos > 0 else 0
    avg_eng = total_eng / n_videos if n_videos > 0 else 0
    epf = avg_eng / followers if followers > 0 else 0
    clr = a['total_comments'] / a['total_likes'] if a['total_likes'] > 0 else 0

    # Country list
    countries_str = '、'.join(sorted(a['countries']))

    # Top country (most videos)
    country_counter = Counter()
    for v in a['videos']:
        raw = v.get('_raw') or {}
        # We don't store country per video now, so use country set
    primary_country = sorted(a['countries'])[0] if a['countries'] else '未知'

    # Verification info
    verify = a['enterprise_verify_reason'] or a['custom_verify'] or '无认证'

    # Pan reason
    if is_pan:
        reasons = []
        if n_countries >= 3:
            reasons.append(f'覆盖{n_countries}国')
        if has_pan_name:
            reasons.append('昵称含泛非词')
        if has_pan_desc:
            reasons.append('描述含泛非词')
        pan_reason = '；'.join(reasons)
    else:
        pan_reason = ''

    # Sample desc
    sample_desc = a['descs'][0][:100] if a['descs'] else ''

    record = {
        'nickname': nickname,
        'uid': uid,
        'follower_count': followers,
        'n_videos_in_sample': n_videos,
        'n_countries': n_countries,
        'countries': countries_str,
        'primary_country': primary_country,
        'category': '泛非' if is_pan else '单国',
        'pan_reason': pan_reason,
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

    if is_pan:
        pan_authors.append(record)
    else:
        country_authors.append(record)

# Sort by follower count desc
pan_authors.sort(key=lambda x: (-x['follower_count'], -x['total_eng']))
country_authors.sort(key=lambda x: (-x['follower_count'], -x['total_eng']))

# Group country authors by primary country
from collections import OrderedDict
country_groups = defaultdict(list)
for a in country_authors:
    for c in a['countries'].split('、'):
        country_groups[c].append(a)

# Unique per country (an author may belong to multiple, we'll assign to most represented)
# For now keep them grouped

print(f"\nPan-Africa accounts: {len(pan_authors)}")
print(f"Single-country accounts: {len(country_authors)}")

# ── Output to Excel ──
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    import subprocess
    subprocess.run([
        'C:/Users/53185/.workbuddy/binaries/python/versions/3.13.12/python.exe', '-m', 'pip', 'install', 'openpyxl',
        '--target', 'C:/Users/53185/.workbuddy/binaries/python/lib'
    ], capture_output=True)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

wb = Workbook()

# ── Styles ──
header_font = Font(name='微软雅黑', bold=True, size=11, color='FFFFFF')
header_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
pan_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
cell_align = Alignment(vertical='center', wrap_text=True)
thin_border = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9'),
)
# 涨=红标记用于粉丝数
red_font = Font(name='微软雅黑', size=10, color='FF0000', bold=True)

def write_header(ws, headers, widths):
    for col_idx, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = w

def write_row(ws, row_idx, data):
    for col_idx, val in enumerate(data, 1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.alignment = cell_align
        cell.border = thin_border
        cell.font = Font(name='微软雅黑', size=10)

def fmt_num(n):
    if n >= 100000000:
        return f'{n/100000000:.1f}亿'
    elif n >= 10000:
        return f'{n/10000:.1f}万'
    else:
        return str(int(n))

# ──────────────────────────────────
# Sheet 1: 泛非头部账号
# ──────────────────────────────────
ws1 = wb.active
ws1.title = '泛非头部账号'

pan_headers = ['排名', '账号昵称', '抖音UID', '粉丝数', '样本视频数', '覆盖国家数',
               '覆盖国家', '泛非判定', '认证类型', '总赞数', '总评数', '总分享',
               '总互动', '均赞', '均评', '均互动', '平均评赞比', '粉均互动率',
               '简介摘要']
pan_widths = [6, 18, 20, 12, 10, 10, 28, 18, 14, 12, 12, 10, 12, 10, 10, 10, 12, 12, 40]
write_header(ws1, pan_headers, pan_widths)

for i, a in enumerate(pan_authors[:100]):  # Top 100 pan-Africa
    row = i + 2
    write_row(ws1, row, [
        i + 1,
        a['nickname'],
        a['uid'],
        fmt_num(a['follower_count']),
        a['n_videos_in_sample'],
        a['n_countries'],
        a['countries'],
        a['pan_reason'],
        a['verify'],
        fmt_num(a['total_likes']),
        fmt_num(a['total_comments']),
        fmt_num(a['total_shares']),
        fmt_num(a['total_eng']),
        fmt_num(a['avg_likes']),
        fmt_num(a['avg_comments']),
        fmt_num(a['avg_eng']),
        a['avg_clr'],
        a['epf'],
        a['sample_desc'],
    ])

ws1.freeze_panes = 'A2'
ws1.auto_filter.ref = f'A1:S{len(pan_authors[:100])+1}'

# ──────────────────────────────────
# Sheet 2-21: 各国头部账号 (每个国家一个Sheet)
# ──────────────────────────────────
all_countries = sorted(country_groups.keys())
print(f"\nCountries with data: {len(all_countries)}")
for c in all_countries:
    print(f"  {c}: {len(country_groups[c])} authors")

country_headers = ['排名', '账号昵称', '抖音UID', '粉丝数', '样本视频数',
                   '认证类型', '总赞数', '总评数', '总分享', '总互动',
                   '均赞', '均评', '均互动', '平均评赞比', '粉均互动率',
                   '简介摘要']
country_widths = [6, 18, 20, 12, 10, 16, 12, 12, 10, 12, 10, 10, 10, 12, 12, 40]

for country in all_countries:
    # Deduplicate: same author may appear in multiple countries
    seen = set()
    unique = []
    for a in sorted(country_groups[country], key=lambda x: (-x['follower_count'], -x['total_eng'])):
        if a['uid'] not in seen:
            seen.add(a['uid'])
            unique.append(a)

    sheet_name = country[:31]  # Excel 31 char limit
    ws = wb.create_sheet(title=sheet_name)
    write_header(ws, country_headers, country_widths)

    for i, a in enumerate(unique[:50]):  # Top 50 per country
        row = i + 2
        write_row(ws, row, [
            i + 1,
            a['nickname'],
            a['uid'],
            fmt_num(a['follower_count']),
            a['n_videos_in_sample'],
            a['verify'],
            fmt_num(a['total_likes']),
            fmt_num(a['total_comments']),
            fmt_num(a['total_shares']),
            fmt_num(a['total_eng']),
            fmt_num(a['avg_likes']),
            fmt_num(a['avg_comments']),
            fmt_num(a['avg_eng']),
            a['avg_clr'],
            a['epf'],
            a['sample_desc'],
        ])
    ws.freeze_panes = 'A2'
    if unique:
        ws.auto_filter.ref = f'A1:P{min(len(unique), 50)+1}'

# ──────────────────────────────────
# Sheet: 汇总统计
# ──────────────────────────────────
ws_summary = wb.create_sheet(title='汇总统计')
ws_summary.merge_cells('A1:F1')
ws_summary.cell(row=1, column=1, value='泛非/各国头部账号统计汇总').font = Font(name='微软雅黑', bold=True, size=14, color='2F5496')

summary_headers = ['分类', '国家/地区', '账号数', 'Top1账号', 'Top1粉丝数', 'Top1均互动']
summary_widths = [10, 16, 10, 20, 14, 14]
for col_idx, (h, w) in enumerate(zip(summary_headers, summary_widths), 1):
    cell = ws_summary.cell(row=3, column=col_idx, value=h)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = header_align
    cell.border = thin_border
    ws_summary.column_dimensions[get_column_letter(col_idx)].width = w

row = 4
# Pan-Africa summary
write_row(ws_summary, row, [
    '泛非', '多国', len(pan_authors),
    pan_authors[0]['nickname'] if pan_authors else '-',
    fmt_num(pan_authors[0]['follower_count']) if pan_authors else '-',
    fmt_num(pan_authors[0]['avg_eng']) if pan_authors else '-',
])
row += 1

# Per country summary
for country in all_countries:
    unique = country_groups[country]
    top = sorted(unique, key=lambda x: (-x['follower_count'], -x['total_eng']))
    write_row(ws_summary, row, [
        '单国', country, len(set(a['uid'] for a in unique)),
        top[0]['nickname'] if top else '-',
        fmt_num(top[0]['follower_count']) if top else '-',
        fmt_num(top[0]['avg_eng']) if top else '-',
    ])
    row += 1

# Grand total
ws_summary.merge_cells(f'A{row}:F{row}')
ws_summary.cell(row=row, column=1, value=f'总计：泛非 {len(pan_authors)} 个 + 单国 {len(set(a["uid"] for aa in country_groups.values() for a in aa))} 个唯一作者 = {len(authors)} 个创作者账号').font = Font(name='微软雅黑', bold=True, size=11)

ws_summary.freeze_panes = 'A4'

# ──────────────────────────────────
# Sheet: 泛非账号Top30精简卡片
# ──────────────────────────────────
ws_card = wb.create_sheet(title='泛非Top30卡片')
card_headers = ['排名', '账号昵称', '粉丝数', '覆盖国家', '均赞', '均评', '评赞比', '认证', '简介']
card_widths = [6, 18, 12, 24, 10, 10, 10, 14, 50]
write_header(ws_card, card_headers, card_widths)

for i, a in enumerate(pan_authors[:30]):
    row = i + 2
    write_row(ws_card, row, [
        i + 1,
        a['nickname'],
        fmt_num(a['follower_count']),
        a['countries'],
        fmt_num(a['avg_likes']),
        fmt_num(a['avg_comments']),
        a['avg_clr'],
        a['verify'],
        a['sample_desc'],
    ])
    # Highlight pan-africa rows
    for col in range(1, 10):
        ws_card.cell(row=row, column=col).fill = pan_fill if i % 2 == 0 else PatternFill()

ws_card.freeze_panes = 'A2'

# ── Save ──
wb.save(OUTPUT)
print(f"\n✅ Saved to: {OUTPUT}")

# ── Print summary ──
print("\n" + "="*60)
print("泛非头部账号 TOP 15")
print("="*60)
for i, a in enumerate(pan_authors[:15]):
    print(f"{i+1:2d}. {a['nickname']:20s} | 粉:{fmt_num(a['follower_count']):>8s} | {a['n_countries']}国 | 均赞:{fmt_num(a['avg_likes']):>8s} | CLR:{a['avg_clr']:.4f}")
    print(f"    覆盖: {a['countries']}")
    print(f"    判定: {a['pan_reason']}")
    print()

print("\n" + "="*60)
print("各国头部账号 Top1")
print("="*60)
for country in all_countries:
    unique = sorted(country_groups[country], key=lambda x: (-x['follower_count'], -x['total_eng']))
    if unique:
        a = unique[0]
        print(f"  {country:8s} → {a['nickname']:20s} | 粉:{fmt_num(a['follower_count']):>8s} | 均赞:{fmt_num(a['avg_likes']):>8s}")
