#!/usr/bin/env python3
"""
非洲商贸城/中国城/产业园「项目 × 国家 × 账号」主清单构建器

输入源：
  1. 抖音搜索发现结果 ~/.workbuddy/douyin_analysis/_discovery/accounts_*.json
  2. 历史画像库（可选）~/Downloads/对标矩阵项目存档_2026-06-16/author_profiles/author_profiles_cache.json

处理：从每个账号的昵称/签名中抽取「项目名」，识别国家，按项目聚合，
     输出项目维度的主清单（Markdown + JSON）。

用法:
  python3 build_project_registry.py                # 全量重建
  python3 build_project_registry.py --merge-history # 同时并入历史画像库
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict

DISCOVERY_DIR = Path.home() / ".workbuddy/douyin_analysis" / "_discovery"
ARCHIVE_DIR = Path.home() / ".workbuddy/douyin_analysis" / "_archive"
HISTORY_CACHE = Path.home() / "Downloads" / "对标矩阵项目存档_2026-06-16" / "author_profiles" / "author_profiles_cache.json"

# 国家词表（含主要城市）
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

# 项目名抽取：前缀(≤6个汉字) + 项目后缀
PROJ_SUFFIX = ('商贸城', '中国城', '世纪城', '商贸中心', '商贸广场', '小商品城', '百货城',
               '产业园', '工业园', '工业区', '开发区', '经济特区', '经济区',
               '海外仓', '展销中心', '选品中心', '商城', '市场')
PROJ_RE = re.compile(r'([一-龥A-Za-z0-9]{0,8}?(?:' + '|'.join(PROJ_SUFFIX) + r'))')

PROJECT_TYPES = {
    '商贸城': ['商贸城', '商贸中心', '商贸广场', '世纪城'],
    '中国城': ['中国城', '中国商城', '中国商品城', '唐人街', '华人街'],
    '产业园': ['产业园', '工业园', '工业区', '开发区', '经济区', '经济特区', '园区'],
    '批发市场': ['批发市场', '小商品城', '百货城', '批城'],
    '商城/市场': ['商城', '市场', '商厦', '购物中心'],
    '海外仓/展厅': ['海外仓', '展厅', '选品中心', '展销中心', '仓储'],
}


def detect_countries(text: str) -> list[str]:
    return [c for c, kws in COUNTRIES.items() if any(k in text for k in kws)]


def detect_types(text: str) -> list[str]:
    return [t for t, kws in PROJECT_TYPES.items() if any(k in text for k in kws)]


# 项目名开头噪音词（动词/介词/所属关系，正则会连前缀一起抓进来）
NAME_NOISE_PREFIX = ('就职于', '工作于', '就职', '工作', '专注', '专注于', '深耕', '扎根',
                     '旗下的', '旗下', '运营', '坐标', '来自', '位于', '入驻', '进驻',
                     '逛', '带你看', '走进', '直击', '实拍')


def clean_project_name(n: str) -> str:
    """清洗项目名开头的动词/介词噪音（如『就职于非洲安哥拉世纪城』→『非洲安哥拉世纪城』）"""
    changed = True
    while changed:
        changed = False
        for w in NAME_NOISE_PREFIX:
            if n.startswith(w) and len(n) - len(w) >= 4:
                n = n[len(w):]
                changed = True
    return n


def extract_project_names(text: str) -> list[str]:
    """抽取项目名（如 安哥拉世纪城 / 坦桑尼亚北京工业园）

    2026-09 踩坑：正则会抓到「海外仓」「工业园」「市场」这类无前缀的通用词，
    它们不是具体项目 → 必须排除纯后缀，只保留带前缀的具体项目名。
    """
    names = []
    for m in PROJ_RE.finditer(text):
        n = m.group(1).strip()
        if n in PROJ_SUFFIX:      # 纯通用词，非项目名
            continue
        if len(n) < 3:
            continue
        names.append(clean_project_name(n))
    return [n for n in dict.fromkeys(names) if len(n) >= 3]


def normalize_projects(names: list[str]) -> dict[str, str]:
    """项目名归一化：子串合并到最长形式（如『世纪城』→『安哥拉世纪城』）"""
    names = sorted(set(names), key=len, reverse=True)
    mapping = {}
    for n in names:
        hit = None
        for long in names:
            if long != n and n in long:
                hit = long
                break
        mapping[n] = hit or n
    return mapping


def load_discovery() -> list[dict]:
    """加载所有搜索发现结果（合并多天、多个文件，按 sec_uid 去重）

    2026-09 注意：同一天可能产出 accounts_<日期>.json（泛词）和
    accounts_<日期>_projects.json（滚雪球），合并时保留信息更完整的一条
    （粉丝数更大或签名更长），不能简单按日期覆盖，否则丢数据。
    """
    rows = {}
    for f in sorted(DISCOVERY_DIR.glob('accounts_*.json')):
        date = f.stem.replace('accounts_', '')
        try:
            for r in json.load(open(f, encoding='utf-8')):
                r['_date'] = date
                k = r.get('sec_uid')
                if not k:
                    continue
                old = rows.get(k)
                if old is None:
                    rows[k] = r
                    continue
                # 信息完整度：粉丝数 + 签名长度
                score = lambda x: (x.get('followers') or 0) + len(x.get('signature') or '') * 10
                if score(r) > score(old):
                    rows[k] = r
        except Exception as e:
            print(f"  ⚠️ 读取 {f.name} 失败: {e}")
    return list(rows.values())


def load_history() -> list[dict]:
    """从历史画像库加载（2026-06 采集的 5584 人）"""
    if not HISTORY_CACHE.exists():
        return []
    data = json.load(open(HISTORY_CACHE, encoding='utf-8'))
    rows = []
    for uid, p in data.items():
        nick = p.get('nickname', '') or ''
        sig = (p.get('signature', '') or '') + ' ' + (p.get('custom_verify', '') or '') + \
              ' ' + (p.get('enterprise_verify_reason', '') or '')
        full = nick + ' ' + sig
        ctry = detect_countries(full)
        if not ctry:
            continue
        projs = extract_project_names(full)
        if not projs:
            continue
        rows.append({
            'nickname': nick, 'sec_uid': uid, 'followers': p.get('follower_count', 0),
            'likes': p.get('total_favorited', 0), 'signature': sig.strip(),
            'countries': ctry, 'projects': detect_types(full),
            'project_names': projs, '_date': '2026-06-16', '_source': '画像库',
        })
    return rows


def main():
    merge_history = '--merge-history' in sys.argv

    print("加载搜索发现结果...")
    rows = load_discovery()
    print(f"  {len(rows)} 个账号")
    if merge_history:
        h = load_history()
        print(f"  历史画像库：{len(h)} 个候选")
        known = {r['sec_uid'] for r in rows}
        rows.extend([x for x in h if x['sec_uid'] not in known])

    # 只保留有非洲国家信号 + 项目信号的
    qualified = []
    for r in rows:
        full = f"{r.get('nickname','')} {r.get('signature','')}"
        ctry = r.get('countries') or detect_countries(full)
        pnames = r.get('project_names') or extract_project_names(full)
        if ctry and pnames:
            r['countries'] = ctry
            r['project_names'] = pnames
            r['projects'] = r.get('projects') or detect_types(full)
            qualified.append(r)
    print(f"  命中「非洲国家 + 项目名」：{len(qualified)} 个账号")

    # 项目名归一化（先收集全部原始名）
    all_names = [pn for r in qualified for pn in r['project_names']]
    norm = normalize_projects(all_names)
    for r in qualified:
        r['project_names'] = list(dict.fromkeys(norm.get(pn, pn) for pn in r['project_names']))

    # 按项目聚合（国家优先从项目名提取，否则取账号首个国家）
    proj_map = defaultdict(lambda: {'accounts': [], 'countries': set(), 'types': set()})
    for r in qualified:
        for pn in r['project_names'][:2]:  # 一个账号最多归入2个项目
            proj_map[pn]['accounts'].append(r)
            pc = detect_countries(pn) or r['countries'][:1]
            proj_map[pn]['countries'].update(pc)
            proj_map[pn]['types'].update(r.get('projects', []))

    # 输出
    projs = []
    for name, d in proj_map.items():
        accs = sorted(d['accounts'], key=lambda x: -(x.get('followers') or 0))
        projs.append({
            'project': name,
            'countries': sorted(d['countries']),
            'types': sorted(d['types']),
            'account_count': len(accs),
            'top_followers': accs[0].get('followers', 0),
            'accounts': [{
                'nickname': a.get('nickname'), 'sec_uid': a.get('sec_uid'),
                'followers': a.get('followers', 0), 'signature': (a.get('signature') or '')[:70],
                'source': a.get('_source') or a.get('source_keyword') or a.get('_date', ''),
            } for a in accs[:8]],
        })
    projs.sort(key=lambda x: (-x['account_count'], -x['top_followers']))

    # JSON
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    jf = DISCOVERY_DIR / 'projects_master.json'
    jf.write_text(json.dumps({'updated': __import__('time').strftime('%Y-%m-%d %H:%M'),
                              'projects': projs}, ensure_ascii=False, indent=1), encoding='utf-8')

    # Markdown
    fmt = lambda n: f"{n/10000:.1f}万" if n >= 10000 else str(n or '-')
    md = ["# 非洲商贸城/中国城/产业园 项目 × 国家 × 账号 主清单\n",
          f"> 更新时间：{__import__('time').strftime('%Y-%m-%d %H:%M')} · "
          f"数据源：抖音搜索发现 + 历史画像库\n",
          f"共识别 **{len(projs)}** 个项目，覆盖 **{len(set(c for p in projs for c in p['countries']))}** 个国家，"
          f"关联 **{len(qualified)}** 个抖音账号。\n",
          "## 一、项目总表\n",
          "| # | 项目名 | 国家 | 类型 | 关联账号 | 头部账号 | 粉丝 |",
          "|---|--------|------|------|---------|---------|------|"]
    for i, p in enumerate(projs, 1):
        md.append(f"| {i} | **{p['project']}** | {'/'.join(p['countries'])} | "
                  f"{'/'.join(p['types'])} | {p['account_count']} | "
                  f"{p['accounts'][0]['nickname']} | {fmt(p['top_followers'])} |")

    md.append("\n## 二、项目明细（含关联账号）\n")
    for i, p in enumerate(projs, 1):
        md.append(f"### {i}. {p['project']}　`{'/'.join(p['countries'])}`　`{'/'.join(p['types'])}`\n")
        md.append("| 账号 | 粉丝 | 签名 | 来源 |")
        md.append("|---|---|---|---|")
        for a in p['accounts']:
            md.append(f"| {a['nickname']} | {fmt(a['followers'])} | {a['signature'][:50]} | {a['source']} |")
        md.append("")

    mf = DISCOVERY_DIR / 'projects_master.md'
    mf.write_text('\n'.join(md), encoding='utf-8')

    # 同步一份到归档目录（供 IMA 上传）
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_DIR / '【项目库】非洲商贸城_项目国家账号主清单.md').write_text('\n'.join(md), encoding='utf-8')

    print(f"\n✅ 输出：")
    print(f"  {jf}")
    print(f"  {mf}")
    print(f"\n=== 项目 Top 15 ===")
    for p in projs[:15]:
        print(f"{p['account_count']:>3}号 | {'/'.join(p['countries']):10s} | {'/'.join(p['types']):10s} | {p['project'][:26]}")


if __name__ == '__main__':
    main()
