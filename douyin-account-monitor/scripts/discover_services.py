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

# ── 非洲锚点硬门槛（2026-09-22 踩坑后新增）────────────────────────────
# 踩坑：本轮「非洲产业园招商」关键词搜出 3 个纯国内园区号并自动入库——
#   大湾区数字产业服务平台(28.7万/广东) / 临沂商城国际电子商务产业园(2.6万/山东) /
#   侯马开发区新田智联信创产业园(1.0万/山西)，均靠人工回滚。
# 原因：旧逻辑只在「命中的强词**全部**是园区类」时才校验非洲语境；只要混进
#   「物流/服务/对接」任意一个非模糊词即绕过校验直接放行。
# 修复：所有账号一律先过「非洲锚点」；缺锚点时须同时具备
#   ① 跨境属性服务词（货代/清关/双清/海外仓/…）② 跨境业务语境词（跨境/外贸/出口/国际/出海/海外）
#   二者缺一不可。产业园/招商/对接/商会/供应链/物流 等国内同样泛滥的词不再单独放行。
AFRICA_ANCHOR_WORDS = ['非洲', '中非', '北非', '西非', '东非', '南非', '撒哈拉'] + \
    [k for k in da.COUNTRIES if k not in ('非洲',)]
CROSS_BORDER_SERVICE_WORDS = [
    '货代', '清关', '双清', '海外仓', '专线', '海运', '空运', '订舱', '报关',
    '考察团', '落地服务', '签证', 'ECTN', 'COC', 'PVOC', '拼柜', '整柜',
]
CROSS_BORDER_CTX_WORDS = ['跨境', '外贸', '出口', '国际', '出海', '海外', '全球', '门到门', '到门']


def has_africa_anchor(text: str) -> bool:
    """非洲锚点：昵称/签名中直接出现非洲、非洲次区域或非洲国家名。"""
    t = text or ''
    return any(w in t for w in AFRICA_ANCHOR_WORDS)


def has_crossborder_evidence(text: str) -> bool:
    """无非洲锚点时的补救通道：跨境属性服务词 + 跨境业务语境词须同时命中。"""
    t = text or ''
    return (any(w in t for w in CROSS_BORDER_SERVICE_WORDS)
            and any(w in t for w in CROSS_BORDER_CTX_WORDS))

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

    2026-09-22 二次修复（旧逻辑被绕过）：旧逻辑只在「命中的强词**全部**是园区类」
    时才校验非洲语境，只要混进「物流/服务/对接」就放行。现改为全局非洲锚点硬门槛：
      ① 有非洲锚点（非洲/次区域/非洲国家名）→ 正常按强服务词判定
      ② 无锚点 → 必须同时有「跨境属性服务词」+「跨境业务语境词」才算服务商
    """
    if any(w in text for w in EXCLUDE_WORDS):
        return False
    if not any(w in text for w in STRONG_WORDS):
        return False
    # 非洲锚点硬门槛（2026-09-22 新增）
    if has_africa_anchor(text):
        return True
    return has_crossborder_evidence(text)


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
    # 单轮自动入库上限（Mark 2026-09-04 定：放量 1-4 个/天）。
    # 2026-09-14 加：修复「获赞<1万 → 粉丝被清零」解析缺陷后，达线候选会从
    # 每日 0-25 个跃升，加此上限把放量锁回 Mark 定的节奏，超出的号仍进候选清单
    # （标记「🕒待入库」）供人工复核，不静默丢弃。
    max_add = 4
    if '--max-add' in args:
        i = args.index('--max-add')
        max_add = int(args[i + 1])
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
    # 粉丝门槛**不在此处裁剪**（2026-09-14 改）：只作用于 auto_add 判定。
    # 原因：修复「获赞<1万 → 粉丝被清零」后，<1000 粉 的服务号会拿到真实粉丝值，
    # 若仍在这里按 min_fans 裁掉，候选清单里的「弱信号服务号观察池」会整体消失
    # （历史每日约 200 个）。保留它们入清单（标 ✅服务），只是不自动入库。

    # ── 与监控名单比对 ───────────────────────────────────────────────
    conn = monitor.init_db()
    c = conn.cursor()
    c.execute("SELECT sec_uid, nickname FROM accounts WHERE active=1")
    existing = {r[0]: r[1] for r in c.fetchall()}

    # 回滚黑名单（2026-09-06 加）：人工复核回滚（物理删除）的号记入黑名单文件，
    # 防止被删号在后续搜索中再次命中自动入库。
    # 踩坑实录：09-05 人工回滚 5 号（区域错位/无非洲关联/同主体双号/内容号）后
    # 未留黑名单，09-06 搜索再次命中，5 号全部卷土重来自动入库，靠人工复核二次回滚。
    REJECT_FILE = OUTPUT_DIR.parent / "rejected_accounts.json"
    rejected = {}
    if REJECT_FILE.exists():
        try:
            rejected = json.loads(REJECT_FILE.read_text(encoding='utf-8'))
        except Exception:
            rejected = {}
    rejected_hit = [r for r in rows if r['sec_uid'] in rejected]
    rows = [r for r in rows if r['sec_uid'] not in rejected]

    new_rows = [r for r in rows if r['sec_uid'] not in existing]
    already = [r for r in rows if r['sec_uid'] in existing]

    svc_new = [r for r in new_rows if r['is_service']]
    # 自动入库 = 服务属性 AND 粉丝≥min_fans；其余进候选清单但不灌库（防微号污染）
    qualified = sorted([r for r in svc_new if r['followers'] >= min_fans],
                       key=lambda x: -x['followers'])
    auto_add = qualified[:max_add]
    overflow = qualified[max_add:]
    print(f"\n去重 {before} → 过滤后 {len(rows)} 个 | "
          f"已在监控 {len(already)} 个 | 黑名单拦截 {len(rejected_hit)} 个 | "
          f"新候选 {len(new_rows)} 个"
          f"（服务属性 {len(svc_new)}，达入库线 ≥{min_fans}粉 {len(qualified)}，"
          f"本轮入库 {len(auto_add)}，超上限转候选 {len(overflow)}）")

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
                # 轻量快照：粉丝/获赞来自搜索卡片，作品数未知。
                # 必须写 NULL 而不是 0 —— monitor.py 用「当前作品数 - 上次作品数」算
                # expected_new，写 0 会让首轮基线的全部老视频被当成新作品入队
                # （2026-09-05 实测灌进 296 条）。NULL 会被 prev_aweme is not None 挡掉。
                # likes 防御（2026-09-05 加）：卡片解析偶发把获赞解析成天文数字
                # （实测 1e12~1e17 级，粉丝值正常获赞值错乱）。超过 10 亿视为解析失败
                # 写 NULL，等 4:00 巡查用主页权威值重建，避免下轮巡查巨额负差误报。
                likes = r['likes'] if 0 < r['likes'] <= 1000000000 else None
                c.execute("""INSERT INTO snapshots
                             (sec_uid, checked_at, follower_count, total_favorited, aweme_count, ok)
                             VALUES (?,?,?,?,NULL,1)""",
                          (r['sec_uid'], now, r['followers'], likes))
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
    added_uids = {r['sec_uid'] for r in added}
    overflow_uids = {r['sec_uid'] for r in overflow}
    md = [f"# 出海服务拓号清单（{date}{' · 试跑未入库' if dry_run else ''}）\n",
          f"- 关键词：{len(keywords)} 个（{'、'.join(keywords)}）",
          f"- 命中口径：服务属性词 OR 非洲词；新候选 {len(new_rows)}，其中服务属性 {len(svc_new)}"
          f"{f'；黑名单拦截 {len(rejected_hit)} 个' if rejected_hit else ''}",
          f"- 状态：{'未入库（试跑）' if dry_run else f'自动入库 {len(added)} 个（服务属性且≥{min_fans}粉，单轮上限 {max_add}）'}"
          f"{f'；另 {len(overflow)} 个达线但超上限 → 标 🕒待入库 供人工复核' if overflow else ''}",
          "",
          "| 状态 | 账号 | 粉丝 | 获赞 | 服务词 | 国家 | 签名 |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted(new_rows, key=lambda x: (not x['is_service'], -x['followers'])):
        if not dry_run and r['sec_uid'] in added_uids:
            st = '➕入库'
        elif r['sec_uid'] in overflow_uids:
            st = '🕒待入库'
        elif r['is_service']:
            st = '✅服务'
        else:
            st = '🔸非洲'
        fans = f"{r['followers']/10000:.1f}万" if r['followers'] >= 10000 else str(r['followers'] or '-')
        likes = f"{r['likes']/10000:.1f}万" if 10000 <= r['likes'] <= 1000000000 else (str(r['likes']) if 0 < r['likes'] < 10000 else '?')
        svc = ','.join(r['service_hits'][:3]) or '-'
        ct = ','.join(r['countries'][:2]) or '-'
        md.append(f"| {st} | {r['nickname']} | {fans} | {likes} | {svc} | {ct} | {(r.get('signature') or '')[:40]} |")
    if already:
        md += ["", f"（已在监控名单，跳过：{'、'.join(r['nickname'] for r in already[:10])}）"]
    if rejected_hit:
        md += ["", "⛔ 黑名单拦截（历史人工复核回滚，不再入库）：",
               "、".join(f"{r['nickname']}" for r in rejected_hit)]
    mf = OUTPUT_DIR / f'{base}.md'
    jf.write_text(json.dumps({'date': date, 'keywords': keywords, 'new': new_rows,
                              'already': already, 'added': [r['sec_uid'] for r in added],
                              'overflow': [r['sec_uid'] for r in overflow],
                              'dry_run': dry_run}, ensure_ascii=False, indent=1), encoding='utf-8')
    mf.write_text('\n'.join(md), encoding='utf-8')
    print(f"\n✅ 输出：\n  {jf}\n  {mf}")
    print(f"服务属性新候选 {len(svc_new)} 个：" if svc_new else "\n⚠️ 本轮无服务属性新号")
    for r in sorted(svc_new, key=lambda x: -x['followers']):
        fans = f"{r['followers']/10000:.1f}万" if r['followers'] >= 10000 else str(r['followers'] or '-')
        print(f"  {fans:>7} | {r['nickname'][:24]} | {','.join(r['service_hits'][:3])}")


if __name__ == '__main__':
    main()
