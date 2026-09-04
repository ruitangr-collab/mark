#!/usr/bin/env python3
"""跨账号需求密度统计（账号分级核心指标）

读取 ~/.workbuddy/douyin_analysis/account_*/all_comments.json，
按五类需求正则统计每账号的需求密度与需求绝对量，用于 S/A/B 分级。

用法:
    python3 demand_density.py            # 统计全部账号，按密度降序
    python3 demand_density.py --top 8    # 只看前8

输出: 昵称/粉丝/评论/需求数/密度%/五类分布
分级规则见 SKILL.md「账号分级标准（出海服务核心）」
"""
import json, re, sys
from pathlib import Path

BASE = Path.home() / '.workbuddy' / 'douyin_analysis'

# 五类需求正则（出海意向人群诉求）
CATS = {
    '投资创业': r'(创业|投资|开厂|办厂|建厂|做生意|开店|考察|项目|布局|入场|市场怎么样|搞实业|实业)',
    '货源采购': r'(采购|批发|进货|货源|拿货|供应|报价|多少钱|价格|成本|渠道拿|找.{0,3}(货源|供应商)|出口.{0,4}(怎么|如何))',
    '意向咨询': r'(怎么|如何|能不能|可不可以|需要什么|什么条件|手续|流程|求带|带带我|请教|咨询|求助|行不行|靠谱吗|有没有.{0,3}(风险|搞头|前途))',
    '合作商务': r'(合作|加盟|代理|合伙|对接|资源|人脉|交流|认识一下|找.{0,3}(合作|老板)|商务|一起做|入伙)',
    '渠道获客': r'(引流|获客|涨粉|直播|带货|渠道|客户|销售|推广|账号|内容|短视频|粉丝)',
}

# 界面噪音（页脚/播放器/时间戳残留）
NOISE = ['京公网安备', '备案号', '立即领取', '快乐大本营', '大学生免费用',
         '我的喜欢', '充钻石', '进入全屏', '播放中', '退出全屏']


def clean(c: str):
    c = c.strip()
    if len(c) < 2:
        return None
    if any(n in c for n in NOISE):
        return None
    c = re.sub(r'^\d+\s?(小时|分钟|天)前.*$', '', c)
    return c.strip() or None


def analyze_account(d: Path):
    nick = d.name.replace('account_', '')
    followers = 0
    uj = d / 'user_info.json'
    if uj.exists():
        try:
            followers = json.load(open(uj, encoding='utf-8')).get('follower_count', 0)
        except Exception:
            pass
    cf = d / 'all_comments.json'
    if not cf.exists():
        return None
    raw = json.load(open(cf, encoding='utf-8'))
    comments = [c for c in (clean(c) for c in raw) if c]
    total = len(comments)
    hit_any, cat_count = set(), {k: 0 for k in CATS}
    for i, c in enumerate(comments):
        for k, pat in CATS.items():
            if re.search(pat, c):
                cat_count[k] += 1
                hit_any.add(i)
    return {
        'nick': nick, 'followers': followers, 'total': total,
        'req': len(hit_any),
        'density': len(hit_any) / total * 100 if total else 0,
        **cat_count,
    }


def main():
    top_n = None
    if '--top' in sys.argv:
        top_n = int(sys.argv[sys.argv.index('--top') + 1])
    rows = [r for r in (analyze_account(d) for d in sorted(BASE.glob('account_*'))) if r]
    rows.sort(key=lambda x: -x['density'])
    if top_n:
        rows = rows[:top_n]
    print(f"{'昵称':<14}{'粉丝(万)':>8}{'评论':>6}{'需求数':>6}{'密度%':>7}  投资 货源 咨询 合作 获客")
    for r in rows:
        print(f"{r['nick'][:14]:<14}{r['followers']/10000:>8.1f}{r['total']:>6}{r['req']:>6}"
              f"{r['density']:>7.1f}  {r['投资创业']:>4} {r['货源采购']:>4} "
              f"{r['意向咨询']:>4} {r['合作商务']:>4} {r['渠道获客']:>4}")


if __name__ == '__main__':
    main()
