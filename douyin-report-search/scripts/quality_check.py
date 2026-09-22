#!/usr/bin/env python3
"""v4分析质量诊断"""
import json, os, re, sys
from collections import Counter, defaultdict
from statistics import mean, median, stdev
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')

data_dir = 'C:/Users/53185/.workbuddy/skills/douyin-report-search/country_data'

NEWS_KEYWORDS_VERIFY = [
    '新闻','日报','TV','卫视','资讯','网','广播','频道','CCTV','cctv',
    '新华社','人民日报','环球','参考消息','中国日报','凤凰','观察者',
    '头条','快报','官方发布','电视台','传媒','报道','时报','央视频',
    '央视','观察','财经网','新媒体',
]
def is_news(author):
    nickname = (author.get('nickname') or '').lower()
    ev = author.get('enterprise_verify_reason') or ''
    cv = author.get('custom_verify') or ''
    if ev:
        for kw in NEWS_KEYWORDS_VERIFY:
            if kw.lower() in ev.lower(): return True
    if cv:
        for kw in NEWS_KEYWORDS_VERIFY:
            if kw.lower() in cv.lower(): return True
    if ev:
        for kw in ['新闻','日报','TV','卫视','资讯','广播','频道','CCTV','cctv',
                    '新华社','人民日报','环球','参考消息','中国日报','凤凰','观察者',
                    '头条','快报','报道','时报','央视频','央视']:
            if kw.lower() in nickname: return True
    return False

all_creator = []
all_news = []
for fname in sorted(os.listdir(data_dir)):
    fpath = os.path.join(data_dir, fname)
    try:
        data = json.loads(open(fpath, encoding='utf-8').read())
    except:
        continue
    country = fname.split('_')[0]
    for v in data.get('videos', []):
        raw = v.get('_raw') or {}
        author = raw.get('author') or {}
        if is_news(author):
            all_news.append((v, author, country))
        else:
            all_creator.append((v, author, country))

print(f'Creator: {len(all_creator)}, News: {len(all_news)}')

# 1. Comment-like ratio distribution
print('\n=== 1. 评赞比分布 ===')
clrs = []
for v,a,_ in all_creator:
    s = v.get('statistics', {})
    likes = s.get('digg_count') or 0
    comments = s.get('comment_count') or 0
    if likes > 0:
        clrs.append(comments/likes)

clrs_s = sorted(clrs)
n = len(clrs_s)
print(f'min={min(clrs):.4f} p5={clrs_s[int(n*.05)]:.4f} p25={clrs_s[int(n*.25)]:.4f} p50={clrs_s[int(n*.5)]:.4f} p75={clrs_s[int(n*.75)]:.4f} p95={clrs_s[int(n*.95)]:.4f} max={max(clrs):.4f}')
print(f'mean={mean(clrs):.4f} std={stdev(clrs):.4f} zeros={sum(1 for c in clrs if c==0)}/{n}')

# Outliers
p95v = clrs_s[int(n*.95)]
outliers = [(v,a,c) for (v,a,c), clr in zip(all_creator, clrs) if clr > p95v]
print(f'Outliers (>p95=0.5): {len(outliers)}')
for v,a,c in sorted(outliers, key=lambda x: x[0].get('statistics',{}).get('digg_count',0))[:5]:
    s = v.get('statistics', {})
    desc = ((v.get('_raw') or {}).get('desc') or '')[:60]
    print(f'  likes={s.get("digg_count",0)} comments={s.get("comment_count",0)} follower={a.get("follower_count",0):,} desc="{desc}"')

# 2. Follower distribution
print('\n=== 2. 粉丝分布 ===')
fcs = [a.get('follower_count',0) or 0 for v,a,_ in all_creator if (a.get('follower_count',0) or 0) > 0]
fcs_s = sorted(fcs)
fn = len(fcs_s)
print(f'min={min(fcs):,} p25={fcs_s[fn//4]:,} p50={fcs_s[fn//2]:,} p75={fcs_s[fn*3//4]:,} p95={fcs_s[int(fn*.95)]:,} max={max(fcs):,}')
print(f'mean={mean(fcs):,.0f} std={stdev(fcs):,.0f}')
print(f'Skew: mean/median = {mean(fcs)/fcs_s[fn//2]:.1f}x')
print(f'<1K: {sum(1 for f in fcs if f<1000)/fn*100:.1f}%  >100W: {sum(1 for f in fcs if f>=1e6)/fn*100:.1f}%')

# 3. Duration distribution
print('\n=== 3. 时长分布 ===')
durs = []
for v,a,_ in all_creator:
    vid = (v.get('_raw') or {}).get('video') or {}
    d = (vid.get('duration') or 0) / 1000
    if d > 0:
        durs.append(d)
buckets = [(0,15,'<15s'),(15,30,'15-30s'),(30,60,'30-60s'),(60,120,'1-2min'),(120,300,'2-5min'),(300,99999,'>5min')]
for lo,hi,label in buckets:
    cnt = sum(1 for d in durs if lo <= d < hi)
    print(f'  {label}: {cnt} ({cnt/len(durs)*100:.1f}%)')
print(f'  mean={mean(durs):.1f}s median={median(durs):.1f}s')

# 4. Hook type counts
print('\n=== 4. 钩子类型覆盖 ===')
hooks_count = Counter()
for v,a,_ in all_creator:
    desc = ((v.get('_raw') or {}).get('desc') or '').lower()
    if re.search(r'(\d+[个种条项大]|[Tt][Oo][Pp]\s*\d+|第[一二三四五六七八九十\d]+)', desc): hooks_count['数字罗列'] += 1
    if re.search(r'(为什么|怎么|如何|你知道吗|竟然|居然|原来|真相|揭秘|曝光)', desc): hooks_count['好奇悬念'] += 1
    if re.search(r'(vs|对比|差别|区别|不同|竟然|居然|反而|却是)', desc): hooks_count['对比反差'] += 1
    if re.search(r'(太|好|最|绝|爆|燃|泪目|感动|震惊|可怕|恐怖|疯狂|牛逼|厉害)', desc): hooks_count['情绪共鸣'] += 1
    if re.search(r'(揭秘|独家|首次|罕见|秘密|内幕|不为人知|99%|百分九十九|没几个人)', desc): hooks_count['稀缺独家'] += 1
    if re.search(r'(教程|攻略|方法|技巧|干货|建议|指南|步骤|必看|收藏|避坑)', desc): hooks_count['实用指南'] += 1
    if re.search(r'(我在|经历|故事|见过|亲历|实拍|记录|日记)', desc): hooks_count['亲身经历'] += 1
for hk, cnt in hooks_count.most_common():
    print(f'  {hk}: {cnt}')

# 5. Day distribution
print('\n=== 5. 发布日分布 ===')
utc8 = timezone(timedelta(hours=8))
day_count = Counter()
hour_count = Counter()
for v,a,_ in all_creator:
    ct = (v.get('_raw') or {}).get('create_time')
    if ct:
        try:
            dt = datetime.fromtimestamp(ct, tz=utc8)
            day_count[dt.strftime('%A')] += 1
            hour_count[dt.hour] += 1
        except:
            pass
for d in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']:
    print(f'  {d}: {day_count[d]}')

# 6. Engagement-per-follower
print('\n=== 6. 粉均互动率 ===')
epfs = []
for v,a,_ in all_creator:
    s = v.get('statistics', {})
    fc = a.get('follower_count', 0) or 1
    total = (s.get('digg_count') or 0)+(s.get('comment_count') or 0)+(s.get('share_count') or 0)+(s.get('collect_count') or 0)
    epfs.append(total/fc)
epfs_s = sorted(epfs)
en = len(epfs_s)
print(f'p50={epfs_s[en//2]:.4f} p75={epfs_s[en*3//4]:.4f} mean={mean(epfs):.4f} std={stdev(epfs):.4f}')
print(f'>1: {sum(1 for e in epfs if e>1)/en*100:.1f}%  >10: {sum(1 for e in epfs if e>10)/en*100:.1f}%')

# 7. Effect sizes
print('\n=== 7. Cohen d 效果量 ===')
def cohens_d(a, b):
    if len(a)<2 or len(b)<2: return 0
    ma, mb = mean(a), mean(b)
    va, vb = stdev(a), stdev(b)
    pooled = (((len(a)-1)*va**2 + (len(b)-1)*vb**2) / (len(a)+len(b)-2))**0.5
    return (ma-mb)/pooled if pooled>0 else 0

q_yes = []; q_no = []
p_yes = []; p_no = []
for v,a,_ in all_creator:
    desc = ((v.get('_raw') or {}).get('desc') or '')
    vid = (v.get('_raw') or {}).get('video') or {}
    h = vid.get('height') or 0; w = vid.get('width') or 0
    s = v.get('statistics', {})
    likes = s.get('digg_count') or 0
    comments = s.get('comment_count') or 0
    if likes > 0:
        clr = comments/likes
        if re.search(r'[?？]|吗|么|怎么|如何|什么|为什么|哪|谁|几', desc):
            q_yes.append(clr)
        else:
            q_no.append(clr)
        if h and w:
            if h > w: p_yes.append(clr)
            else: p_no.append(clr)

d_q = cohens_d(q_yes, q_no)
d_p = cohens_d(p_yes, p_no)
print(f'疑问句: d={d_q:.4f} ({"极小" if abs(d_q)<0.2 else "小" if abs(d_q)<0.5 else "中" if abs(d_q)<0.8 else "大"})')
print(f'竖屏vs横屏: d={d_p:.4f} ({"极小" if abs(d_p)<0.2 else "小" if abs(d_p)<0.5 else "中" if abs(d_p)<0.8 else "大"})')

# 8. Time span check
print('\n=== 8. 时间跨度 ===')
times = []
for v,a,_ in all_creator:
    ct = (v.get('_raw') or {}).get('create_time')
    if ct:
        times.append(ct)
if times:
    tmin = datetime.fromtimestamp(min(times), tz=utc8)
    tmax = datetime.fromtimestamp(max(times), tz=utc8)
    print(f'视频时间范围: {tmin.strftime("%Y-%m-%d")} ~ {tmax.strftime("%Y-%m-%d")}')

# 9. Country coverage balance
print('\n=== 9. 各国样本量 ===')
country_cnt = Counter()
for v,a,c in all_creator:
    country_cnt[c] += 1
print(f'总国家数: {len(country_cnt)}')
print(f'Min: {min(country_cnt.values())} Max: {max(country_cnt.values())}')
print(f'Mean: {mean(country_cnt.values()):.0f} Std: {stdev(country_cnt.values()):.0f}')
for c, cnt in sorted(country_cnt.items(), key=lambda x: -x[1]):
    print(f'  {c}: {cnt}')
