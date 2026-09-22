#!/usr/bin/env python3
"""
抖音监控归档文档生成器
读取 ~/.workbuddy/douyin_analysis/ 下的分析结果，生成 4 类归档文档到 _archive/：
  1. 【监控对象】账号清单.md         — 所有分析/监控过的账号总表
  2. 【时序】YYYY-MM-DD_<关键词>.md  — 每日关键词监控结果
  3. 【档案】<账号名>.md             — 单账号分析文档
  4. 【汇报】跨账号趋势汇总.md        — 提炼的高热度话题/高频问题/类型占比

归档文档由 IMA 归档流程上传到「媒体账号监控」知识库（单库+命名分区）。
用法: python3 build_archive_docs.py
"""
import json, re, sys
from pathlib import Path
from collections import Counter

# 复用需求密度模块的分类规则（账号分级核心指标）
sys.path.insert(0, str(Path(__file__).parent))
try:
    from demand_density import CATS as DEMAND_CATS, clean as clean_comment
except ImportError:
    DEMAND_CATS, clean_comment = {}, lambda c: c

# 话题词频停用词统一从 common.py 取（2026-09-17 收敛，此前本文件内联一份已漂移）
try:
    from common import (TOPIC_STOPWORDS as _TOPIC_STOP, is_ui_residue,
                        is_topic_noise, cross_dataset_duplicates)
except ImportError:
    _TOPIC_STOP = set()

    def is_ui_residue(_t):
        return False

    def is_topic_noise(_t):
        return False

    def cross_dataset_duplicates(_per, _n=4):
        return set()

OUTPUT_BASE = Path.home() / ".workbuddy/douyin_analysis"
ARCHIVE_DIR = OUTPUT_BASE / "_archive"

# 需求信号关键词（评论中出现视为潜在客户需求）
DEMAND_KEYWORDS = ['怎么', '如何', '合作', '联系', '价格', '多少钱', '货源', '采购',
                   '工厂', '进货', '渠道', '招商', '加盟', '代理', '签证', '去非洲',
                   '投资', '创业', '带我去', '求带', '想了解', '私信', '微信']


def load_comments(dir_path: Path) -> list[str]:
    f = dir_path / "all_comments.json"
    if f.exists():
        return json.load(open(f, encoding='utf-8'))
    return []


def load_json(dir_path: Path, name: str) -> dict:
    f = dir_path / name
    if f.exists():
        return json.load(open(f, encoding='utf-8'))
    return {}


def format_cn(n) -> str:
    if not n:
        return '?'
    n = int(n)
    if n >= 100000000:
        return f"{n/100000000:.1f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


def extract_demand_signals(comments: list[str], top_n: int = 5) -> list[tuple[str, str]]:
    """提取含需求关键词的评论"""
    hits = []
    for c in comments:
        if any(kw in c for kw in DEMAND_KEYWORDS):
            hits.append(c)
    # 去重保序，截取
    uniq = list(dict.fromkeys(hits))
    return [(c[:120] + ('...' if len(c) > 120 else ''), c) for c in uniq[:top_n]]


def top_words(comments: list[str], n: int = 15, extra_skip: set | None = None) -> list[tuple[str, int]]:
    """简单词频统计（过滤单字、常见词、页面噪音）"""
    stop = _TOPIC_STOP
    extra_skip = extra_skip or set()
    words = Counter()
    for c in comments:
        # 先剔 UI 残留（播放器倒计时/占位昵称），否则会被切词成 "后播放下一个" 之类碎片
        if is_ui_residue(c):
            continue
        # 2026-09-18：账号名残留（"4853叶镇平出海贸易"）+ 章节字幕残留
        # （"沙坪河段…：水深6.3米，宽度80米"）都不是评论，会把话题榜整榜占满
        if is_topic_noise(c):
            continue
        # 平台注入内容（跨数据集逐字重复）同样不是评论
        if c in extra_skip:
            continue
        # 标签文案 = 视频标题/账号自述，不是用户评论（2026-09-18 由 >=2 收紧到 >=1）
        if c.count('#') >= 1:
            continue
        # 提取中文词（2-6字）
        for w in re.findall(r'[\u4e00-\u9fff]{2,6}', c):
            if w not in stop:
                words[w] += 1
    return words.most_common(n)


def build_account_register() -> str:
    """【监控对象】账号清单"""
    rows = []
    for d in sorted(OUTPUT_BASE.iterdir()):
        if not d.is_dir() or not d.name.startswith('account_'):
            continue
        info = load_json(d, 'user_info.json')
        meta = load_json(d, 'meta.json')
        comments = load_comments(d)
        name = info.get('nickname') or d.name.replace('account_', '')
        # 需求密度（分级核心指标）
        cleaned = [c for c in (clean_comment(x) for x in comments) if c]
        hit_idx = set()
        for i, c in enumerate(cleaned):
            for pat in DEMAND_CATS.values():
                if re.search(pat, c):
                    hit_idx.add(i)
                    break
        total_clean = len(cleaned)
        density = len(hit_idx) / total_clean * 100 if total_clean else 0.0
        rows.append({
            'name': name,
            'fans': format_cn(info.get('follower_count')),
            'likes': format_cn(info.get('total_favorited')),
            'works': info.get('aweme_count', '?'),
            'videos_analyzed': len(meta.get('video_ids', [])),
            'comments': len(comments),
            'date': meta.get('run_time', '?')[:10],
            'sec_uid': info.get('sec_uid', '?'),
            'density': density,
            'demand_cnt': len(hit_idx),
        })
    if not rows:
        return "# 【监控对象】账号清单\n\n暂无已分析的账号。\n"

    # 读 S 级名单（人工确认的出海服务核心账号，见 s_watchlist.json）
    s_set, s_meta = set(), {}
    wl = ARCHIVE_DIR / 's_watchlist.json'
    if wl.exists():
        try:
            wl_data = json.load(open(wl, encoding='utf-8'))
            for a in wl_data.get('accounts', []):
                s_set.add(a['nickname'])
                s_meta[a['nickname']] = a.get('service_type', '')
        except Exception:
            pass

    # 分级：S=出海服务核心名单；A=密度≥11%或需求≥60；B=其余
    for r in rows:
        if r['name'] in s_set:
            r['level'], r['svc'] = 'S', s_meta[r['name']]
        elif r['density'] >= 11 or r['demand_cnt'] >= 60:
            r['level'], r['svc'] = 'A', '实操/半服务（数据达标但非纯服务类）'
        else:
            r['level'], r['svc'] = 'B', '低需求或非目标人群'
    rows.sort(key=lambda x: ({'S': 0, 'A': 1, 'B': 2}[x['level']], -x['density']))

    lines = ["# 【监控对象】账号清单\n",
             "> 分级标准：S=出海服务核心（考察招商/仓储物流/顾问咨询/供应链，密度≥13%且需求≥50条）；"
             "A=数据达标但非纯服务类；B=低需求或非目标人群。S级名单见 `s_watchlist.json`。\n",
             "| 级别 | 账号 | 粉丝 | 需求密度 | 需求数 | 评论数 | 作品数 | 服务类型 | 分析日期 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| **{r['level']}** | {r['name']} | {r['fans']} | {r['density']:.1f}% | "
                     f"{r['demand_cnt']} | {r['comments']} | {r['works']} | {r['svc']} | {r['date']} |")
    counts = Counter(r['level'] for r in rows)
    lines.append(f"\n> 合计 {len(rows)} 个账号：S级 {counts['S']} · A级 {counts['A']} · B级 {counts['B']}。"
                 f" 每次账号分析完成后自动更新本清单。")
    return "\n".join(lines)


def build_daily_timeline() -> list[tuple[str, str]]:
    """【时序】每日关键词监控文档（按日期+关键词）"""
    docs = []
    for d in sorted(OUTPUT_BASE.iterdir()):
        if not d.is_dir() or not d.name.startswith('keyword_'):
            continue
        meta = load_json(d, 'meta.json')
        comments = load_comments(d)
        keyword = meta.get('keyword') or d.name.replace('keyword_', '')
        run_date = (meta.get('run_time') or '')[:10]
        if not run_date:
            continue

        signals = extract_demand_signals(comments, 5)
        words = top_words(comments, 15)

        lines = [
            f"# 【时序】{run_date} 关键词「{keyword}」监控\n",
            f"- 运行时间：{meta.get('run_time', '?')}",
            f"- 采集视频数：{len(meta.get('video_ids', []))}",
            f"- 去重评论数：{len(comments)}\n",
            "## 高频词 Top 15\n",
        ]
        for w, c in words:
            lines.append(f"- {w}（{c}）")
        lines.append("\n## 需求信号评论\n")
        if signals:
            for snippet, _ in signals:
                lines.append(f"- {snippet}")
        else:
            lines.append("- 本次未捕获明显需求信号")
        lines.append("\n> 每日定时监控自动生成，归档到「媒体账号监控」知识库。")
        docs.append((f"{run_date}_关键词{keyword}", "\n".join(lines)))
    return docs


def build_account_profiles() -> list[tuple[str, str]]:
    """【档案】单账号分析文档（一个号一份）"""
    docs = []
    for d in sorted(OUTPUT_BASE.iterdir()):
        if not d.is_dir() or not d.name.startswith('account_'):
            continue
        info = load_json(d, 'user_info.json')
        meta = load_json(d, 'meta.json')
        comments = load_comments(d)
        name = info.get('nickname') or d.name.replace('account_', '')
        signals = extract_demand_signals(comments, 5)
        words = top_words(comments, 15)

        lines = [
            f"# 【档案】{name} 账号分析\n",
            f"- 分析日期：{meta.get('run_time', '?')}",
            f"- 粉丝：{format_cn(info.get('follower_count'))}",
            f"- 获赞：{format_cn(info.get('total_favorited'))}",
            f"- 作品数：{info.get('aweme_count', '?')}",
            f"- 已分析视频：{len(meta.get('video_ids', []))}",
            f"- 去重评论：{len(comments)}",
            f"- sec_uid：{info.get('sec_uid', '?')}\n",
            "## 内容定位\n",
        ]
        if info.get('signature'):
            lines.append(f"签名：{info['signature']}")
        lines.append("\n## 评论区高频词 Top 15\n")
        for w, c in words:
            lines.append(f"- {w}（{c}）")
        lines.append("\n## 需求信号评论\n")
        if signals:
            for snippet, _ in signals:
                lines.append(f"- {snippet}")
        else:
            lines.append("- 未捕获明显需求信号")
        lines.append("\n> 每个账号一份档案，跨账号话题一致性分析见「汇报」文档。")
        docs.append((name, "\n".join(lines)))
    return docs


def build_cross_account_report() -> str:
    """【汇报】跨账号趋势汇总——高热度话题/高频问题/类型占比"""
    # 收集所有账号+关键词的评论
    all_comments = []
    sources = []
    per_dataset = {}
    for d in sorted(OUTPUT_BASE.iterdir()):
        if not d.is_dir() or not (d.name.startswith('account_') or d.name.startswith('keyword_')):
            continue
        comments = load_comments(d)
        if comments:
            label = d.name.replace('account_', '账号「').replace('keyword_', '关键词「')
            label += '」'
            sources.append((label, len(comments)))
            all_comments.extend(comments)
            per_dataset[d.name] = comments

    # 平台注入内容（跨数据集逐字重复，如推荐流标题）——只用于话题榜，不进其它统计
    platform_injected = cross_dataset_duplicates(per_dataset)

    total = len(all_comments)
    uniq = len(set(all_comments))
    lines = [
        "# 【汇报】出海非洲/非洲创业 跨账号评论趋势汇总\n",
        f"- 生成时间：{__import__('time').strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 覆盖数据源：{len(sources)} 个（{'、'.join(s[0] for s in sources)}）",
        f"- 原始评论：{total} 条（去重后 {uniq} 条）\n",
    ]

    # 1. 高热度话题（词频）
    lines.append("## 一、当前高热度话题 Top 20\n")
    for w, c in top_words(all_comments, 20, extra_skip=platform_injected):
        pct = c / max(1, total) * 100
        lines.append(f"{w}（{c} 次，{pct:.0f}%）")

    # 2. 类型占比：按需求关键词分类
    lines.append("\n## 二、评论区内容类型分布\n")
    type_map = {
        '合作/商务': ['合作', '招商', '加盟', '代理', '联系', '私信'],
        '货源/采购': ['货源', '采购', '进货', '工厂', '价格', '多少钱'],
        '意向/咨询': ['怎么', '如何', '想了解', '求带', '签证', '去非洲'],
        '投资/创业': ['投资', '创业', '项目'],
        '渠道/获客': ['渠道', '引流', '粉丝', '涨粉'],
    }
    type_counts = Counter()
    for c in set(all_comments):
        for tname, kws in type_map.items():
            if any(kw in c for kw in kws):
                type_counts[tname] += 1
                break
    matched = sum(type_counts.values())
    if matched:
        for tname, cnt in type_counts.most_common():
            lines.append(f"- {tname}：{cnt} 条（{cnt/matched*100:.0f}% 占需求类评论）")
        lines.append(f"- 需求类评论合计：{matched} 条，占全部评论 {matched/max(1,uniq)*100:.0f}%")
        lines.append(f"- 其他（纯互动/闲聊）：{max(0, uniq - matched)} 条（{max(0, uniq-matched)/max(1,uniq)*100:.0f}%）")

    # 3. 高频问题（含疑问词的评论）
    lines.append("\n## 三、评论区问得最多的问题\n")
    question_kws = ['怎么', '如何', '多少钱', '能不能', '可以吗', '靠谱吗', '安全吗', '合法吗', '需要什么']
    q_counter = Counter()
    q_examples = {}
    for c in set(all_comments):
        for kw in question_kws:
            if kw in c:
                q_counter[kw] += 1
                if kw not in q_examples:
                    q_examples[kw] = c[:100]
                break
    if q_counter:
        for kw, cnt in q_counter.most_common(10):
            ex = q_examples.get(kw, '')
            lines.append(f"- 「{kw}」类 {cnt} 条：{ex}")
    else:
        lines.append("- 暂未捕获明显提问")

    # 4. 需求信号原文精选
    lines.append("\n## 四、高价值需求信号原文\n")
    signals = extract_demand_signals(list(set(all_comments)), 8)
    for snippet, _ in signals:
        lines.append(f"- {snippet}")

    lines.append("\n> 每次分析完成后自动更新本汇总，供内容选题与客户开发参考。")
    return "\n".join(lines)


def main():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    # 1. 监控对象清单
    register = build_account_register()
    f = ARCHIVE_DIR / "【监控对象】账号清单.md"
    f.write_text(register, encoding='utf-8')
    written.append(f)

    # 2. 时序监控文档
    for fname, content in build_daily_timeline():
        f = ARCHIVE_DIR / f"【时序】{fname}.md"
        f.write_text(content, encoding='utf-8')
        written.append(f)

    # 3. 账号档案
    for fname, content in build_account_profiles():
        f = ARCHIVE_DIR / f"【档案】{fname}.md"
        f.write_text(content, encoding='utf-8')
        written.append(f)

    # 4. 跨账号汇报
    report = build_cross_account_report()
    f = ARCHIVE_DIR / "【汇报】跨账号趋势汇总.md"
    f.write_text(report, encoding='utf-8')
    written.append(f)

    print(f"✅ 生成 {len(written)} 个归档文档:")
    for f in written:
        print(f"  - {f.relative_to(ARCHIVE_DIR)} ({f.stat().st_size} B)")


if __name__ == '__main__':
    main()
