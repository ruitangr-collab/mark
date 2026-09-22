#!/usr/bin/env python3
"""每日摘要生成器（第 7 步）：把当日 10 个数据集（9 个 S 级账号 + 关键词流）
压缩成一份可读摘要，供人读汇报与 S 级名单复核使用。

用法:
    python3 scripts/daily_digest.py [YYYY-MM-DD]

输出（stdout，Markdown）:
  1. 评论区高热度话题 Top10（词频 + 占比）
  2. 评论区内容类型分布（五类需求）
  3. 评论区问得最多的问题（原样引用）
  4. S 级账号需求密度环比（读 _runtime/demand_density_<日期>.txt 与前一日期文件）
  5. 同行/博主账号线索（对标线索，标注跨账号扩散度）

设计说明:
  - 口径锁定「当日 10 数据集」，与 demand_density.py 的全量口径互补：
    全量口径用于账号分级，本脚本口径用于当日舆情与选题。
  - 同行名在评论里以「粉丝数前缀 + 昵称」形式出现（如 "5904锋哥在非洲"），
    故先剥掉前导数字再聚合，避免同一账号因粉丝数变化被拆成多个。
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import TOPIC_STOPWORDS as STOPWORDS  # 单一来源，勿在本文件另建一份
from common import is_ui_residue, is_topic_noise, cross_dataset_duplicates

BASE = Path.home() / '.workbuddy' / 'douyin_analysis'
RUNTIME = BASE / '_runtime'
WATCHLIST = BASE / '_archive' / 's_watchlist.json'
KEYWORD = '非洲出海'

# 五类需求正则（与 demand_density.py 保持一致，勿单独改动）
CATS = {
    '投资创业': r'(创业|投资|开厂|办厂|建厂|做生意|开店|考察|项目|布局|入场|市场怎么样|搞实业|实业)',
    '货源采购': r'(采购|批发|进货|货源|拿货|供应|报价|多少钱|价格|成本|渠道拿|找.{0,3}(货源|供应商)|出口.{0,4}(怎么|如何))',
    '意向咨询': r'(怎么|如何|能不能|可不可以|需要什么|什么条件|手续|流程|求带|带带我|请教|咨询|求助|行不行|靠谱吗|有没有.{0,3}(风险|搞头|前途))',
    '合作商务': r'(合作|加盟|代理|合伙|对接|资源|人脉|交流|认识一下|找.{0,3}(合作|老板)|商务|一起做|入伙)',
    '渠道获客': r'(引流|获客|涨粉|直播|带货|渠道|客户|销售|推广|账号|内容|短视频|粉丝)',
}

# 页面噪音（页脚/播放器/时间戳残留），与 build_archive_docs.py 保持同步
NOISE = ['京公网安备', '备案号', '立即领取', '快乐大本营', '大学生免费用',
         '我的喜欢', '充钻石', '进入全屏', '播放中', '退出全屏']

STOPWORDS = set(STOPWORDS)  # noqa: F811  兼容旧引用

# 同行/服务类账号线索特征词
PEER_PAT = re.compile(
    r'(在非洲|闯非洲|出海|海外仓|国际物流|跨境|供应链|考察|招商|签证|机票|'
    r'货代|清关|专线|产业园|商贸城|工业园|咨询|服务中心|联盟|商会)'
)
# 评论里账号名的前导粉丝数前缀："5904锋哥在非洲" / "4.6万大褚工厂出海"
PREFIX_PAT = re.compile(r'^\d+(\.\d+)?万?')


def clean(c):
    c = (c or '').strip()
    if len(c) < 2:
        return None
    if any(n in c for n in NOISE):
        return None
    if is_ui_residue(c):
        return None
    c = re.sub(r'^\d+\s?(小时|分钟|天)前.*$', '', c)
    return c.strip() or None


def load_day_dirs(day):
    """当日 10 个数据集目录：9 个 S 级账号 + 关键词流。"""
    data = json.loads(WATCHLIST.read_text(encoding='utf-8'))
    names = [a['nickname'] for a in data.get('accounts', [])]
    dirs = [BASE / f'account_{n}' for n in names] + [BASE / f'keyword_{KEYWORD}']
    return [d for d in dirs if (d / 'all_comments.json').exists()]


def load_comments(dirs):
    per = {}
    for d in dirs:
        raw = json.loads((d / 'all_comments.json').read_text(encoding='utf-8'))
        cs = [c for c in (clean(x) for x in raw) if c]
        per[d.name] = list(dict.fromkeys(cs))
    return per


def top_topics(per, n=10):
    words = Counter()
    total = sum(len(v) for v in per.values())
    injected = cross_dataset_duplicates(per)
    for cs in per.values():
        for c in cs:
            # 与 build_archive_docs.top_words 同口径：统计全部出现次数
            # 2026-09-18：剔账号名/章节字幕/平台注入残留，否则 Top10 被 "水深/宽度/库里南" 占满
            if is_topic_noise(c) or c in injected or c.count('#') >= 1:
                continue
            for w in re.findall(r'[\u4e00-\u9fff]{2,6}', c):
                if w not in STOPWORDS:
                    words[w] += 1
    return words.most_common(n), total


def cat_dist(per):
    cnt = {k: 0 for k in CATS}
    hit = set()
    total = 0
    for name, cs in per.items():
        for i, c in enumerate(cs):
            total += 1
            for k, pat in CATS.items():
                if re.search(pat, c):
                    cnt[k] += 1
                    hit.add((name, i))
    return cnt, len(hit), total


QUESTIONS = [
    ('怎么', r'怎么'),
    ('能不能', r'能不能|可不可以|行不行'),
    ('多少钱', r'多少钱|什么价|价格|报价'),
    ('如何', r'如何'),
    ('可以吗', r'可以吗|可以么'),
    ('安全吗', r'安全吗|安全么|风险'),
    ('需要什么', r'需要什么|什么条件|需要哪些'),
]


def questions(per, per_q=3):
    """按疑问类型分组，取真实提问原文。

    只保留「以问号结尾、且不含 # 标签」的短句——否则会把视频简介/标题
    （如「…来非洲开家具厂能不能赚钱？」）误当用户提问，这是本数据集已知的污染源。
    """
    out = {}
    for label, pat in QUESTIONS:
        rx = re.compile(pat)
        samples = []
        for name, cs in per.items():
            for c in cs:
                if not rx.search(c):
                    continue
                if not c.rstrip().endswith(('?', '？')):
                    continue
                if '#' in c or not (6 <= len(c) <= 60):
                    continue
                samples.append((name, c))
        seen, uniq = set(), []
        for nm, c in samples:
            if c not in seen:
                seen.add(c)
                uniq.append((nm, c))
        out[label] = (len(samples), uniq[:per_q])
    return out


# 句子特征词：命中即判定为「叙述句」而非账号名，避免把评论正文当线索
SENTENCE_MARKERS = [
    '我们', '你们', '他们', '客户', '很多', '都在', '可以', '怎么', '有没有',
    '这个', '那个', '一个', '什么', '为什么', '应该', '现在', '已经', '还有',
    '但是', '因为', '所以', '就是', '觉得', '知道', '看到', '大家', '朋友',
    '我的', '你的', '他的', '想了解', '请问', '帮', '谢谢', '确实', '真的',
]


def norm_name(s):
    """归一化账号名：去前导粉丝数、去括号补充说明与 emoji，便于聚合/比对。

    评论里账号名形如「5904锋哥在非洲」「4.6万大褚工厂出海」「佳哥在非洲(加纳🇬🇭）」，
    同一账号会因粉丝数变化或括号内容被拆成多条，故统一归并。
    """
    s = PREFIX_PAT.sub('', s).strip()
    s = re.sub(r'[（(][^）)]*[）)]', '', s)
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]+', '', s)
    return s.strip()


def peer_leads(per, exclude, min_len=4, max_len=30):
    """同行/服务类账号线索：归一化后聚合，记录跨账号扩散度。"""
    ex_norm = {norm_name(e) for e in exclude}
    agg = defaultdict(lambda: {'n': 0, 'accts': set(), 'raw': set()})
    for name, cs in per.items():
        for c in cs:
            if not (min_len <= len(c) <= max_len):
                continue
            if not PEER_PAT.search(c):
                continue
            # 叙述句排除：含句读、疑问结尾、或以「我/你/他」开头
            if re.search(r'[。！？，,；;、]', c) or c.endswith('吗'):
                continue
            if c[0] in '我你他咱这那':
                continue
            if any(m in c for m in SENTENCE_MARKERS):
                continue
            key = norm_name(c)
            if len(key) < 3 or key in ex_norm:
                continue
            agg[key]['n'] += 1
            agg[key]['accts'].add(name)
            agg[key]['raw'].add(PREFIX_PAT.sub('', c).strip())
    rows = [
        {'name': k, 'n': v['n'], 'spread': len(v['accts']),
         'accts': sorted(v['accts']), 'raw': sorted(v['raw'])[0]}
        for k, v in agg.items()
    ]
    rows.sort(key=lambda r: (-r['spread'], -r['n']))
    return rows


def density_series(day):
    """读取 demand_density_<date>.txt，返回 {昵称: (评论, 需求, 密度)}。"""
    p = RUNTIME / f'demand_density_{day}.txt'
    if not p.exists():
        return None
    out = {}
    for line in p.read_text(encoding='utf-8').splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            out[parts[0]] = (int(parts[2]), int(parts[3]), float(parts[4]))
        except ValueError:
            continue
    return out


def prev_density_file(day):
    d = date.fromisoformat(day)
    for i in range(1, 6):
        cand = (d - timedelta(days=i)).isoformat()
        if (RUNTIME / f'demand_density_{cand}.txt').exists():
            return cand
    return None


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    dirs = load_day_dirs(day)
    per = load_comments(dirs)
    total = sum(len(v) for v in per.values())

    print(f'# 抖音出海非洲监控 · 当日摘要（{day}）\n')
    print(f'- 数据集：{len(dirs)} 个（{len(dirs) - 1} 个 S 级账号 + 关键词「{KEYWORD}」）')
    print(f'- 去重评论：{total} 条')
    print('- 各数据集去重量：' + '、'.join(f'{k.replace("account_", "")}={len(v)}'
                                            for k, v in per.items()))
    print()

    # 1. 话题 Top10
    topics, _ = top_topics(per, 10)
    print('## 一、评论区高热度话题 Top10\n')
    print('| # | 话题 | 词频 | 占比 |')
    print('|---|---|---|---|')
    for i, (w, c) in enumerate(topics, 1):
        print(f'| {i} | {w} | {c} | {c / total * 100:.1f}% |')
    print()

    # 2. 内容类型分布
    cnt, hit, tot = cat_dist(per)
    print('## 二、评论区内容类型分布\n')
    print('| 类型 | 条数 | 占需求类 | 占全部评论 |')
    print('|---|---|---|---|')
    for k in ['货源采购', '投资创业', '意向咨询', '合作商务', '渠道获客']:
        print(f'| {k} | {cnt[k]} | {cnt[k] / hit * 100:.0f}% | {cnt[k] / tot * 100:.1f}% |')
    print(f'| **需求类合计** | **{hit}** | 100% | **{hit / tot * 100:.1f}%** |')
    print(f'\n> 注：单条评论可命中多类，故各类之和 ≥ 需求类合计。其他（纯互动/闲聊）{tot - hit} 条。\n')

    # 3. 问题
    qs = questions(per)
    print('## 三、评论区问得最多的问题\n')
    for label, (n, samples) in qs.items():
        print(f'**「{label}」类 {n} 条**')
        for nm, c in samples:
            print(f'- （{nm.replace("account_", "")}）{c}')
        print()

    # 4. 密度环比
    cur = density_series(day)
    prev_day = prev_density_file(day)
    prev = density_series(prev_day) if prev_day else None
    print(f'## 四、S 级账号需求密度环比（对比 {prev_day or "无基准"}）\n')
    if not cur:
        print('> 未找到当日 demand_density 输出。\n')
    else:
        wl = json.loads(WATCHLIST.read_text(encoding='utf-8'))
        s_names = [a['nickname'] for a in wl.get('accounts', [])]
        print('| 账号 | 密度% | 环比 | 需求数 | 环比 | 评论数 | 双线达标 |')
        print('|---|---|---|---|---|---|---|')
        for n in s_names:
            key = next((k for k in cur if k == n or k.startswith(n[:8])), None)
            if not key:
                print(f'| {n} | — | — | — | — | — | 无数据 |')
                continue
            c_total, c_req, c_d = cur[key]
            if prev and key in prev:
                _, p_req, p_d = prev[key]
                dd, dr = c_d - p_d, c_req - p_req
                arrow = f'{"↑" if dd > 0 else "↓" if dd < 0 else "="}{abs(dd):.1f}'
                ra = f'{"↑" if dr > 0 else "↓" if dr < 0 else "="}{abs(dr)}'
            else:
                arrow = ra = '—'
            ok = '✅' if (c_d >= 13 and c_req >= 50) else ''
            print(f'| {n} | {c_d:.1f} | {arrow} | {c_req} | {ra} | {c_total} | {ok} |')
        print()

    # 5. 同行线索
    exclude = {d.name.replace('account_', '') for d in BASE.glob('account_*')}
    leads = peer_leads(per, exclude)
    print('## 五、同行/博主账号线索（对标线索）\n')
    print('| 账号名 | 命中 | 跨账号数 | 出现位置 |')
    print('|---|---|---|---|')
    for r in leads[:25]:
        accts = '、'.join(a.replace('account_', '').replace('keyword_', 'kw-') for a in r['accts'])
        print(f"| {r['name']} | {r['n']} | {r['spread']} | {accts} |")
    print()
    print(f'> 共 {len(leads)} 个候选线索（已剔除已入库账号）。'
          '跨账号数≥2 且属考察/招商/物流/海外仓/顾问类的，建议核验后并入 s_watchlist.json。')


if __name__ == '__main__':
    main()
