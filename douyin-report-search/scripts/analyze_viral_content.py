#!/usr/bin/env python3
"""
A1 爆款内容拆解
从 20国 采集数据中分析高互动视频的规律:
  - 标题模式 (长度/用词/结构)
  - 标签策略 (哪些标签最热门)
  - 时长分布 (多长的视频最受欢迎)
  - 内容类型 (干货/故事/资讯/产品/口播)
  - 作者集中度
输出: 抖音爆款内容分析报告.xlsx
"""

import json
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Paths ──
SKILL_DIR = Path(r"C:/Users/53185/.workbuddy/skills/douyin-report-search")
DATA_DIR = SKILL_DIR / "country_data"
OUTPUT = SKILL_DIR / "抖音爆款内容分析报告.xlsx"

def log(s):
    sys.stdout.buffer.write((s + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()

# ── Content type classifier ──
TYPE_PATTERNS = {
    "干货知识": ["如何", "怎么", "技巧", "方法", "教程", "干货", "避坑", "攻略", "指南", "注意", "必须知道", "一定要", "千万别", "经验", "分享经验"],
    "故事Vlog": ["vlog", "Vlog", "记录", "日常", "我的", "今天", "旅行", "生活", "见闻", "实拍", "街拍"],
    "新闻资讯": ["最新", "突发", "新闻", "宣布", "正式", "签约", "合作", "投资", "开工", "竣工", "开通", "启用"],
    "产品展示": ["工厂", "产品", "源头", "批发", "价格", "质量", "样品", "出货", "装箱", "发货", "现货", "车间", "生产线"],
    "观点口播": ["为什么", "我认为", "说实话", "很多人不知道", "聊一聊", "谈谈", "分析", "解读", "深度"],
    "招聘求职": ["招聘", "求职", "找工作", "招人", "待遇", "工资", "年薪", "包吃住"],
}

def classify_content(desc, tags):
    text = desc + " " + " ".join(tags)
    scores = {}
    for ctype, keywords in TYPE_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[ctype] = score
    if not scores:
        return "其他"
    return max(scores, key=scores.get)

# ── Load all data ──
log("Loading all country data...")
all_videos = []
stats_by_country = defaultdict(lambda: {"total": 0, "sum_engagement": 0, "videos": []})

for fpath in sorted(DATA_DIR.glob("*.json")):
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        country = data.get("country", "Unknown")
        keyword = data.get("keyword", "Unknown")
        for v in data.get("videos", []):
            raw = v.get("_raw") or {}
            # Duration
            vid_info = raw.get("video") or {}
            duration_ms = vid_info.get("duration", 0) or 0
            duration_sec = duration_ms / 1000 if duration_ms else 0

            # Tags from text_extra
            tags = []
            for te in (raw.get("text_extra") or []):
                if isinstance(te, dict) and te.get("hashtag_name"):
                    tags.append(te["hashtag_name"])

            stats = v.get("statistics", {})
            digg = stats.get("digg_count", 0) or 0
            comment = stats.get("comment_count", 0) or 0
            share = stats.get("share_count", 0) or 0
            collect = stats.get("collect_count", 0) or 0
            engagement = digg + comment * 3 + share * 5 + collect * 2  # weighted engagement

            author = v.get("author", {})
            desc = v.get("desc", "") or raw.get("desc", "") or ""

            content_type = classify_content(desc, tags)

            record = {
                "country": country,
                "keyword": keyword,
                "aweme_id": v.get("aweme_id", ""),
                "desc": desc,
                "tags": tags,
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
                "create_time": v.get("create_time", 0),
            }
            all_videos.append(record)
            stats_by_country[country]["total"] += 1
            stats_by_country[country]["sum_engagement"] += engagement
    except Exception as e:
        log(f"  SKIP {fpath.name}: {e}")

log(f"Loaded {len(all_videos)} videos from {len(stats_by_country)} countries")

# ── Sort and classify ──
all_videos.sort(key=lambda x: x["engagement"], reverse=True)
total = len(all_videos)

# Viral threshold: top 10% by engagement
viral_cutoff = max(1, total // 10)
viral = all_videos[:viral_cutoff]
normal = all_videos[viral_cutoff:]

log(f"Viral (top 10%): {len(viral)} videos (engagement >= {viral[-1]['engagement']})")
log(f"Normal: {len(normal)} videos")

# ── Helper for stats ──
def avg(lst):
    return round(sum(lst) / len(lst), 1) if lst else 0

def median(lst):
    s = sorted(lst)
    n = len(s)
    if n == 0:
        return 0
    if n % 2 == 1:
        return s[n // 2]
    return round((s[n // 2 - 1] + s[n // 2]) / 2, 1)

def pct(a, b):
    return round(a / b * 100, 1) if b else 0

# ── Create workbook ──
wb = openpyxl.Workbook()
HEADER_FONT = Font(name="Microsoft YaHei", bold=True, size=11)
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT_W = Font(name="Microsoft YaHei", bold=True, size=11, color="FFFFFF")
TITLE_FONT = Font(name="Microsoft YaHei", bold=True, size=14)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)
CENTER = Alignment(horizontal="center", vertical="center")
WRAP = Alignment(vertical="center", wrap_text=True)

def style_header(ws, row, cols):
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT_W
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = THIN_BORDER

def style_data(ws, start_row, end_row, cols):
    for r in range(start_row, end_row + 1):
        for c in range(1, cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = THIN_BORDER
            cell.alignment = Alignment(vertical="center")

def auto_width(ws, max_width=50):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                val = str(cell.value or "")
                max_len = max(max_len, len(val))
            except:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, max_width)

# ═══════════════════════════════════════════════════════
# Sheet 1: 爆款 vs 普通 对比总览
# ═══════════════════════════════════════════════════════
log("Building Sheet 1: Viral vs Normal comparison...")
ws1 = wb.active
ws1.title = "爆款vs普通对比"

# Title row
ws1.merge_cells("A1:I1")
ws1.cell(row=1, column=1, value="抖音非洲内容 - 爆款 vs 普通视频对比分析").font = TITLE_FONT

headers = ["指标", "爆款视频(Top10%)", "普通视频(Bottom90%)", "差异", "解读"]
for i, h in enumerate(headers, 1):
    ws1.cell(row=3, column=i, value=h)
style_header(ws1, 3, 5)

def vs_row(ws, r, metric, v_val, n_val, note=""):
    if isinstance(v_val, float) and isinstance(n_val, float) and n_val > 0:
        diff = round((v_val - n_val) / n_val * 100, 1)
        diff_str = f"+{diff}%" if diff > 0 else f"{diff}%"
    else:
        diff_str = "-"
    ws.cell(row=r, column=1, value=metric).border = THIN_BORDER
    ws.cell(row=r, column=2, value=str(v_val)).border = THIN_BORDER
    ws.cell(row=r, column=3, value=str(n_val)).border = THIN_BORDER
    ws.cell(row=r, column=4, value=diff_str).border = THIN_BORDER
    ws.cell(row=r, column=5, value=note).border = THIN_BORDER

row = 4
vs_row(ws1, row, "视频数量", len(viral), len(normal), f"爆款占{pct(len(viral), total)}%"); row += 1

viral_eng = [v["engagement"] for v in viral]
normal_eng = [v["engagement"] for v in normal]
vs_row(ws1, row, "平均互动(加权)", avg(viral_eng), avg(normal_eng), "爆款互动是普通视频的倍数"); row += 1

viral_likes = [v["digg"] for v in viral]
normal_likes = [v["digg"] for v in normal]
vs_row(ws1, row, "平均点赞", avg(viral_likes), avg(normal_likes)); row += 1

viral_cmt = [v["comment"] for v in viral]
normal_cmt = [v["comment"] for v in normal]
vs_row(ws1, row, "平均评论", avg(viral_cmt), avg(normal_cmt), "评论是高价值互动信号"); row += 1

viral_share = [v["share"] for v in viral]
normal_share = [v["share"] for v in normal]
vs_row(ws1, row, "平均分享", avg(viral_share), avg(normal_share)); row += 1

viral_coll = [v["collect"] for v in viral]
normal_coll = [v["collect"] for v in normal]
vs_row(ws1, row, "平均收藏", avg(viral_coll), avg(normal_coll)); row += 1

viral_len = [v["desc_len"] for v in viral]
normal_len = [v["desc_len"] for v in normal]
vs_row(ws1, row, "平均标题长度(字)", avg(viral_len), avg(normal_len), "标题长短与爆款的关系"); row += 1

viral_tags = [v["tag_count"] for v in viral]
normal_tags = [v["tag_count"] for v in normal]
vs_row(ws1, row, "平均标签数", avg(viral_tags), avg(normal_tags), "标签数量与爆款的关系"); row += 1

viral_dur = [v["duration_sec"] for v in viral if v["duration_sec"] > 0]
normal_dur = [v["duration_sec"] for v in normal if v["duration_sec"] > 0]
vs_row(ws1, row, "平均时长(秒)", avg(viral_dur), avg(normal_dur), "视频最佳时长的提示"); row += 1

style_data(ws1, 4, row - 1, 5)
auto_width(ws1)
ws1.column_dimensions["E"].width = 40

# ═══════════════════════════════════════════════════════
# Sheet 2: 时长分布分析
# ═══════════════════════════════════════════════════════
log("Building Sheet 2: Duration distribution...")
ws2 = wb.create_sheet("时长分布")

duration_buckets = [
    (0, 15, "0-15秒"),
    (15, 30, "15-30秒"),
    (30, 60, "30-60秒"),
    (60, 120, "1-2分钟"),
    (120, 300, "2-5分钟"),
    (300, 600, "5-10分钟"),
    (600, 99999, "10分钟+"),
]

headers2 = ["时长区间", "视频数", "占比(%)", "爆款数", "爆款率(%)", "平均点赞", "平均评论", "平均分享", "平均收藏", "平均互动"]
for i, h in enumerate(headers2, 1):
    ws2.cell(row=1, column=i, value=h)
style_header(ws2, 1, 10)

bucket_data = []
for lo, hi, label in duration_buckets:
    in_range = [v for v in all_videos if lo <= v["duration_sec"] < hi]
    viral_in = [v for v in in_range if v in viral]
    bucket_data.append({
        "label": label,
        "count": len(in_range),
        "pct": pct(len(in_range), total),
        "viral_count": len(viral_in),
        "viral_rate": pct(len(viral_in), len(in_range)) if in_range else 0,
        "avg_digg": avg([v["digg"] for v in in_range]),
        "avg_comment": avg([v["comment"] for v in in_range]),
        "avg_share": avg([v["share"] for v in in_range]),
        "avg_collect": avg([v["collect"] for v in in_range]),
        "avg_eng": avg([v["engagement"] for v in in_range]),
    })

for i, bd in enumerate(bucket_data):
    r = i + 2
    vals = [bd["label"], bd["count"], bd["pct"], bd["viral_count"], bd["viral_rate"],
            bd["avg_digg"], bd["avg_comment"], bd["avg_share"], bd["avg_collect"], bd["avg_eng"]]
    for j, val in enumerate(vals):
        ws2.cell(row=r, column=j + 1, value=val)
style_data(ws2, 2, len(bucket_data) + 1, 10)
auto_width(ws2)

# ═══════════════════════════════════════════════════════
# Sheet 3: 内容类型分析
# ═══════════════════════════════════════════════════════
log("Building Sheet 3: Content type analysis...")
ws3 = wb.create_sheet("内容类型分析")

headers3 = ["内容类型", "视频数", "占比(%)", "爆款数", "爆款率(%)", "平均点赞", "平均评论", "平均分享", "平均收藏", "平均互动", "平均时长(秒)"]
for i, h in enumerate(headers3, 1):
    ws3.cell(row=1, column=i, value=h)
style_header(ws3, 1, 11)

type_data = []
for ctype in TYPE_PATTERNS:
    in_type = [v for v in all_videos if v["content_type"] == ctype]
    viral_in = [v for v in in_type if v in viral]
    type_data.append({
        "type": ctype,
        "count": len(in_type),
        "pct": pct(len(in_type), total),
        "viral_count": len(viral_in),
        "viral_rate": pct(len(viral_in), len(in_type)) if in_type else 0,
        "avg_digg": avg([v["digg"] for v in in_type]),
        "avg_comment": avg([v["comment"] for v in in_type]),
        "avg_share": avg([v["share"] for v in in_type]),
        "avg_collect": avg([v["collect"] for v in in_type]),
        "avg_eng": avg([v["engagement"] for v in in_type]),
        "avg_dur": avg([v["duration_sec"] for v in in_type if v["duration_sec"] > 0]),
    })

# Also include "其他"
in_other = [v for v in all_videos if v["content_type"] == "其他"]
viral_other = [v for v in in_other if v in viral]
type_data.append({
    "type": "其他",
    "count": len(in_other),
    "pct": pct(len(in_other), total),
    "viral_count": len(viral_other),
    "viral_rate": pct(len(viral_other), len(in_other)) if in_other else 0,
    "avg_digg": avg([v["digg"] for v in in_other]),
    "avg_comment": avg([v["comment"] for v in in_other]),
    "avg_share": avg([v["share"] for v in in_other]),
    "avg_collect": avg([v["collect"] for v in in_other]),
    "avg_eng": avg([v["engagement"] for v in in_other]),
    "avg_dur": avg([v["duration_sec"] for v in in_other if v["duration_sec"] > 0]),
})

type_data.sort(key=lambda x: x["count"], reverse=True)

for i, td in enumerate(type_data):
    r = i + 2
    vals = [td["type"], td["count"], td["pct"], td["viral_count"], td["viral_rate"],
            td["avg_digg"], td["avg_comment"], td["avg_share"], td["avg_collect"],
            td["avg_eng"], td["avg_dur"]]
    for j, val in enumerate(vals):
        ws3.cell(row=r, column=j + 1, value=val)
style_data(ws3, 2, len(type_data) + 1, 11)
auto_width(ws3)

# ═══════════════════════════════════════════════════════
# Sheet 4: 热门标签 TOP50
# ═══════════════════════════════════════════════════════
log("Building Sheet 4: Top tags...")
ws4 = wb.create_sheet("热门标签TOP50")

# Collect all tags
all_tags = Counter()
viral_tags_counter = Counter()
for v in all_videos:
    for t in v["tags"]:
        all_tags[t] += 1
        if v in viral:
            viral_tags_counter[t] += 1

headers4 = ["排名", "标签", "出现次数", "视频占比(%)", "爆款中出现次数", "爆款率(%)"]
for i, h in enumerate(headers4, 1):
    ws4.cell(row=1, column=i, value=h)
style_header(ws4, 1, 6)

for i, (tag, count) in enumerate(all_tags.most_common(50)):
    r = i + 2
    vc = viral_tags_counter.get(tag, 0)
    ws4.cell(row=r, column=1, value=i + 1)
    ws4.cell(row=r, column=2, value=tag)
    ws4.cell(row=r, column=3, value=count)
    ws4.cell(row=r, column=4, value=pct(count, total))
    ws4.cell(row=r, column=5, value=vc)
    ws4.cell(row=r, column=6, value=pct(vc, count))
style_data(ws4, 2, min(51, len(all_tags) + 1), 6)
auto_width(ws4)

# ═══════════════════════════════════════════════════════
# Sheet 5: 标题模式分析
# ═══════════════════════════════════════════════════════
log("Building Sheet 5: Title pattern analysis...")
ws5 = wb.create_sheet("标题模式分析")

# Common title words in viral vs normal
def extract_words(descs):
    words = Counter()
    for d in descs:
        # Extract 2-4 char Chinese words
        for w in re.findall(r"[\u4e00-\u9fff]{2,4}", d):
            words[w] += 1
    return words

viral_words = extract_words([v["desc"] for v in viral])
normal_words = extract_words([v["desc"] for v in normal])

# Compare
word_compare = []
for word, vc in viral_words.most_common(100):
    nc = normal_words.get(word, 0)
    v_rate = vc / len(viral) * 100
    n_rate = nc / len(normal) * 100 if normal else 0
    diff = v_rate - n_rate
    word_compare.append((word, vc, nc, round(v_rate, 1), round(n_rate, 1), round(diff, 1)))

word_compare.sort(key=lambda x: x[5], reverse=True)

headers5 = ["排名", "高频词", "爆款中出现", "普通中出现", "爆款频率(%)", "普通频率(%)", "差异(百分点)", "解读"]
for i, h in enumerate(headers5, 1):
    ws5.cell(row=1, column=i, value=h)
style_header(ws5, 1, 8)

for i, (word, vc, nc, vr, nr, diff) in enumerate(word_compare[:60]):
    r = i + 2
    note = "爆款偏爱词" if diff > 0.3 else ("普通词" if diff < -0.3 else "无差异")
    ws5.cell(row=r, column=1, value=i + 1)
    ws5.cell(row=r, column=2, value=word)
    ws5.cell(row=r, column=3, value=vc)
    ws5.cell(row=r, column=4, value=nc)
    ws5.cell(row=r, column=5, value=vr)
    ws5.cell(row=r, column=6, value=nr)
    ws5.cell(row=r, column=7, value=diff)
    ws5.cell(row=r, column=8, value=note)
style_data(ws5, 2, min(61, len(word_compare) + 1), 8)
auto_width(ws5)

# ═══════════════════════════════════════════════════════
# Sheet 6: 标题长度与互动关系
# ═══════════════════════════════════════════════════════
log("Building Sheet 6: Title length vs engagement...")
ws6 = wb.create_sheet("标题长度与互动")

len_buckets = [
    (0, 10, "极短(0-10字)"),
    (10, 20, "短(10-20字)"),
    (20, 30, "中(20-30字)"),
    (30, 50, "长(30-50字)"),
    (50, 80, "超长(50-80字)"),
    (80, 9999, "超长(80字+)"),
]

headers6 = ["标题长度区间", "视频数", "占比(%)", "爆款数", "爆款率(%)", "平均点赞", "平均评论", "平均互动"]
for i, h in enumerate(headers6, 1):
    ws6.cell(row=1, column=i, value=h)
style_header(ws6, 1, 8)

for i, (lo, hi, label) in enumerate(len_buckets):
    r = i + 2
    in_range = [v for v in all_videos if lo <= v["desc_len"] < hi]
    viral_in = [v for v in in_range if v in viral]
    ws6.cell(row=r, column=1, value=label)
    ws6.cell(row=r, column=2, value=len(in_range))
    ws6.cell(row=r, column=3, value=pct(len(in_range), total))
    ws6.cell(row=r, column=4, value=len(viral_in))
    ws6.cell(row=r, column=5, value=pct(len(viral_in), len(in_range)) if in_range else 0)
    ws6.cell(row=r, column=6, value=avg([v["digg"] for v in in_range]))
    ws6.cell(row=r, column=7, value=avg([v["comment"] for v in in_range]))
    ws6.cell(row=r, column=8, value=avg([v["engagement"] for v in in_range]))
style_data(ws6, 2, len(len_buckets) + 1, 8)
auto_width(ws6)

# ═══════════════════════════════════════════════════════
# Sheet 7: TOP100 爆款视频明细
# ═══════════════════════════════════════════════════════
log("Building Sheet 7: TOP100 viral videos...")
ws7 = wb.create_sheet("TOP100爆款视频")

headers7 = ["排名", "国家", "关键词", "作者", "标题", "标签", "时长(秒)", "内容类型", "点赞", "评论", "分享", "收藏", "互动(加权)"]
for i, h in enumerate(headers7, 1):
    ws7.cell(row=1, column=i, value=h)
style_header(ws7, 1, 13)

for i, v in enumerate(viral[:100]):
    r = i + 2
    ws7.cell(row=r, column=1, value=i + 1)
    ws7.cell(row=r, column=2, value=v["country"])
    ws7.cell(row=r, column=3, value=v["keyword"])
    ws7.cell(row=r, column=4, value=v["author_nickname"])
    ws7.cell(row=r, column=5, value=v["desc"][:80])
    ws7.cell(row=r, column=6, value=", ".join(v["tags"][:5]))
    ws7.cell(row=r, column=7, value=v["duration_sec"])
    ws7.cell(row=r, column=8, value=v["content_type"])
    ws7.cell(row=r, column=9, value=v["digg"])
    ws7.cell(row=r, column=10, value=v["comment"])
    ws7.cell(row=r, column=11, value=v["share"])
    ws7.cell(row=r, column=12, value=v["collect"])
    ws7.cell(row=r, column=13, value=v["engagement"])
style_data(ws7, 2, min(101, len(viral) + 1), 13)
auto_width(ws7)
ws7.column_dimensions["E"].width = 45
ws7.column_dimensions["F"].width = 30

# ═══════════════════════════════════════════════════════
# Sheet 8: 各国爆款率排名
# ═══════════════════════════════════════════════════════
log("Building Sheet 8: Country viral rate ranking...")
ws8 = wb.create_sheet("各国爆款率排名")

headers8 = ["排名", "国家", "总视频数", "爆款数", "爆款率(%)", "平均互动", "内容类型偏好"]
for i, h in enumerate(headers8, 1):
    ws8.cell(row=1, column=i, value=h)
style_header(ws8, 1, 7)

country_viral = []
for cname, cdata in stats_by_country.items():
    c_videos = [v for v in all_videos if v["country"] == cname]
    c_viral = [v for v in c_videos if v in viral]
    # Dominant content type
    type_counter = Counter(v["content_type"] for v in c_videos)
    top_type = type_counter.most_common(2)
    type_str = ", ".join(f"{t}({c})" for t, c in top_type)

    country_viral.append({
        "country": cname,
        "total": len(c_videos),
        "viral_count": len(c_viral),
        "viral_rate": pct(len(c_viral), len(c_videos)) if c_videos else 0,
        "avg_eng": avg([v["engagement"] for v in c_videos]),
        "top_type": type_str,
    })

country_viral.sort(key=lambda x: x["viral_rate"], reverse=True)

for i, cv in enumerate(country_viral):
    r = i + 2
    ws8.cell(row=r, column=1, value=i + 1)
    ws8.cell(row=r, column=2, value=cv["country"])
    ws8.cell(row=r, column=3, value=cv["total"])
    ws8.cell(row=r, column=4, value=cv["viral_count"])
    ws8.cell(row=r, column=5, value=cv["viral_rate"])
    ws8.cell(row=r, column=6, value=cv["avg_eng"])
    ws8.cell(row=r, column=7, value=cv["top_type"])
style_data(ws8, 2, len(country_viral) + 1, 7)
auto_width(ws8)
ws8.column_dimensions["G"].width = 35

# ── Save ──
log(f"Saving to {OUTPUT}...")
wb.save(str(OUTPUT))
log(f"Done! Report saved.")

# ── Print summary ──
log(f"\n{'='*50}")
log(f"A1 爆款内容拆解 完成")
log(f"{'='*50}")
log(f"数据量: {total} 视频, {len(viral)} 爆款(Top10%)")
log(f"爆款率最高的时长区间: {max(bucket_data, key=lambda x: x['viral_rate'])['label']}")
log(f"爆款率最高的内容类型: {max(type_data, key=lambda x: x['viral_rate'])['type']}")
log(f"最佳标题长度区间: {max(len_buckets, key=lambda lb: pct(len([v for v in all_videos if lb[0]<=v['desc_len']<lb[1] and v in viral]), len([v for v in all_videos if lb[0]<=v['desc_len']<lb[1]]) or 1))[2]}")
top_tags = all_tags.most_common(5)
log(f"热门标签TOP5: {', '.join(f'{t}({c})' for t, c in top_tags)}")
