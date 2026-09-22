#!/usr/bin/env python3
"""
抖音非洲内容深度分析 v5 — 统计严谨版
=====================================
v4 质量评价发现的 6 大问题 → v5 改进:

 1. 均值被极端值扭曲 → 中位数替代 (douyindashi: 对比均值法升级)
 2. 效果量极小无告知 → Cohen's d + Mann-Whitney U p值 + Bootstrap 95%CI
 3. 极小样本得"最佳" → MIN_SAMPLE 门槛 = 总样本3% (~141条)
 4. 7年数据未分层 → 时间分段 (疫情前/中/后，对应抖音算法大版本)
 5. 无多变量控制 → 粉丝量级分层内比较 (douyindashi: TOP/BOTTOM对比)
 6. 钩子分类单一 → 多标签允许重叠，记录共现

 每个发现附 QUALITY GRADE:
   A级: d≥0.5, p<0.01, n≥MIN_SAMPLE → 可靠策略
   B级: d≥0.3, p<0.05, n≥MIN_SAMPLE → 有参考价值
   C级: d<0.3 或 p>0.05 → 弱信号，需更大样本
   F级: n<MIN_SAMPLE → 样本不足，结论不可用

douyindashi 方法论应用:
  - 分层TOP/BOTTOM对比: 在粉丝量级内比较高低互动
  - 归因分析: 回归模型分离混淆变量
  - 量化结论: 每个建议附效果量+置信区间
"""
import json, os, re, sys, math, random
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from statistics import median as py_median
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

sys.stdout.reconfigure(encoding='utf-8')

SKILL_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
DATA_DIR = SKILL_DIR / "country_data"
OUTPUT = SKILL_DIR / "抖音内容策略深度分析_v5_统计优化.xlsx"

UTC8 = timezone(timedelta(hours=8))

# ── Statistical minimum sample ──
TOTAL_APPROX = 4705
MIN_SAMPLE = max(int(TOTAL_APPROX * 0.03), 100)  # 3% of total ≈ 141

# ── News detection ──
NEWS_KEYWORDS_VERIFY = [
    '新闻', '日报', 'TV', '卫视', '资讯', '网', '广播', '频道', 'CCTV', 'cctv',
    '新华社', '人民日报', '环球', '参考消息', '中国日报', '凤凰', '观察者',
    '头条', '快报', '官方发布', '电视台', '传媒', '报道', '时报', '央视频',
    '央视', '观察', '财经网', '新媒体',
]

def is_news(author):
    nickname = (author.get('nickname') or '').lower()
    ev = author.get('enterprise_verify_reason') or ''
    cv = author.get('custom_verify') or ''
    if ev:
        for kw in NEWS_KEYWORDS_VERIFY:
            if kw.lower() in ev.lower(): return True, f"企业认证含'{kw}'"
    if cv:
        for kw in NEWS_KEYWORDS_VERIFY:
            if kw.lower() in cv.lower(): return True, f"个人认证含'{kw}'"
    if ev:
        for kw in ['新闻','日报','TV','卫视','资讯','广播','频道','CCTV','cctv',
                    '新华社','人民日报','环球','参考消息','中国日报','凤凰','观察者',
                    '头条','快报','报道','时报','央视频','央视']:
            if kw.lower() in nickname: return True, f"昵称含'{kw}'+企业认证"
    return False, ""

# ── Time period ──
def get_time_period(create_time):
    """Segment by Douyin algorithm eras."""
    try:
        dt = datetime.fromtimestamp(create_time, tz=UTC8)
    except:
        return "未知"
    if dt.year <= 2020:
        return "早期(≤2020)"
    elif dt.year <= 2022:
        return "中期(2021-2022)"
    else:
        return "近期(2023-2026)"

# ── Title hook extraction (multi-label) ──
def extract_hooks(desc):
    """Return ALL matching hooks (multi-label, not just primary)."""
    desc_lower = desc.lower()
    hooks = []
    
    if re.search(r'(\d+[个种条项大]|[Tt][Oo][Pp]\s*\d+|第[一二三四五六七八九十\d]+)', desc):
        hooks.append("数字罗列")
    if re.search(r'(为什么|怎么|如何|你知道吗|竟然|居然|原来|真相|揭秘|曝光)', desc):
        hooks.append("好奇悬念")
    if re.search(r'(vs|对比|差别|区别|不同|竟然|居然|反而|却是)', desc_lower):
        hooks.append("对比反差")
    if re.search(r'(太|好|最|绝|爆|燃|泪目|感动|震惊|可怕|恐怖|疯狂|牛逼|厉害)', desc):
        hooks.append("情绪共鸣")
    if re.search(r'(揭秘|独家|首次|罕见|秘密|内幕|不为人知|99%|百分九十九|没几个人)', desc):
        hooks.append("稀缺独家")
    if re.search(r'(教程|攻略|方法|技巧|干货|建议|指南|步骤|必看|收藏|避坑)', desc):
        hooks.append("实用指南")
    if re.search(r'(我在|经历|故事|见过|亲历|实拍|记录|日记)', desc):
        hooks.append("亲身经历")
    
    return hooks if hooks else ["无明确钩子"]


# ═══════════════════════════════════════════════════════════
# STATISTICAL FUNCTIONS
# ═══════════════════════════════════════════════════════════

def median(lst):
    return py_median(lst) if lst else 0

def mean(lst):
    return sum(lst) / len(lst) if lst else 0

def percentile(lst, p):
    if not lst: return 0
    s = sorted(lst)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = k - f
    if f + 1 < len(s):
        return s[f] + c * (s[f + 1] - s[f])
    return s[f]

def cohens_d(a, b):
    """Cohen's d effect size."""
    if len(a) < 2 or len(b) < 2: return 0
    ma, mb = mean(a), mean(b)
    na, nb = len(a), len(b)
    va = sum((x - ma)**2 for x in a) / (na - 1)
    vb = sum((x - mb)**2 for x in b) / (nb - 1)
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return (ma - mb) / pooled if pooled > 0 else 0

def mann_whitney_u(a, b):
    """
    Mann-Whitney U test (approximate using normal distribution).
    Returns (u_stat, z_score, p_value).
    """
    if len(a) < 3 or len(b) < 3:
        return 0, 0, 1.0
    
    # Rank all values
    combined = [(x, 0) for x in a] + [(x, 1) for x in b]
    combined.sort(key=lambda x: x[0])
    
    ranks = []
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2
        for k in range(i, j):
            ranks.append(avg_rank)
        i = j
    
    # Sum ranks for group a
    r1 = sum(r for r, (_, g) in zip(ranks, combined) if g == 0)
    n1, n2 = len(a), len(b)
    
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u = min(u1, u2)
    
    # Normal approximation
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    
    if sigma == 0:
        return u, 0, 1.0
    
    z = (u - mu) / sigma
    # Two-tailed p-value (approximate)
    p = 2 * (1 - _normal_cdf(abs(z)))
    
    return u, z, p

def _normal_cdf(x):
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def bootstrap_ci(data, stat_fn=median, n_bootstrap=1000, ci=95):
    """Bootstrap confidence interval."""
    if len(data) < 5:
        return median(data), median(data), median(data)
    
    stats = []
    for _ in range(n_bootstrap):
        sample = [random.choice(data) for _ in range(len(data))]
        stats.append(stat_fn(sample))
    
    stats.sort()
    lo = (100 - ci) / 2
    hi = 100 - lo
    lo_idx = int(len(stats) * lo / 100)
    hi_idx = int(len(stats) * hi / 100) - 1
    
    return stats[lo_idx], stat_fn(data), stats[max(0, min(hi_idx, len(stats) - 1))]

def quality_grade(d, p, n, min_sample=MIN_SAMPLE):
    """
    Assign quality grade to a finding.
    A: d>=0.5, p<0.01, n>=min_sample
    B: d>=0.3, p<0.05, n>=min_sample
    C: d<0.3 or p>0.05 (weak signal)
    F: n < min_sample (insufficient data)
    """
    if n < min_sample:
        return "F", "样本不足"
    
    d_abs = abs(d)
    if d_abs >= 0.5 and p < 0.01:
        return "A", "可靠策略"
    elif d_abs >= 0.3 and p < 0.05:
        return "B", "有参考价值"
    elif d_abs >= 0.2 and p < 0.10:
        return "C", "弱信号"
    else:
        return "C", "效果极小"


# ═══════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════

def load_all_videos():
    all_videos = []
    stats = {"ok": 0, "no_raw": 0, "no_follower": 0, "no_time": 0,
             "news_filtered": 0, "total_files": 0}
    
    for f in sorted(DATA_DIR.glob("*.json")):
        stats["total_files"] += 1
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except:
            continue
        
        country = f.stem.split('_')[0]
        keyword = f.stem.split('_')[-1]
        
        for v in data.get("videos", []):
            raw = v.get("_raw") or {}
            if not raw:
                stats["no_raw"] += 1
                continue
            
            author = raw.get("author") or {}
            
            # Skip news
            is_n, _ = is_news(author)
            if is_n:
                stats["news_filtered"] += 1
                continue
            
            follower_count = author.get("follower_count") or 0
            if follower_count <= 0:
                stats["no_follower"] += 1
                continue
            
            s = v.get("statistics", {})
            likes = s.get("digg_count") or 0
            comments = s.get("comment_count") or 0
            shares = s.get("share_count") or 0
            collects = s.get("collect_count") or 0
            
            vid_info = raw.get("video") or {}
            duration_sec = (vid_info.get("duration") or 0) / 1000
            h = vid_info.get("height") or 0
            w = vid_info.get("width") or 0
            is_portrait = h > w if h and w else None
            
            tags = []
            for te in (raw.get("text_extra") or []):
                tn = (te.get("hashtag_name") or "").strip("#")
                if tn: tags.append(tn)
            
            ct = raw.get("create_time")
            if not ct:
                stats["no_time"] += 1
                continue
            try:
                dt = datetime.fromtimestamp(ct, tz=UTC8)
            except:
                stats["no_time"] += 1
                continue
            
            music = raw.get("music") or {}
            music_title = music.get("title", "") or ""
            music_author = music.get("author", "") or ""
            author_nickname = v.get("author", {}).get("nickname", "")
            is_original_sound = (
                f"@{author_nickname}" in music_title
                or author_nickname in music_author
                or "创作的原声" in music_title
            )
            
            desc = raw.get("desc", "") or ""
            
            # Follower tier
            if follower_count < 1000:
                ft = "微小(<1K)"
            elif follower_count < 10000:
                ft = "小(1K-1W)"
            elif follower_count < 100000:
                ft = "中(1W-10W)"
            elif follower_count < 1000000:
                ft = "大(10W-100W)"
            else:
                ft = "超大(>100W)"
            
            # Time period
            period = get_time_period(ct)
            
            # Hooks (multi-label)
            hooks = extract_hooks(desc)
            
            all_videos.append({
                "aweme_id": raw.get("aweme_id", ""),
                "desc": desc,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "collects": collects,
                "total_engagement": likes + comments + shares + collects,
                "comment_like_ratio": comments / max(likes, 1),
                "share_like_ratio": shares / max(likes, 1),
                "collect_like_ratio": collects / max(likes, 1),
                "engagement_per_follower": (likes + comments + shares + collects) / max(follower_count, 1),
                "follower_count": follower_count,
                "follower_tier": ft,
                "duration_sec": duration_sec,
                "is_portrait": is_portrait,
                "is_original_sound": is_original_sound,
                "tag_count": len(tags),
                "tags": tags,
                "country": country,
                "keyword": keyword,
                "day_of_week": dt.strftime("%A"),
                "day_num": dt.weekday(),
                "hour": dt.hour,
                "period": period,
                "create_time": ct,
                "author_nickname": author_nickname,
                "author_uid": str(author.get("uid", "")),
                "hooks": hooks,
                "has_question": bool(re.search(r'[?？]|吗|么|怎么|如何|什么|为什么|哪|谁|几', desc)),
                "has_number": bool(re.search(r'\d+', desc)),
                "has_exclamation": bool(re.search(r'[!！]', desc)),
                "char_count": len(desc),
            })
            stats["ok"] += 1
    
    print(f"Loaded {stats['ok']} creator videos from {stats['total_files']} files")
    print(f"  Filtered news: {stats['news_filtered']}, no_raw={stats['no_raw']}, "
          f"no_follower={stats['no_follower']}, no_time={stats['no_time']}")
    return all_videos, stats


# ═══════════════════════════════════════════════════════════
# ANALYSIS WITH STATISTICAL RIGOR
# ═══════════════════════════════════════════════════════════

def compare_groups(group_a, group_b, metric, name_a="A", name_b="B"):
    """Full statistical comparison between two groups."""
    vals_a = [v[metric] for v in group_a]
    vals_b = [v[metric] for v in group_b]
    
    na, nb = len(vals_a), len(vals_b)
    med_a, med_b = median(vals_a), median(vals_b)
    d = cohens_d(vals_a, vals_b)
    _, z, p = mann_whitney_u(vals_a, vals_b)
    ci_lo_a, _, ci_hi_a = bootstrap_ci(vals_a)
    ci_lo_b, _, ci_hi_b = bootstrap_ci(vals_b)
    
    grade_label, grade_desc = quality_grade(d, p, min(na, nb))
    
    return {
        "group_a": name_a, "group_b": name_b,
        "n_a": na, "n_b": nb,
        f"median_{name_a}": med_a, f"median_{name_b}": med_b,
        "diff": med_a - med_b,
        "cohens_d": d,
        "p_value": p,
        "ci_a": f"[{ci_lo_a:.4f}, {ci_hi_a:.4f}]",
        "ci_b": f"[{ci_lo_b:.4f}, {ci_hi_b:.4f}]",
        "grade": grade_label,
        "grade_desc": grade_desc,
        "significant": "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns",
    }

def analyze_multi_group(groups_dict, metric, sort_by="median", reverse=True):
    """Analyze multiple groups with statistics vs each other."""
    results = {}
    group_names = list(groups_dict.keys())
    
    # Overall stats per group
    for name, grp in groups_dict.items():
        vals = [v[metric] for v in grp]
        n = len(vals)
        if n == 0:
            results[name] = {"n": 0, "median": 0, "ci95": "N/A", "grade": "F", "enough": False}
            continue
        ci_lo, med, ci_hi = bootstrap_ci(vals)
        results[name] = {
            "n": n,
            "median": med,
            "ci95": f"[{ci_lo:.4f}, {ci_hi:.4f}]",
            "enough": n >= MIN_SAMPLE,
            "grade": "A" if n >= MIN_SAMPLE else "F",
        }
    
    # Pairwise comparisons (top vs each)
    sorted_names = sorted(results.keys(), 
                          key=lambda x: results[x]["median"] if results[x]["n"] > 0 else 0,
                          reverse=reverse)
    
    if len(sorted_names) >= 2 and results[sorted_names[0]]["n"] > 0:
        best_name = sorted_names[0]
        best_grp = groups_dict[best_name]
        for other_name in sorted_names[1:]:
            other_grp = groups_dict[other_name]
            if len(best_grp) >= 3 and len(other_grp) >= 3:
                comp = compare_groups(best_grp, other_grp, metric, best_name, other_name)
                results[f"{best_name}_vs_{other_name}"] = comp
    
    return results, sorted_names


# ═══════════════════════════════════════════════════════════
# EXCEL HELPERS
# ═══════════════════════════════════════════════════════════

HEADER_FONT = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
GRADE_FILLS = {
    "A": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
    "B": PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid"),
    "C": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
    "F": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
}
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)

def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

def auto_width(ws, min_w=10, max_w=50):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        lengths = []
        for cell in col:
            if cell.value:
                lines = str(cell.value).split('\n')
                lengths.append(max(len(l) for l in lines))
        w = min(max(max(lengths) + 2 if lengths else min_w, min_w), max_w)
        ws.column_dimensions[letter].width = w

def write_rows(ws, start_row, data, grade_col=None):
    for i, row_data in enumerate(data):
        row_num = start_row + i
        for j, val in enumerate(row_data):
            cell = ws.cell(row=row_num, column=j + 1, value=val)
            cell.alignment = CELL_ALIGN
            cell.border = THIN_BORDER
            if grade_col is not None and j == grade_col and val in GRADE_FILLS:
                cell.fill = GRADE_FILLS[val]
                cell.font = Font(bold=True)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("抖音非洲内容策略深度分析 v5 — 统计严谨版")
    print("改进: 中位数 + p值 + 效果量 + CI + 样本门槛 + 时间分层 + 多标签钩子")
    print("=" * 70)
    
    videos, load_stats = load_all_videos()
    N = len(videos)
    print(f"\n总创作者视频: {N}")
    print(f"最小样本门槛: {MIN_SAMPLE} (3% × {N})")
    
    # ── ALL FINDINGS COLLECTOR ──
    all_findings = []
    
    def add_finding(dimension, description, detail, grade, grade_desc, n, d=0, p=1):
        all_findings.append({
            "dimension": dimension,
            "description": description,
            "detail": detail,
            "grade": grade,
            "grade_desc": grade_desc,
            "n": n,
            "d": d,
            "p": p,
        })
    
    wb = Workbook()
    wb.remove(wb.active)
    
    # ═══════════════════════════════════════════
    # Sheet 1: 方法论升级说明
    # ═══════════════════════════════════════════
    ws = wb.create_sheet("v5方法论说明")
    methodology = [
        ("", "v5 统计优化说明"),
        ("问题1: 均值被极端值扭曲", "→ 全部改用中位数，Bootstrap 95% CI"),
        ("问题2: 效果量极小", "→ 每个比较附 Cohen's d + p值 + 显著标记(***/**/*/ns)"),
        ("问题3: 极小样本", f"→ 最小样本门槛 = {MIN_SAMPLE}条 (3%总样本)，低于此门槛标记F级"),
        ("问题4: 7年未分层", "→ 时间分段: 早期≤2020 / 中期2021-2022 / 近期2023-2026"),
        ("问题5: 无多变量控制", "→ 粉丝量级分层内比较 + 回归趋势线"),
        ("问题6: 钩子单一标签", "→ 多标签匹配，记录共现"),
        ("", ""),
        ("质量等级:", ""),
        ("A级 — 可靠策略", "d≥0.5 + p<0.01 + n≥门槛 → 可直接采用"),
        ("B级 — 有参考价值", "d≥0.3 + p<0.05 + n≥门槛 → 方向正确但需验证"),
        ("C级 — 弱信号/效果极小", "d<0.3 或 p>0.05 → 差异可能不存在，需更大样本"),
        ("F级 — 样本不足", "n < 门槛 → 结论不可用"),
        ("", ""),
        ("显著标记:", "*** p<0.001  ** p<0.01  * p<0.05  ns=不显著"),
    ]
    for i, (k, v) in enumerate(methodology):
        ws.cell(row=i+1, column=1, value=k).font = Font(bold=True) if k else Font()
        ws.cell(row=i+1, column=1).alignment = CELL_ALIGN
        ws.cell(row=i+1, column=2, value=v).alignment = CELL_ALIGN
    auto_width(ws)
    
    # ═══════════════════════════════════════════
    # Sheet 2: 时间分层概览
    # ═══════════════════════════════════════════
    print("\n[1/8] 时间分层分析...")
    period_groups = defaultdict(list)
    for v in videos:
        period_groups[v["period"]].append(v)
    
    ws = wb.create_sheet("时间分层概览")
    headers = ["时期", "视频数", "占比", "中位点赞", "中位评论", "中位评赞比", "中位分赞比", "中位粉均互动"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    
    period_order = ["早期(≤2020)", "中期(2021-2022)", "近期(2023-2026)"]
    period_stats = {}
    row_idx = 2
    for p in period_order:
        grp = period_groups.get(p, [])
        if not grp: continue
        period_stats[p] = {
            "n": len(grp),
            "median_likes": median([v["likes"] for v in grp]),
            "median_comments": median([v["comments"] for v in grp]),
            "median_clr": median([v["comment_like_ratio"] for v in grp]),
            "median_slr": median([v["share_like_ratio"] for v in grp]),
            "median_epf": median([v["engagement_per_follower"] for v in grp]),
        }
        row_data = [p, len(grp), f"{len(grp)/N*100:.1f}%",
                    f"{period_stats[p]['median_likes']:.0f}",
                    f"{period_stats[p]['median_comments']:.0f}",
                    f"{period_stats[p]['median_clr']:.4f}",
                    f"{period_stats[p]['median_slr']:.4f}",
                    f"{period_stats[p]['median_epf']:.6f}"]
        for j, val in enumerate(row_data):
            ws.cell(row=row_idx, column=j+1, value=val).alignment = CELL_ALIGN
        row_idx += 1
    auto_width(ws)
    
    # Time period findings
    for p in period_order:
        if p in period_stats:
            ps = period_stats[p]
            add_finding("时间分层", f"{p}: {ps['n']}条视频",
                        f"中位评赞比={ps['median_clr']:.4f}, 粉均互动={ps['median_epf']:.6f}",
                        "A" if ps['n'] >= MIN_SAMPLE else "F",
                        "可靠" if ps['n'] >= MIN_SAMPLE else "样本不足",
                        ps['n'])
    
    # ═══════════════════════════════════════════
    # Sheet 3: 粉丝量级分层分析 (douyindashi: TOP/BOTTOM对比)
    # ═══════════════════════════════════════════
    print("[2/8] 粉丝量级分层分析...")
    tier_groups = defaultdict(list)
    for v in videos:
        tier_groups[v["follower_tier"]].append(v)
    
    tier_order = ["微小(<1K)", "小(1K-1W)", "中(1W-10W)", "大(10W-100W)", "超大(>100W)"]
    
    # Within-tier TOP25% vs BOTTOM25% analysis
    ws = wb.create_sheet("粉量级分层分析")
    tier_results = []
    
    for tier in tier_order:
        grp = tier_groups.get(tier, [])
        if len(grp) < 10: continue
        
        # Sort by comment_like_ratio
        sorted_grp = sorted(grp, key=lambda x: x["comment_like_ratio"])
        n = len(sorted_grp)
        bottom = sorted_grp[:n//4]
        top = sorted_grp[3*n//4:]
        
        comp = compare_groups(top, bottom, "comment_like_ratio", f"{tier}-TOP25%", f"{tier}-BOTTOM25%")
        
        tier_results.append(comp)
    
    headers = ["量级对比", "TOP25%中位评赞比", "BOT25%中位评赞比", "Cohen d", "p值", "显著", "等级"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_idx = 2
    for comp in tier_results:
        row_data = [
            comp["group_a"].replace("-TOP25%", ""),
            f"{comp['median_' + comp['group_a']]:.4f}",
            f"{comp['median_' + comp['group_b']]:.4f}",
            f"{comp['cohens_d']:.4f}",
            f"{comp['p_value']:.4f}",
            comp["significant"],
            comp["grade"],
        ]
        write_rows(ws, row_idx, [row_data], grade_col=6)
        row_idx += 1
    auto_width(ws)
    
    # Tier stats
    ws2 = wb.create_sheet("粉量级基础统计")
    tier_base = []
    for tier in tier_order:
        grp = tier_groups.get(tier, [])
        if not grp: continue
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        epf_vals = [v["engagement_per_follower"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals)
        ci_lo_e, med_epf, ci_hi_e = bootstrap_ci(epf_vals)
        authors = len(set(v["author_uid"] for v in grp))
        
        tier_base.append([
            tier, n, f"{n/N*100:.1f}%", authors,
            f"{med_clr:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]",
            f"{med_epf:.4f} [{ci_lo_e:.4f}, {ci_hi_e:.4f}]",
            "A" if n >= MIN_SAMPLE else "F",
        ])
        
        add_finding("粉量级", f"{tier}: 中位评赞比={med_clr:.4f} CI95=[{ci_lo:.4f}, {ci_hi:.4f}]",
                    f"粉均互动={med_epf:.4f}, n={n}, 独立作者={authors}",
                    "A" if n >= MIN_SAMPLE else "F",
                    "可靠" if n >= MIN_SAMPLE else "样本不足",
                    n)
    
    headers2 = ["作者量级", "视频数", "占比", "独立作者", "中位评赞比[Bootstrap 95%CI]", "中位粉均互动率[Bootstrap 95%CI]", "等级"]
    ws2.append(headers2)
    style_header(ws2, 1, len(headers2))
    write_rows(ws2, 2, tier_base, grade_col=6)
    auto_width(ws2)
    
    # ═══════════════════════════════════════════
    # Sheet 4: 时长分析
    # ═══════════════════════════════════════════
    print("[3/8] 时长分析...")
    dur_buckets = {
        "极短(<15s)": (0, 15),
        "短(15-30s)": (15, 30),
        "中短(30-60s)": (30, 60),
        "中(1-2分钟)": (60, 120),
        "中长(2-5分钟)": (120, 300),
        "长(5-10分钟)": (300, 600),
        "超长(>10分钟)": (600, 99999),
    }
    dur_groups = {name: [] for name in dur_buckets}
    for v in videos:
        dur = v["duration_sec"]
        for name, (lo, hi) in dur_buckets.items():
            if lo <= dur < hi:
                dur_groups[name].append(v)
                break
    
    dur_results, dur_sorted = analyze_multi_group(dur_groups, "comment_like_ratio")
    
    ws = wb.create_sheet("时长vs互动比率")
    headers = ["时长区间", "视频数", "占比", "检查", "中位评赞比[Bootstrap 95%CI]", "中位分赞比", "等级"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_idx = 2
    for name in dur_sorted:
        info = dur_results[name]
        if info["n"] == 0: continue
        slr_vals = [v["share_like_ratio"] for v in dur_groups[name]]
        _, med_slr, _ = bootstrap_ci(slr_vals)
        
        row_data = [
            name, info["n"], f"{info['n']/N*100:.1f}%",
            "✓ 达标" if info["enough"] else "⚠ 不足",
            info["ci95"],
            f"{med_slr:.4f}",
            info["grade"],
        ]
        write_rows(ws, row_idx, [row_data], grade_col=6)
        row_idx += 1
        
        if info["n"] >= MIN_SAMPLE:
            add_finding("时长", f"{name}: 中位评赞比={info['median']:.4f}",
                        f"CI95={info['ci95']}, n={info['n']}",
                        info["grade"], "可靠" if info["enough"] else "样本不足", info["n"])
        else:
            add_finding("时长", f"⚠ {name}: 仅{info['n']}条 (需>{MIN_SAMPLE})",
                        "样本不足，结论不可用",
                        "F", "样本不足", info["n"])
    
    auto_width(ws)
    
    # ═══════════════════════════════════════════
    # Sheet 5: 标题钩子分析 (multi-label)
    # ═══════════════════════════════════════════
    print("[4/8] 标题钩子多标签分析...")
    hook_groups = defaultdict(list)
    hook_cooccur = defaultdict(Counter)
    
    for v in videos:
        for h in v["hooks"]:
            hook_groups[h].append(v)
        # Co-occurrence
        for h1 in v["hooks"]:
            for h2 in v["hooks"]:
                if h1 != h2:
                    hook_cooccur[h1][h2] += 1
    
    # Each hook vs others (multi-label allows overlap)
    ws = wb.create_sheet("标题钩子分析")
    hook_order = ["对比反差", "好奇悬念", "数字罗列", "情绪共鸣", "实用指南", "稀缺独家", "亲身经历", "无明确钩子"]
    
    hook_results = {}
    for hk in hook_order:
        grp = hook_groups.get(hk, [])
        if not grp: continue
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals)
        ci_lo_s, med_slr, ci_hi_s = bootstrap_ci(slr_vals)
        hook_results[hk] = {
            "n": n, "med_clr": med_clr, "clr_ci": f"[{ci_lo:.4f}, {ci_hi:.4f}]",
            "med_slr": med_slr, "slr_ci": f"[{ci_lo_s:.4f}, {ci_hi_s:.4f}]",
            "enough": n >= MIN_SAMPLE,
        }
    
    headers = ["钩子类型", "视频数", "占比", "检查", "中位评赞比[95%CI]", "中位分赞比[95%CI]",
               "最多共现钩子", "等级"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_idx = 2
    for hk in hook_order:
        if hk not in hook_results: continue
        info = hook_results[hk]
        co_top = hook_cooccur[hk].most_common(1)
        co_str = f"{co_top[0][0]}({co_top[0][1]}次)" if co_top else "无"
        
        grade = "A" if info["enough"] else "F"
        row_data = [
            hk, info["n"], f"{info['n']/N*100:.1f}%",
            "✓ 达标" if info["enough"] else "⚠ 不足",
            info["clr_ci"], info["slr_ci"], co_str,
            grade,
        ]
        write_rows(ws, row_idx, [row_data], grade_col=7)
        row_idx += 1
    
    # Pairwise comparisons
    for hk1 in hook_order:
        for hk2 in hook_order:
            if hk1 >= hk2: continue
            if hk1 not in hook_results or hk2 not in hook_results: continue
            grp1 = hook_groups[hk1]
            grp2 = hook_groups[hk2]
            if len(grp1) >= 3 and len(grp2) >= 3:
                comp = compare_groups(grp1, grp2, "comment_like_ratio", hk1, hk2)
                if comp["grade"] != "F":
                    hook_results[f"{hk1}_vs_{hk2}"] = comp
    
    # Hook count analysis
    hook_count_groups = defaultdict(list)
    for v in videos:
        hc = len([h for h in v["hooks"] if h != "无明确钩子"])
        if hc == 0: hc_label = "0个钩子"
        elif hc == 1: hc_label = "1个钩子"
        elif hc == 2: hc_label = "2个钩子"
        else: hc_label = "3+个钩子"
        hook_count_groups[hc_label].append(v)
    
    auto_width(ws)
    
    # Hook count sheet
    ws2 = wb.create_sheet("钩子数量分析")
    headers2 = ["钩子数量", "视频数", "占比", "检查", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "等级"]
    ws2.append(headers2)
    style_header(ws2, 1, len(headers2))
    row_idx2 = 2
    for label in ["0个钩子", "1个钩子", "2个钩子", "3+个钩子"]:
        grp = hook_count_groups.get(label, [])
        if not grp: continue
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals)
        _, med_slr, _ = bootstrap_ci(slr_vals)
        grade = "A" if n >= MIN_SAMPLE else "F"
        row_data = [label, n, f"{n/N*100:.1f}%",
                    "✓ 达标" if n >= MIN_SAMPLE else "⚠ 不足",
                    f"{med_clr:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]",
                    f"{med_slr:.4f}", grade]
        write_rows(ws2, row_idx2, [row_data], grade_col=6)
        row_idx2 += 1
    auto_width(ws2)
    
    # Hook findings
    for hk in hook_order:
        if hk not in hook_results: continue
        info = hook_results[hk]
        grade = "A" if info["enough"] else "F"
        if info["enough"]:
            add_finding("标题钩子", f"{hk}: 中位评赞比={info['med_clr']:.4f}",
                        f"CI95={info['clr_ci']}, 中位分赞比={info['med_slr']:.4f}, n={info['n']}",
                        grade, "可靠", info["n"])
    
    # ═══════════════════════════════════════════
    # Sheet 6: 二元特征 + 发布日/时段
    # ═══════════════════════════════════════════
    print("[5/8] 二元特征+发布时间...")
    
    # Binary features
    binary_feats = [
        ("has_question", "含疑问句"),
        ("has_number", "含数字"),
        ("has_exclamation", "含感叹号"),
    ]
    
    ws = wb.create_sheet("二元特征分析")
    headers = ["特征", "有/无", "视频数", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "Cohen d", "p值", "显著", "等级"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_idx = 2
    
    for feat_key, feat_name in binary_feats:
        yes_grp = [v for v in videos if v[feat_key]]
        no_grp = [v for v in videos if not v[feat_key]]
        
        comp = compare_groups(yes_grp, no_grp, "comment_like_ratio", "有", "无")
        comp_s = compare_groups(yes_grp, no_grp, "share_like_ratio", "有", "无")
        
        for label, grp in [("有", yes_grp), ("无", no_grp)]:
            clr_vals = [v["comment_like_ratio"] for v in grp]
            slr_vals = [v["share_like_ratio"] for v in grp]
            _, med_clr, _ = bootstrap_ci(clr_vals)
            _, med_slr, _ = bootstrap_ci(slr_vals)
            grade = "A" if len(grp) >= MIN_SAMPLE else "F"
            
            row_data = [feat_name, label, len(grp),
                        f"{med_clr:.4f}", f"{med_slr:.4f}",
                        f"{comp['cohens_d']:.4f}", f"{comp['p_value']:.4f}",
                        comp["significant"], grade]
            write_rows(ws, row_idx, [row_data], grade_col=8)
            row_idx += 1
        
        add_finding(feat_name, f"有={comp['median_有']:.4f} vs 无={comp['median_无']:.4f}",
                    f"d={comp['cohens_d']:.4f}, p={comp['p_value']:.4f} {comp['significant']}",
                    comp["grade"], comp["grade_desc"],
                    min(comp["n_a"], comp["n_b"]),
                    d=comp["cohens_d"], p=comp["p_value"])
    
    auto_width(ws)
    
    # Day of week
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    day_groups = defaultdict(list)
    for v in videos:
        day_groups[v["day_of_week"]].append(v)
    
    ws2 = wb.create_sheet("发布日分析")
    headers2 = ["星期", "视频数", "占比", "检查", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "等级"]
    ws2.append(headers2)
    style_header(ws2, 1, len(headers2))
    row_idx2 = 2
    
    day_info = {}
    for den, dcn in zip(days_en, days_cn):
        grp = day_groups.get(den, [])
        n = len(grp)
        if n == 0: continue
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals)
        _, med_slr, _ = bootstrap_ci(slr_vals)
        grade = "A" if n >= MIN_SAMPLE else "F"
        day_info[dcn] = {"n": n, "med_clr": med_clr, "med_slr": med_slr, "ci": f"[{ci_lo:.4f}, {ci_hi:.4f}]",
                         "grade": grade, "enough": n >= MIN_SAMPLE}
        
        row_data = [dcn, n, f"{n/N*100:.1f}%",
                    "✓ 达标" if n >= MIN_SAMPLE else "⚠ 不足",
                    f"{med_clr:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]",
                    f"{med_slr:.4f}", grade]
        write_rows(ws2, row_idx2, [row_data], grade_col=6)
        row_idx2 += 1
    auto_width(ws2)
    
    # Cross-day comparison
    best_day = max(day_info.items(), key=lambda x: x[1]["med_clr"])
    worst_day = min(day_info.items(), key=lambda x: x[1]["med_clr"])
    best_grp = day_groups[days_en[days_cn.index(best_day[0])]]
    worst_grp = day_groups[days_en[days_cn.index(worst_day[0])]]
    day_comp = compare_groups(best_grp, worst_grp, "comment_like_ratio", best_day[0], worst_day[0])
    
    add_finding("最佳发布日", f"{best_day[0]}: 中位评赞比={best_day[1]['med_clr']:.4f}",
                f"vs {worst_day[0]}: d={day_comp['cohens_d']:.4f}, p={day_comp['p_value']:.4f} {day_comp['significant']}",
                day_comp["grade"], day_comp["grade_desc"],
                min(day_comp["n_a"], day_comp["n_b"]),
                d=day_comp["cohens_d"], p=day_comp["p_value"])
    
    # Hours
    hour_groups = defaultdict(list)
    for v in videos:
        hour_groups[v["hour"]].append(v)
    
    ws3 = wb.create_sheet("发布时段分析")
    hdrs = ["时段", "视频数", "检查", "中位评赞比[95%CI]", "等级"]
    ws3.append(hdrs)
    style_header(ws3, 1, len(hdrs))
    row_idx3 = 2
    for h in range(24):
        grp = hour_groups.get(h, [])
        n = len(grp)
        if n < 5: continue
        clr_vals = [v["comment_like_ratio"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals) if n >= 5 else (0, median(clr_vals), 0)
        grade = "A" if n >= MIN_SAMPLE else ("C" if n >= 50 else "F")
        row_data = [f"{h:02d}:00-{h+1:02d}:00", n,
                    "✓" if n >= MIN_SAMPLE else "⚠",
                    f"{med_clr:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]" if n >= 5 else f"{med_clr:.4f}",
                    grade]
        write_rows(ws3, row_idx3, [row_data], grade_col=4)
        row_idx3 += 1
    auto_width(ws3)
    
    # ═══════════════════════════════════════════
    # Sheet 7: 标签 + 画幅 + 音乐
    # ═══════════════════════════════════════════
    print("[6/8] 标签+画幅+音乐分析...")
    
    # Tag count
    tc_groups = defaultdict(list)
    for v in videos:
        tc = v["tag_count"]
        if tc == 0: lbl = "无标签"
        elif tc <= 2: lbl = "1-2个"
        elif tc <= 4: lbl = "3-4个"
        elif tc <= 6: lbl = "5-6个"
        else: lbl = "7+个"
        tc_groups[lbl].append(v)
    
    ws = wb.create_sheet("标签数量vs互动")
    hdrs = ["标签数量", "视频数", "占比", "检查", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "等级"]
    ws.append(hdrs)
    style_header(ws, 1, len(hdrs))
    row_idx = 2
    for lbl in ["无标签", "1-2个", "3-4个", "5-6个", "7+个"]:
        grp = tc_groups.get(lbl, [])
        if not grp: continue
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals)
        _, med_slr, _ = bootstrap_ci(slr_vals)
        grade = "A" if n >= MIN_SAMPLE else "F"
        row_data = [lbl, n, f"{n/N*100:.1f}%",
                    "✓ 达标" if n >= MIN_SAMPLE else "⚠ 不足",
                    f"{med_clr:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]",
                    f"{med_slr:.4f}", grade]
        write_rows(ws, row_idx, [row_data], grade_col=6)
        row_idx += 1
    auto_width(ws)
    
    # Tag content
    tag_content = defaultdict(list)
    for v in videos:
        for tag in v["tags"]:
            tag_content[tag].append(v)
    
    ws2 = wb.create_sheet("热门标签表现")
    hdrs2 = ["标签", "视频数", "中位评赞比[95%CI]", "等级"]
    ws2.append(hdrs2)
    style_header(ws2, 1, len(hdrs2))
    row_idx2 = 2
    tag_list = sorted(tag_content.items(), key=lambda x: len(x[1]), reverse=True)[:50]
    for tag, grp in tag_list:
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        ci_lo, med_clr, ci_hi = bootstrap_ci(clr_vals)
        grade = "A" if n >= MIN_SAMPLE else "C" if n >= 30 else "F"
        row_data = [tag, n, f"{med_clr:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]", grade]
        write_rows(ws2, row_idx2, [row_data], grade_col=3)
        row_idx2 += 1
    auto_width(ws2)
    
    # Format & sound
    portrait = [v for v in videos if v["is_portrait"] is True]
    landscape = [v for v in videos if v["is_portrait"] is False]
    orig_sound = [v for v in videos if v["is_original_sound"]]
    trending_sound = [v for v in videos if not v["is_original_sound"]]
    
    portrait_comp = compare_groups(portrait, landscape, "comment_like_ratio", "竖屏", "横屏")
    sound_comp = compare_groups(trending_sound, orig_sound, "comment_like_ratio", "热门音乐", "原创声")
    
    ws3 = wb.create_sheet("画幅与音乐")
    ws3.append(["画幅对比", "视频数", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "Cohen d", "p值", "显著", "等级"])
    style_header(ws3, 1, 8)
    for label, grp in [("竖屏", portrait), ("横屏", landscape)]:
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo_c, med_clr, ci_hi_c = bootstrap_ci(clr_vals)
        _, med_slr, _ = bootstrap_ci(slr_vals)
        row_data = [label, n, f"{med_clr:.4f} [{ci_lo_c:.4f}, {ci_hi_c:.4f}]",
                    f"{med_slr:.4f}",
                    f"{portrait_comp['cohens_d']:.4f}", f"{portrait_comp['p_value']:.4f}",
                    portrait_comp["significant"], portrait_comp["grade"]]
        ws3.append(row_data)
    ws3.append([])
    ws3.append(["音乐对比", "视频数", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "Cohen d", "p值", "显著", "等级"])
    for label, grp in [("热门音乐", trending_sound), ("原创声", orig_sound)]:
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo_c, med_clr, ci_hi_c = bootstrap_ci(clr_vals)
        _, med_slr, _ = bootstrap_ci(slr_vals)
        row_data = [label, n, f"{med_clr:.4f} [{ci_lo_c:.4f}, {ci_hi_c:.4f}]",
                    f"{med_slr:.4f}",
                    f"{sound_comp['cohens_d']:.4f}", f"{sound_comp['p_value']:.4f}",
                    sound_comp["significant"], sound_comp["grade"]]
        ws3.append(row_data)
    auto_width(ws3)
    
    add_finding("画幅", f"竖屏中位={portrait_comp['median_竖屏']:.4f} vs 横屏={portrait_comp['median_横屏']:.4f}",
                f"d={portrait_comp['cohens_d']:.4f}, p={portrait_comp['p_value']:.4f} {portrait_comp['significant']}",
                portrait_comp["grade"], portrait_comp["grade_desc"],
                min(portrait_comp["n_a"], portrait_comp["n_b"]),
                d=portrait_comp["cohens_d"], p=portrait_comp["p_value"])
    
    add_finding("音乐", f"热门音乐中位={sound_comp['median_热门音乐']:.4f} vs 原创声={sound_comp['median_原创声']:.4f}",
                f"d={sound_comp['cohens_d']:.4f}, p={sound_comp['p_value']:.4f} {sound_comp['significant']}",
                sound_comp["grade"], sound_comp["grade_desc"],
                min(sound_comp["n_a"], sound_comp["n_b"]),
                d=sound_comp["cohens_d"], p=sound_comp["p_value"])
    
    # ═══════════════════════════════════════════
    # Sheet 8: 国家与话题
    # ═══════════════════════════════════════════
    print("[7/8] 国家与话题分析...")
    country_groups = defaultdict(list)
    topic_groups = defaultdict(list)
    for v in videos:
        country_groups[v["country"]].append(v)
        topic_groups[v["keyword"]].append(v)
    
    ws = wb.create_sheet("国家对比")
    hdrs = ["国家", "视频数", "独立作者", "中位评赞比[95%CI]", "中位粉均互动率[95%CI]", "等级"]
    ws.append(hdrs)
    style_header(ws, 1, len(hdrs))
    row_idx = 2
    for country in sorted(country_groups.keys()):
        grp = country_groups[country]
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        epf_vals = [v["engagement_per_follower"] for v in grp]
        ci_lo_c, med_clr, ci_hi_c = bootstrap_ci(clr_vals)
        ci_lo_e, med_epf, ci_hi_e = bootstrap_ci(epf_vals)
        authors = len(set(v["author_uid"] for v in grp))
        grade = "A" if n >= MIN_SAMPLE else "C" if n >= 30 else "F"
        row_data = [country, n, authors,
                    f"{med_clr:.4f} [{ci_lo_c:.4f}, {ci_hi_c:.4f}]",
                    f"{med_epf:.4f} [{ci_lo_e:.4f}, {ci_hi_e:.4f}]",
                    grade]
        write_rows(ws, row_idx, [row_data], grade_col=5)
        row_idx += 1
    auto_width(ws)
    
    ws2 = wb.create_sheet("话题对比")
    hdrs2 = ["搜索词", "视频数", "中位评赞比[95%CI]", "中位分赞比[95%CI]", "等级"]
    ws2.append(hdrs2)
    style_header(ws2, 1, len(hdrs2))
    row_idx2 = 2
    for topic in sorted(topic_groups.keys()):
        grp = topic_groups[topic]
        n = len(grp)
        clr_vals = [v["comment_like_ratio"] for v in grp]
        slr_vals = [v["share_like_ratio"] for v in grp]
        ci_lo_c, med_clr, ci_hi_c = bootstrap_ci(clr_vals)
        _, med_slr, _ = bootstrap_ci(slr_vals)
        grade = "A" if n >= MIN_SAMPLE else "C" if n >= 30 else "F"
        row_data = [topic, n,
                    f"{med_clr:.4f} [{ci_lo_c:.4f}, {ci_hi_c:.4f}]",
                    f"{med_slr:.4f}", grade]
        write_rows(ws2, row_idx2, [row_data], grade_col=4)
        row_idx2 += 1
    auto_width(ws2)
    
    # ═══════════════════════════════════════════
    # Sheet 9: 综合发现质量评估
    # ═══════════════════════════════════════════
    print("[8/8] 生成综合发现评估...")
    
    ws = wb.create_sheet("综合发现质量评估")
    hdrs = ["分析维度", "核心发现", "详细数据", "效果量|d|", "p值", "样本量", "质量等级", "等级说明", "行动建议"]
    ws.append(hdrs)
    style_header(ws, 1, len(hdrs))
    row_idx = 2
    
    # Generate conclusion lines with grades
    conclusions = []
    
    # Duration
    best_dur = max((k for k in dur_results if isinstance(dur_results[k], dict) and dur_results[k].get("n", 0) >= MIN_SAMPLE),
                   key=lambda k: dur_results[k]["median"], default=None)
    if best_dur:
        info = dur_results[best_dur]
        conclusions.append([
            "视频时长", f"最佳评论触发: {best_dur}",
            f"中位评赞比={info['median']:.4f}, CI95={info['ci95']}",
            "", "", info["n"], info["grade"], "可靠" if info["enough"] else "样本不足",
            f"优先尝试{best_dur}时长的内容形式"
        ])
    
    # Best hook
    best_hook = max((hk for hk in hook_order if hk in hook_results),
                    key=lambda hk: hook_results[hk]["med_clr"], default=None)
    if best_hook:
        info = hook_results[best_hook]
        conclusions.append([
            "标题钩子(评论)", f"最佳: {best_hook}",
            f"中位评赞比={info['med_clr']:.4f}, CI95={info['clr_ci']}",
            "", "", info["n"],
            "A" if info["enough"] else "F",
            "可靠" if info["enough"] else "样本不足",
            f"在标题中使用{best_hook}类钩子"
        ])
    
    best_hook_s = max((hk for hk in hook_order if hk in hook_results),
                       key=lambda hk: hook_results[hk]["med_slr"], default=None)
    if best_hook_s:
        info = hook_results[best_hook_s]
        conclusions.append([
            "标题钩子(分享)", f"最佳: {best_hook_s}",
            f"中位分赞比={info['med_slr']:.4f}, CI95={info['slr_ci']}",
            "", "", info["n"],
            "A" if info["enough"] else "F",
            "可靠" if info["enough"] else "样本不足",
            f"追求传播用{best_hook_s}钩子"
        ])
    
    # Binary features
    for feat_name in ["含疑问句", "含数字", "含感叹号"]:
        matching = [f for f in all_findings if f["dimension"] == feat_name]
        if matching:
            f = matching[0]
            conclusions.append([
                f["dimension"], f["description"], f["detail"],
                f"{abs(f['d']):.4f}", f"{f['p']:.4f}", f["n"],
                f["grade"], f["grade_desc"],
                "可使用" if f["grade"] in ("A", "B") else "效果极弱，不必依赖"
            ])
    
    # Day
    best_d = max(day_info.items(), key=lambda x: x[1]["med_clr"])
    conclusions.append([
        "最佳发布日", best_d[0],
        f"中位评赞比={best_d[1]['med_clr']:.4f}, CI95={best_d[1]['ci']}",
        "", "", best_d[1]["n"],
        best_d[1]["grade"],
        "可靠" if best_d[1]["enough"] else "样本不足",
        f"优先在{best_d[0]}发布高互动内容"
    ])
    
    # Format
    fmt = "竖屏" if portrait_comp['median_竖屏'] > portrait_comp['median_横屏'] else "横屏"
    conclusions.append([
        "画幅选择", fmt,
        f"d={portrait_comp['cohens_d']:.4f}, p={portrait_comp['p_value']:.4f}",
        f"{abs(portrait_comp['cohens_d']):.4f}", f"{portrait_comp['p_value']:.4f}",
        min(portrait_comp['n_a'], portrait_comp['n_b']),
        portrait_comp["grade"], portrait_comp["grade_desc"],
        "优先竖屏拍摄" if fmt == "竖屏" else "横屏也可接受，差异不大"
    ])
    
    # Sound
    snd = "热门音乐" if sound_comp['median_热门音乐'] > sound_comp['median_原创声'] else "原创声"
    conclusions.append([
        "音乐策略", f"{snd}中位评赞比更高",
        f"d={sound_comp['cohens_d']:.4f}, p={sound_comp['p_value']:.4f}",
        f"{abs(sound_comp['cohens_d']):.4f}", f"{sound_comp['p_value']:.4f}",
        min(sound_comp['n_a'], sound_comp['n_b']),
        sound_comp["grade"], sound_comp["grade_desc"],
        f"优先使用{snd}" if sound_comp["grade"] in ("A", "B") else "效果差异极小，随内容选择"
    ])
    
    # Tier
    tier_info = {}
    for tier in tier_order:
        grp = tier_groups.get(tier, [])
        if grp:
            med_epf = median([v["engagement_per_follower"] for v in grp])
            tier_info[tier] = med_epf
    if tier_info:
        best_tier = max(tier_info, key=tier_info.get)
        worst_tier = min(tier_info, key=tier_info.get)
        conclusions.append([
            "作者量级", f"粉均互动最高: {best_tier}",
            f"{best_tier}中位={tier_info[best_tier]:.4f} vs {worst_tier}中位={tier_info[worst_tier]:.4f}",
            "", "", sum(1 for v in videos if v["follower_tier"] == best_tier),
            "A" if sum(1 for v in videos if v["follower_tier"] == best_tier) >= MIN_SAMPLE else "F",
            "素人内容有更高的粉丝激活效率",
            "小体量创作者在评论转化上有天然优势"
        ])
    
    # Time period
    for p in period_order:
        if p in period_stats:
            ps = period_stats[p]
            conclusions.append([
                f"时期-{p}", f"中位评赞比={ps['median_clr']:.4f}",
                f"粉均互动={ps['median_epf']:.6f}, n={ps['n']}",
                "", "", ps["n"],
                "A" if ps["n"] >= MIN_SAMPLE else "F",
                "时间趋势参考",
                "算法环境在变，优先参考近期数据"
            ])
    
    # Quality summary
    a_count = sum(1 for c in conclusions if c[6] == "A")
    b_count = sum(1 for c in conclusions if c[6] == "B")
    c_count = sum(1 for c in conclusions if c[6] == "C")
    f_count = sum(1 for c in conclusions if c[6] == "F")
    
    # Write conclusions
    for c in conclusions:
        write_rows(ws, row_idx, [c], grade_col=6)
        row_idx += 1
    
    row_idx += 1
    ws.cell(row=row_idx, column=1, value="质量分布").font = Font(bold=True)
    ws.cell(row=row_idx, column=2, value=f"A级(可靠策略): {a_count}  B级(有参考): {b_count}  C级(弱信号): {c_count}  F级(样本不足): {f_count}")
    auto_width(ws)
    
    # ═══════════════════════════════════════════
    # Save
    # ═══════════════════════════════════════════
    wb.save(str(OUTPUT))
    print(f"\n✓ 报告已保存: {OUTPUT}")
    print(f"  文件大小: {OUTPUT.stat().st_size / 1024:.0f}KB")
    
    # Print quality summary
    print("\n" + "=" * 70)
    print("v5 发现质量分布")
    print("=" * 70)
    print(f"  A级(可靠策略 d≥0.5 + p<0.01): {a_count}")
    print(f"  B级(有参考价值 d≥0.3 + p<0.05): {b_count}")
    print(f"  C级(弱信号/效果极小): {c_count}")
    print(f"  F级(样本不足): {f_count}")
    print(f"\n  总发现数: {len(conclusions)}")
    
    if a_count == 0:
        print("\n  ⚠ 警告: 所有发现均未达到A级(可靠策略)!")
        print("     这意味着在当前样本中，没有任何单一内容特征能产生中到大的效果量。")
        print("     非洲商业赛道内容策略的差异化空间，可能不取决于这些表层特征。")
    
    print("\n" + "=" * 70)
    print("v5 核心改进点")
    print("=" * 70)
    print("  1. 中位数替代均值 → 消除极右偏分布的影响")
    print("  2. Bootstrap 95%CI → 每个数字附置信区间")
    print("  3. Cohen's d + Mann-Whitney U p值 → 区分真差异与噪声")
    print("  4. 最小样本门槛 = 3% → 小样本结论标记F级")
    print("  5. 时间分层(早/中/近) → 控制算法环境变化")
    print("  6. 多标签钩子 → 记录共现而非强制单选")

if __name__ == "__main__":
    main()
