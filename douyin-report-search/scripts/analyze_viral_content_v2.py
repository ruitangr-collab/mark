#!/usr/bin/env python3
"""
A1 爆款内容深度分析 v2
在 v1 基础上增加:
  - 标题钩子模式 (疑问/数字/警告/如何/对比/情绪词)
  - 标签组合分析 (哪些标签组合最容易爆)
  - 作者持续性 (爆款是偶然还是持续)
  - 发布时间分析 (哪天/哪个时段最容易爆)
  - 相关性矩阵 (时长/标签数/标题长 vs 互动)
  - 评论数 vs 其他指标的关系
输出: 抖音爆款内容深度分析v2.xlsx
"""

import json
import re
import sys
import math
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SKILL_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
DATA_DIR = SKILL_DIR / "country_data"
OUTPUT = SKILL_DIR / "抖音爆款内容深度分析v2.xlsx"

def log(s):
    sys.stdout.buffer.write((s + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()

# ── Title hook patterns ──
HOOK_PATTERNS = {
    "疑问句": [r"\？", r"\?", "吗", "呢", "吧", "怎么样", "如何", "怎么"],
    "数字罗列": [r"\d+个", r"\d+种", r"\d+万", r"\d+年", r"第\d", r"TOP\d", r"Top\d"],
    "警告避坑": ["坑", "避坑", "注意", "千万别", "警惕", "骗局", "血亏", "亏了", "踩雷"],
    "如何教你": ["如何", "怎么", "教你", "手把手", "秘籍", "干货", "攻略"],
    "对比反差": ["还是", "vs", "VS", "对比", "没想到", "居然", "其实"],
    "情绪强烈": ["暴利", "赚翻", "血赚", "崩溃", "太难了", "绝了", "炸了", "必看"],
    "稀缺独家": ["独家", "第一次", "罕见", "揭秘", "内幕", "真相", "只有"],
    "时间紧迫": ["最新", "刚刚", "今天", "昨天", "紧急"],
}

def detect_hooks(desc):
    matched = []
    for hook, keywords in HOOK_PATTERNS.items():
        if any(re.search(kw, desc) for kw in keywords):
            matched.append(hook)
    return matched

# ── Load all data (same as v1) ──
log("Loading all data...")
all_videos = []
author_videos = defaultdict(list)

TYPE_PATTERNS = {
    "干货知识": ["如何", "怎么", "技巧", "方法", "教程", "干货", "避坑", "攻略", "指南"],
    "故事Vlog": ["vlog", "Vlog", "记录", "日常", "我的", "今天", "旅行", "生活"],
    "新闻资讯": ["最新", "突发", "新闻", "宣布", "正式", "签约", "投资"],
    "产品展示": ["工厂", "产品", "源头", "批发", "价格", "质量", "车间"],
    "观点口播": ["为什么", "我认为", "说实话", "很多人不知道", "分析", "解读"],
    "招聘求职": ["招聘", "求职", "找工作", "招人", "待遇", "工资"],
}

def classify_content(desc, tags):
    text = desc + " " + " ".join(tags)
    scores = {}
    for ctype, kws in TYPE_PATTERNS.items():
        score = sum(1 for kw in kws if kw in text)
        if score > 0:
            scores[ctype] = score
    return max(scores, key=scores.get) if scores else "其他"

for fpath in sorted(DATA_DIR.glob("*.json")):
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        country = data.get("country", "Unknown")
        keyword = data.get("keyword", "Unknown")
        for v in data.get("videos", []):
            raw = v.get("_raw") or {}
            vid_info = raw.get("video") or {}
            duration_ms = vid_info.get("duration", 0) or 0
            duration_sec = duration_ms / 1000 if duration_ms else 0

            tags = []
            for te in (raw.get("text_extra") or []):
                if isinstance(te, dict) and te.get("hashtag_name"):
                    tags.append(te["hashtag_name"])

            stats = v.get("statistics", {})
            digg = stats.get("digg_count", 0) or 0
            comment = stats.get("comment_count", 0) or 0
            share = stats.get("share_count", 0) or 0
            collect = stats.get("collect_count", 0) or 0
            engagement = digg + comment * 3 + share * 5 + collect * 2

            author = v.get("author", {})
            desc = v.get("desc", "") or raw.get("desc", "") or ""
            create_time = v.get("create_time", 0) or 0

            hooks = detect_hooks(desc)
            content_type = classify_content(desc, tags)

            # Tag combination (sorted tuple for dedup)
            tag_combo = tuple(sorted(tags))

            record = {
                "country": country,
                "keyword": keyword,
                "aweme_id": v.get("aweme_id", ""),
                "desc": desc,
                "tags": tags,
                "tag_combo": tag_combo,
                "tag_count": len(tags),
                "duration_sec": round(duration_sec, 1),
                "digg": digg,
                "comment": comment,
                "share": share,
                "collect": collect,
                "engagement": engagement,
                "author_nickname": author.get("nickname", ""),
                "author_uid": author.get("uid", ""),
                "content_type": content_type,
                "desc_len": len(desc),
                "create_time": create_time,
                "hooks": hooks,
                "hook_count": len(hooks),
            }
            all_videos.append(record)
            author_videos[author.get("uid", "")].append(record)
    except Exception as e:
        log(f"  SKIP {fpath.name}: {e}")

total = len(all_videos)
log(f"Loaded {total} videos, {len(author_videos)} authors")

# ── Sort & define viral ──
all_videos.sort(key=lambda x: x["engagement"], reverse=True)
viral_cutoff = max(1, total // 10)
viral = all_videos[:viral_cutoff]
viral_ids = set(v["aweme_id"] for v in viral)

def is_viral(rec):
    return rec["aweme_id"] in viral_ids

# ── Helpers ──
def avg(lst):
    return round(sum(lst) / len(lst), 2) if lst else 0

def pct(a, b):
    return round(a / b * 100, 1) if b else 0

def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x - mx)*(y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx)**2 for x in xs))
    dy = math.sqrt(sum((y - my)**2 for y in ys))
    return round(num / (dx * dy + 1e-9), 3)

# ── Excel styles ──
HEADER_FONT_W = Font(name="Microsoft YaHei", bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="4472C4")
NORMAL_FONT = Font(name="Microsoft YaHei", size=10)
WRAP = Alignment(vertical="center", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center")
THIN = Border(left=Side("thin"), right=Side("thin"), top=Side("thin"), bottom=Side("thin"))

def sh(ws, r, c, val=""):
    cell = ws.cell(row=r, column=c, value=val)
    cell.border = THIN
    return cell

def header_row(ws, r, headers):
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=r, column=i, value=h)
        cell.font = HEADER_FONT_W
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = THIN

def auto_width(ws, max_w=50):
    for col in ws.columns:
        mx = 0
        cl = get_column_letter(col[0].column)
        for cell in col:
            try:
                mx = max(mx, len(str(cell.value or "")))
            except: pass
        ws.column_dimensions[cl].width = min(mx + 3, max_w)

# ══════════════════════════════════════
# Workbook
# ══════════════════════════════════════
wb = openpyxl.Workbook()

# ── Sheet 1: 相关性矩阵 ──
log("Sheet1: 相关性矩阵...")
ws1 = wb.active
ws1.title = "相关性矩阵"

numeric_fields = ["duration_sec", "tag_count", "desc_len", "hook_count", "digg", "comment", "share", "collect", "engagement"]
fields_cn = {
    "duration_sec": "视频时长(秒)",
    "tag_count": "标签数量",
    "desc_len": "标题长度(字)",
    "hook_count": "钩子数量",
    "digg": "点赞数",
    "comment": "评论数",
    "share": "分享数",
    "collect": "收藏数",
    "engagement": "互动得分(加权)",
}

header_row(ws1, 1, [""] + [fields_cn[f] for f in numeric_fields])

# Compute correlations (all videos)
# Use log-transformed for highly skewed metrics
import statistics

def safe_corr(xs, ys):
    # Use rank correlation (Spearman) - more robust
    n = len(xs)
    if n < 3:
        return 0
    # Rank transform
    def rank(lst):
        s = sorted((v, i) for i, v in enumerate(lst))
        r = [0]*n
        cur = 1
        for j in range(n):
            if j > 0 and s[j][0] == s[j-1][0]:
                r[s[j][1]] = r[s[j-1][1]]
            else:
                r[s[j][1]] = cur
                cur += 1
        return r
    rx = rank(xs)
    ry = rank(ys)
    return round(pearson(rx, ry), 3)

all_x = {f: [v[f] for v in all_videos if v[f] is not None] for f in numeric_fields}

for i, f1 in enumerate(numeric_fields):
    row = i + 2
    sh(ws1, row, 1, fields_cn[f1]).font = Font(name="Microsoft YaHei", bold=True, size=10)
    for j, f2 in enumerate(numeric_fields):
        val = safe_corr(all_x[f1], all_x[f2])
        cell = sh(ws1, row, j + 2, val)
        cell.alignment = CENTER
        # Color: strong positive=green, strong negative=red
        if val >= 0.3:
            cell.fill = PatternFill("solid", fgColor="C6EFCE")
        elif val <= -0.3:
            cell.fill = PatternFill("solid", fgColor="FFCCCC")
        elif abs(val) >= 0.15:
            cell.fill = PatternFill("solid", fgColor="E2EFDA")

auto_width(ws1, 25)

# ── Sheet 2: 标题钩子分析 ──
log("Sheet2: 标题钩子分析...")
ws2 = wb.create_sheet("标题钩子分析")

hook_stats = {}
for hook_name in HOOK_PATTERNS:
    viral_with = [v for v in viral if hook_name in v["hooks"]]
    normal_with = [v for v in all_videos if hook_name in v["hooks"] and not is_viral(v)]
    total_with = len(viral_with) + len(normal_with)
    
    hook_stats[hook_name] = {
        "viral_count": len(viral_with),
        "normal_count": len(normal_with),
        "total": total_with,
        "viral_rate": pct(len(viral_with), total_with) if total_with else 0,
        "avg_eng": avg([v["engagement"] for v in ([vv for vv in all_videos if hook_name in vv["hooks"]])]),
    }

header_row(ws2, 1, ["钩子类型", "爆款数", "普通数", "总出现", "爆款率(%)", "平均互动", "判断"])
sorted_hooks = sorted(hook_stats.items(), key=lambda x: x[1]["viral_rate"], reverse=True)
for i, (name, st) in enumerate(sorted_hooks):
    r = i + 2
    judgment = "强力钩子" if st["viral_rate"] >= 15 else ("有效钩子" if st["viral_rate"] >= 10 else ("弱效" if st["viral_rate"] >= 5 else "无效"))
    vals = [name, st["viral_count"], st["normal_count"], st["total"], st["viral_rate"], st["avg_eng"], judgment]
    for j, val in enumerate(vals):
        cell = sh(ws2, r, j + 1, val)
        cell.alignment = CENTER if j > 0 else Alignment(vertical="center")

auto_width(ws2)

# ── Sheet 3: 钩子组合分析 (multi-hook titles) ──
log("Sheet3: 钩子数量分析...")
ws3 = wb.create_sheet("钩子数量分析")

header_row(ws3, 1, ["钩子数量", "视频数", "爆款数", "爆款率(%)", "平均互动", "典型标题举例"])
for hook_cnt in range(0, 5):
    r = hook_cnt + 2
    in_range = [v for v in all_videos if v["hook_count"] == hook_cnt]
    in_viral = [v for v in in_range if is_viral(v)]
    example = in_range[0]["desc"][:50] if in_range else ""
    vals = [hook_cnt, len(in_range), len(in_viral), pct(len(in_viral), len(in_range)) if in_range else 0,
             avg([v["engagement"] for v in in_range]), example]
    for j, val in enumerate(vals):
        cell = sh(ws3, r, j + 1, val)
        cell.alignment = CENTER if j < 5 else WRAP
auto_width(ws3)
ws3.column_dimensions["F"].width = 50

# ── Sheet 4: 标签组合分析 ──
log("Sheet4: 标签组合分析...")
ws4 = wb.create_sheet("标签组合分析")

# Count combo frequencies in viral vs all
combo_counter = Counter()
combo_viral = Counter()
for v in all_videos:
    combo = v["tag_combo"]
    combo_counter[combo] += 1
    if is_viral(v):
        combo_viral[combo] += 1

# Filter: at least 2 tags, appears 3+ times
combo_results = []
for combo, cnt in combo_counter.items():
    if cnt < 3 or len(combo) < 2:
        continue
    vc = combo_viral.get(combo, 0)
    combo_results.append({
        "tags": " + ".join(combo[:4]),
        "count": cnt,
        "viral_count": vc,
        "viral_rate": pct(vc, cnt),
    })

combo_results.sort(key=lambda x: x["viral_rate"], reverse=True)

header_row(ws4, 1, ["排名", "标签组合", "出现次数", "爆款数", "爆款率(%)"])
for i, cr in enumerate(combo_results[:50]):
    r = i + 2
    for j, val in enumerate([i + 1, cr["tags"], cr["count"], cr["viral_count"], cr["viral_rate"]]):
        cell = sh(ws4, r, j + 1, val)
        cell.alignment = CENTER if j != 1 else WRAP
auto_width(ws4)
ws4.column_dimensions["B"].width = 40

# ── Sheet 5: 作者持续性分析 ──
log("Sheet5: 作者持续性分析...")
ws5 = wb.create_sheet("作者持续性分析")

author_stats = []
for uid, videos in author_videos.items():
    if not uid:
        continue
    viral_in = [v for v in videos if is_viral(v)]
    author_name = videos[0]["author_nickname"]
    total_eng = sum(v["engagement"] for v in videos)
    author_stats.append({
        "uid": uid,
        "name": author_name,
        "total_videos": len(videos),
        "viral_count": len(viral_in),
        "viral_rate": pct(len(viral_in), len(videos)),
        "avg_engagement": avg([v["engagement"] for v in videos]),
        "max_engagement": max(v["engagement"] for v in videos),
    })

# Sort by viral_count desc
author_stats.sort(key=lambda x: x["viral_count"], reverse=True)

header_row(ws5, 1, ["排名", "作者", "总视频数", "爆款数", "爆款率(%)", "平均互动", "最高互动", "持续性判断"])
for i, a in enumerate(author_stats[:80]):
    r = i + 2
    if a["viral_count"] >= 3:
        judgment = "持续爆款作者"
    elif a["viral_count"] >= 1:
        judgment = "偶尔爆款"
    else:
        judgment = "未出爆款"
    vals = [i + 1, a["name"], a["total_videos"], a["viral_count"],
             a["viral_rate"], a["avg_engagement"], a["max_engagement"], judgment]
    for j, val in enumerate(vals):
        cell = sh(ws5, r, j + 1, val)
        cell.alignment = CENTER if j != 1 else Alignment(vertical="center")
auto_width(ws5)

# ── Sheet 6: 发布时间分析 ──
log("Sheet6: 发布时间分析...")
ws6 = wb.create_sheet("发布时间分析")

# Convert create_time to weekday/hour
weekday_cnt = [0]*7   # 0=Mon
weekday_viral = [0]*7
hour_cnt = [0]*24
hour_viral = [0]*24

for v in all_videos:
    ct = v.get("create_time", 0)
    if not ct:
        continue
    try:
        dt = datetime.fromtimestamp(ct)
        wd = dt.weekday()  # 0=Mon
        h = dt.hour
        weekday_cnt[wd] += 1
        hour_cnt[h] += 1
        if is_viral(v):
            weekday_viral[wd] += 1
            hour_viral[h] += 1
    except:
        pass

weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

header_row(ws6, 1, ["时间段", "视频数", "爆款数", "爆款率(%)", "判断"])
for wd in range(7):
    r = wd + 2
    vr = pct(weekday_viral[wd], weekday_cnt[wd]) if weekday_cnt[wd] else 0
    judgment = "高爆款率" if vr >= 12 else ("中等" if vr >= 8 else "低")
    vals = [weekday_names[wd], weekday_cnt[wd], weekday_viral[wd], vr, judgment]
    for j, val in enumerate(vals):
        cell = sh(ws6, r, j + 1, val)
        cell.alignment = CENTER
auto_width(ws6)

# Hour analysis (grouped by 4-hour blocks)
hour_blocks = [
    (0, 4, "凌晨 0-4点"),
    (4, 8, "清晨 4-8点"),
    (8, 12, "上午 8-12点"),
    (12, 16, "下午 12-16点"),
    (16, 20, "傍晚 16-20点"),
    (20, 24, "晚上 20-24点"),
]
ws6_hour = wb.create_sheet("发布时段分析")
header_row(ws6_hour, 1, ["时段", "视频数", "爆款数", "爆款率(%)", "判断"])
for i, (lo, hi, label) in enumerate(hour_blocks):
    r = i + 2
    cnt = sum(hour_cnt[lo:hi])
    vc = sum(hour_viral[lo:hi])
    vr = pct(vc, cnt) if cnt else 0
    judgment = "黄金时段" if vr >= 12 else ("良好" if vr >= 8 else "一般")
    vals = [label, cnt, vc, vr, judgment]
    for j, val in enumerate(vals):
        cell = sh(ws6_hour, r, j + 1, val)
        cell.alignment = CENTER
auto_width(ws6_hour)

# ── Sheet 7: 评论 vs 点赞 关系分析 ──
log("Sheet7: 评论/点赞/分享关系...")
ws7 = wb.create_sheet("评论互动深度分析")

# Categorize videos by comment/digg ratio
ratio_data = []
for v in all_videos:
    if v["digg"] > 0:
        ratio = v["comment"] / v["digg"] * 100  # comment rate
        ratio_data.append({
            "video": v,
            "ratio": ratio,
            "digg": v["digg"],
            "comment": v["comment"],
            "share": v["share"],
        })

ratio_data.sort(key=lambda x: x["ratio"], reverse=True)

header_row(ws7, 1, ["排名", "作者", "标题", "点赞", "评论", "评论率(%)", "分享", "是否爆款", "内容类型"])
for i, rd in enumerate(ratio_data[:100]):
    v = rd["video"]
    r = i + 2
    vals = [i + 1, v["author_nickname"], v["desc"][:50], v["digg"], v["comment"],
             round(rd["ratio"], 2), v["share"], "是" if is_viral(v) else "否", v["content_type"]]
    for j, val in enumerate(vals):
        cell = sh(ws7, r, j + 1, val)
        cell.alignment = CENTER if j in [0,3,4,5,6,7] else WRAP
auto_width(ws7)
ws7.column_dimensions["C"].width = 45

# ── Sheet 8: 深度结论汇总 ──
log("Sheet8: 深度结论汇总...")
ws8 = wb.create_sheet("深度结论汇总")

conclusions = [
    ("数据规模", f"共分析 {total} 条视频，{len(author_videos)} 位作者，爆款定义为 TOP 10%（{viral_cutoff}条）"),
    ("", ""),
    ("=== 相关性发现 ===", ""),
    ("互动得分与点赞数", f"相关系数待计算（见相关性矩阵Sheet）"),
    ("标题长度与互动", f"最佳区间待确认（见标题长度Sheet）"),
    ("标签数量与互动", f"最佳数量待确认"),
    ("", ""),
    ("=== 标题钩子发现 ===", ""),
]

# Fill in actual correlation values
corr_comment_eng = safe_corr(all_x["comment"], all_x["engagement"])
corr_share_eng = safe_corr(all_x["share"], all_x["engagement"])
corr_tag_eng = safe_corr(all_x["tag_count"], all_x["engagement"])
corr_len_eng = safe_corr(all_x["desc_len"], all_x["engagement"])
corr_dur_eng = safe_corr(all_x["duration_sec"], all_x["engagement"])

conclusions.append(("评论数 vs 互动得分", f"Spearman相关系数 = {corr_comment_eng}（越强说明评论价值越高）"))
conclusions.append(("分享数 vs 互动得分", f"Spearman相关系数 = {corr_share_eng}"))
conclusions.append(("标签数量 vs 互动得分", f"Spearman相关系数 = {corr_tag_eng}"))
conclusions.append(("标题长度 vs 互动得分", f"Spearman相关系数 = {corr_len_eng}"))
conclusions.append(("视频时长 vs 互动得分", f"Spearman相关系数 = {corr_dur_eng}"))
conclusions.append(("", ""))

# Top hooks
top_hooks = sorted(hook_stats.items(), key=lambda x: x[1]["viral_rate"], reverse=True)[:3]
conclusions.append(("=== 最强标题钩子 ===", ""))
for name, st in top_hooks:
    conclusions.append((f"钩子: {name}", f"爆款率 {st['viral_rate']}%，出现 {st['total']} 次"))

conclusions.append(("", ""))

# Weekday best
best_wd = max(range(7), key=lambda w: pct(weekday_viral[w], weekday_cnt[w]) if weekday_cnt[w] else 0)
conclusions.append(("=== 最佳发布日 ===", f"{weekday_names[best_wd]}（爆款率 {pct(weekday_viral[best_wd], weekday_cnt[best_wd])}%）"))

# Hour best
best_hour_block = max(hour_blocks, key=lambda b: pct(sum(hour_viral[b[0]:b[1]]), sum(hour_cnt[b[0]:b[1]])) if sum(hour_cnt[b[0]:b[1]]) else 0)
conclusions.append(("=== 最佳发布时段 ===", f"{best_hour_block[2]}"))

# Author insights
multi_viral = [a for a in author_stats if a["viral_count"] >= 2]
conclusions.append(("", ""))
conclusions.append(("=== 作者持续性 ===", f"有 {len(multi_viral)} 位作者产出过 2+ 条爆款（持续爆款作者）"))

header_row(ws8, 1, ["维度", "结论与建议"])
for i, (dim, conc) in enumerate(conclusions):
    r = i + 2
    cell_dim = sh(ws8, r, 1, dim)
    cell_dim.font = Font(name="Microsoft YaHei", bold=(dim.startswith("===")), size=10)
    cell_dim.alignment = Alignment(vertical="center", wrap_text=True)
    cell_conc = sh(ws8, r, 2, conc)
    cell_conc.alignment = Alignment(vertical="center", wrap_text=True)
    ws8.row_dimensions[r].height = 30 if dim else 15

ws8.column_dimensions["A"].width = 25
ws8.column_dimensions["B"].width = 60

# ── Save ──
log(f"Saving to {OUTPUT}...")
wb.save(str(OUTPUT))
log(f"Done!")

# ── Print key findings ──
log(f"\n{'='*50}")
log(f"深度分析完成")
log(f"{'='*50}")
log(f"相关性 (Spearman):")
log(f"  评论数 vs 互动: {corr_comment_eng}")
log(f"  分享数 vs 互动: {corr_share_eng}")
log(f"  标签数 vs 互动: {corr_tag_eng}")
log(f"  标题长 vs 互动: {corr_len_eng}")
log(f"  时长 vs 互动:    {corr_dur_eng}")
log(f"\n最强钩子: {', '.join(n for n,s in top_hooks[:3])}")
log(f"最佳发布日: {weekday_names[best_wd]}")
log(f"持续爆款作者: {len(multi_viral)} 位")
