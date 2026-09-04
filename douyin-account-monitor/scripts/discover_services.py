#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出海服务拓号引擎（2026-09-04 建）

用途：以「出海服务」为核心，每日按关键词搜索抖音用户 tab，
发现新的出海服务类账号 → 服务属性过滤 → 轻量加入监控名单（accounts+snapshot）。

与 discover_accounts.py（商贸城/产业园项目库拓号）的区别：
  - 本项目找「出海服务商/带路人/招商/物流/海外仓/代办顾问」账号；
  - 过滤口径 = 服务属性词 OR 非洲词（不是 AND 非洲国家词硬过滤，
    否则会误杀于哥这类河南 IP 不带国家词的出海服务号）；
  - 入库 = 轻量直写（不开浏览器主页），基线留给每日巡查自动建。

用法:
  python3 discover_services.py                    # 默认关键词组 + 过滤 + 入库
  python3 discover_services.py --dry-run          # 只出候选清单，不入库（试跑用）
  python3 discover_services.py "非洲考察团,非洲物流"  # 指定关键词
  python3 discover_services.py --min-fans 1000    # 粉丝门槛（默认 0 不过滤）
  python3 discover_services.py --no-filter        # 关闭服务属性过滤（慎用）

输出: ~/.workbuddy/skills/douyin-account-monitor/data/discovery/discovery_services_<日期>.json/.md
"""
import sys, json, re, time, sqlite3
from pathlib import Path
from urllib.parse import quote
from datetime import datetime

CA_DIR = Path.home() / '.workbuddy' / 'skills' / 'douyin-comment-analyzer' / 'scripts'
if str(CA_DIR) not in sys.path:
    sys.path.insert(0, str(CA_DIR))

from DrissionPage import ChromiumPage, ChromiumOptions  # noqa: E402
from common import is_logged_in, wait_for_login  # noqa: E402
import discover_accounts as da  # 复用搜索/卡片解析原语  # noqa: E402

MONITOR_DIR = Path.home() / '.workbuddy' / 'skills' / 'douyin-account-monitor'
sys.path.insert(0, str(MONITOR_DIR / 'scripts'))
import monitor  # noqa: E402  —— 复用 DB 与 add 逻辑

PROFILE_DIR = Path.home() / ".workbuddy/douyin_chrome_profile"
OUTPUT_DIR = MONITOR_DIR / "data" / "discovery"

# ─── 出海服务向关键词（默认组）─────────────────────────────────────────
# 目标：捞「对出海生意人提供服务的账号」——考察带路/招商/物流/海外仓/落地代办/咨询顾问
DEFAULT_KEYWORDS = [
    '非洲考察团', '非洲商务考察', '非洲考察',
    '出海非洲', '非洲创业指导', '非洲投资咨询',
    '非洲物流', '非洲海外仓', '非洲清关', '非洲货代',
    '非洲公司注册', '非洲签证', '非洲落地服务',
    '非洲产业园招商', '非洲工业园',
]

# 服务属性强词：命中昵称或签名 → 判定为出海服务账号
SERVICE_WORDS = [
    '考察团', '考察', '招商', '物流', '海外仓', '清关', '货代', '货运',
    '公司注册', '注册', '代办', '签证', '咨询', '顾问', '落地服务',
    '出海服务', '供应链', '带路', '对接', '商会', '创业指导',
    '投资咨询', '产业园', '工业园', '陪同', '翻译', '服务',
]

# 强服务词（自动入库门槛）：To B 出海服务商的硬特征
STRONG_WORDS = [
    '物流', '货代', '清关', '海外仓', '专线', '海运', '空运', '供应链',
    '考察团', '招商', '产业园', '工业园', '落地服务', '公司注册', '代办',
    '对接', '商会', '带路', '出海服务', '双清', '服务中心', '安保联防',
]

# 排除词：命中即不算服务商（民宿/酒店/国内商贸城/农业矿业内容号）
EXCLUDE_WORDS = [
    '民宿', '酒店', '宾馆', '旅馆', '睡衣', '选矿', '金矿', '农场',
    '养殖', '翻译社', '俱乐部', '黑杨', '商贸城', '媳妇', '跨国恋',
    '红宝石', '黄金矿业', '钻石', '工厂', '菏泽', '牡丹芍药', '孵化器',
    '时光机', '做证明题', '建材超市',  # 在非华人内容号特征（Wendy的时光机刚果金等，非服务商）
]

# 语境模糊强词：国内产业园/招商号同样命中（杭州开投/东郊记忆/恒力南通等），
# 必须同时命中「非洲/国家词/出海」语境才算服务商，否则只进候选不进库。
# 2026-09-04 晚 20:00 拓号踩坑：19 个自动入库里 12 个是国内园区号，靠人工回滚。
ZONE_AMBIGUOUS_WORDS = ['产业园', '工业园', '招商']

# 非洲/出海语境词（与园区类强词联动用）
AFRICA_CTX_WORDS = ['非洲', '出海', '跨境', '驻外', '非洲国家'] + \
    [k for k in da.COUNTRIES if k not in ('非洲',)]

# 非洲国家词（复用 discover_accounts 的）
COUNTRIES = da.COUNTRIES


def detect_service(text: str) -> list[str]:
    """检测文本命中的服务属性词"""
    return [w for w in SERVICE_WORDS if w and w in (text or '')]


def is_strong_service(text: str) -> bool:
    """强服务判定（自动入库门槛）：命中强服务词 且 未命中排除词。

    语境坑（2026-09-04 晚修复）：'产业园/工业园/招商' 等词国内园区号同样命中，
    必须联动非洲/出海语境，否则会把杭州开投、东郊记忆·成都、恒力南通、
    浩森牡丹芍药等纯国内园区招商号灌进名单。
    """
    if any(w in text for w in EXCLUDE_WORDS):
        return False
    if any(w in text for w in STRONG_WORDS):
        # 若命中的全是「语境模糊强词」（园区/招商类），必须有非洲/出海语境
        hits = [w for w in STRONG_WORDS if w in text]
        if all(w in ZONE_AMBIGUOUS_WORDS for w in hits):
            return any(w in text for w in AFRICA_CTX_WORDS)
        return True
    return False


def detect_countries(text: str) -> list[str]:
    return [c for c, kws in COUNTRIES.items() if any(k in text for k in kws)]


def main():
    args = [a for a in sys.argv[1:]]
    dry_run = '--dry-run' in args
    if dry_run:
        args.remove('--dry-run')
    do_filter = True
    if '--no-filter' in args:
        do_filter = False
        args.remove('--no-filter')
    min_fans = 1000  # 自动入库的粉丝门槛（<此值仅入候选清单不自动入库，避免微号污染名单）
    if '--min-fans' in args:
        i = args.index('--min-fans')
        min_fans = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    if args:
        keywords = [k.strip() for k in args[0].split(',') if k.strip()]
    else:
        keywords = DEFAULT_KEYWORDS

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 浏览器（复用登录态，窗口最小化）──────────────────────────────
    co = ChromiumOptions()
    co.set_user_data_path(str(PROFILE_DIR))
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--start-minimized')
    co.set_argument('--no-sandbox')
    page = ChromiumPage(co)
    page.get('https://www.douyin.com/')
    time.sleep(6)
    if not is_logged_in(page):
        print('⚠️ 未登录，等待扫码...')
        wait_for_login(page)

    # ── 逐关键词搜索用户 tab ────────────────────────────────────────
    all_cards = []
    print(f"搜索 {len(keywords)} 个出海服务关键词（用户 tab）")
    for kw in keywords:
        try:
            all_cards.extend(da.search_keyword(page, kw, scroll=4))
        except Exception as e:
            print(f"  「{kw}」失败: {e}")
        time.sleep(1)
    page.quit()

    # ── 去重（按 sec_uid 保留粉丝多的）──────────────────────────────
    uniq = {}
    for c in all_cards:
        k = c['sec_uid']
        if k not in uniq or c['followers'] > uniq[k]['followers']:
            uniq[k] = c
    rows = list(uniq.values())

    # ── 服务属性判定 ────────────────────────────────────────────────
    for r in rows:
        full = ' '.join([r.get('nickname', ''), r.get('signature', '')])
        r['service_hits'] = detect_service(full)
        r['countries'] = detect_countries(full)
        r['is_service'] = r['is_strong'] = is_strong_service(full)

    # ── 过滤：服务属性命中 或 命中非洲词（宽口径但保底）───────────────
    before = len(rows)
    if do_filter:
        rows = [r for r in rows if r['is_service'] or r['countries']]
    if min_fans > 0:
        rows = [r for r in rows if r['followers'] == 0 or r['followers'] >= min_fans]

    # ── 与监控名单比对 ───────────────────────────────────────────────
    conn = monitor.init_db()
    c = conn.cursor()
    c.execute("SELECT sec_uid, nickname FROM accounts WHERE active=1")
    existing = {r[0]: r[1] for r in c.fetchall()}
    new_rows = [r for r in rows if r['sec_uid'] not in existing]
    already = [r for r in rows if r['sec_uid'] in existing]

    svc_new = [r for r in new_rows if r['is_service']]
    # 自动入库 = 服务属性 AND 粉丝≥min_fans；其余进候选清单但不灌库（防微号污染）
    auto_add = [r for r in svc_new if r['followers'] >= min_fans]
    print(f"\n去重 {before} → 过滤后 {len(rows)} 个 | "
          f"已在监控 {len(already)} 个 | 新候选 {len(new_rows)} 个"
          f"（服务属性 {len(svc_new)}，达入库线 ≥{min_fans}粉 {len(auto_add)}）")

    # ── 入库（非 dry-run）────────────────────────────────────────────
    added = []
    if not dry_run:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for r in auto_add:
            try:
                c.execute("""INSERT OR IGNORE INTO accounts
                             (sec_uid, nickname, signature, source_url, added_at, last_check,
                              active, baselined, douyin_id)
                             VALUES (?,?,?,?,?,?,1,0,?)""",
                          (r['sec_uid'], r['nickname'], r.get('signature'),
                           f"discover_services:{','.join(keywords[:3])}", now, now,
                           r.get('douyin_id')))
                # 轻量快照：粉丝/获赞来自搜索卡片，作品数未知留 0，巡查自动补
                c.execute("""INSERT INTO snapshots
                             (sec_uid, checked_at, follower_count, total_favorited, aweme_count, ok)
                             VALUES (?,?,?,?,0,1)""",
                          (r['sec_uid'], now, r['followers'], r['likes']))
                added.append(r)
            except Exception as e:
                print(f"  入库失败 {r['nickname']}: {e}")
        conn.commit()
    conn.close()

    # ── 输出候选清单 ────────────────────────────────────────────────
    date = datetime.now().strftime('%Y-%m-%d')
    suffix = '_dryrun' if dry_run else ''
    base = f'discovery_services_{date}{suffix}'
    jf = OUTPUT_DIR / f'{base}.json'
    md = [f"# 出海服务拓号清单（{date}{' · 试跑未入库' if dry_run else ''}）\n",
          f"- 关键词：{len(keywords)} 个（{'、'.join(keywords)}）",
          f"- 命中口径：服务属性词 OR 非洲词；新候选 {len(new_rows)}，其中服务属性 {len(svc_new)}",
          f"- 状态：{'未入库（试跑）' if dry_run else f'自动入库 {len(added)} 个（服务属性且≥{min_fans}粉）'}",
          "",
          "| 状态 | 账号 | 粉丝 | 获赞 | 服务词 | 国家 | 签名 |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted(new_rows, key=lambda x: (not x['is_service'], -x['followers'])):
        st = '➕入库' if (not dry_run and r in added) else ('✅服务' if r['is_service'] else '🔸非洲')
        fans = f"{r['followers']/10000:.1f}万" if r['followers'] >= 10000 else str(r['followers'] or '-')
        svc = ','.join(r['service_hits'][:3]) or '-'
        ct = ','.join(r['countries'][:2]) or '-'
        md.append(f"| {st} | {r['nickname']} | {fans} | {r['likes']} | {svc} | {ct} | {(r.get('signature') or '')[:40]} |")
    if already:
        md += ["", f"（已在监控名单，跳过：{'、'.join(r['nickname'] for r in already[:10])}）"]
    mf = OUTPUT_DIR / f'{base}.md'
    jf.write_text(json.dumps({'date': date, 'keywords': keywords, 'new': new_rows,
                              'already': already, 'added': [r['sec_uid'] for r in added],
                              'dry_run': dry_run}, ensure_ascii=False, indent=1), encoding='utf-8')
    mf.write_text('\n'.join(md), encoding='utf-8')
    print(f"\n✅ 输出：\n  {jf}\n  {mf}")
    print(f"服务属性新候选 {len(svc_new)} 个：" if svc_new else "\n⚠️ 本轮无服务属性新号")
    for r in sorted(svc_new, key=lambda x: -x['followers']):
        fans = f"{r['followers']/10000:.1f}万" if r['followers'] >= 10000 else str(r['followers'] or '-')
        print(f"  {fans:>7} | {r['nickname'][:24]} | {','.join(r['service_hits'][:3])}")


if __name__ == '__main__':
    main()
