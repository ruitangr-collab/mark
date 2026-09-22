#!/usr/bin/env python3
"""
非洲中资园区/商贸城 项目库【去重核验器】v2

把抖音项目库（projects_master.json）与公开资料基准库（africa_parks_reference.json）
交叉比对。v2 改进：
  * 匹配用「专名关键词(keys)」，避免『工业园』『商贸城』等泛后缀误匹配
  * 账号昵称含园区名 → 强归属（官方运营号最可信）
  * 仅抖音线索内做名称归一合并（大小写/国家前缀/同园区多形态）
  * 输出核验版主清单 Markdown + JSON

用法:
  python3 reconcile_projects.py
"""
import json, re
from pathlib import Path
from collections import defaultdict

HOME = Path.home() / ".workbuddy" / "douyin_analysis"
DISCOVERY_DIR = HOME / "_discovery"
ARCHIVE_DIR = HOME / "_archive"
REF_FILE = ARCHIVE_DIR / "africa_parks_reference.json"
MASTER_FILE = DISCOVERY_DIR / "projects_master.json"

# 专名后缀（用于判断"像项目名"，不是匹配依据）
ENTITY_SUFFIX = ('商贸城', '中国城', '世纪城', '产业园', '工业园', '园区', '工业区', '开发区',
                 '经济特区', '商城', '贸易中心', '商贸中心', '批发市场', '专业市场', '商厦')
NOISE_VERB = ('为您', '为', '提供', '还做', '开拓', '开发', '链接', '分享', '解锁', '帮助',
              '助力', '辐射', '专为', '携手', '看懂', '深耕', '扎根', '就职', '运营', '坐标',
              '位于', '入驻', '进驻', '主要做', '只做', '面向', '对接', '有3000亩', '自建')
COUNTRIES = ['安哥拉', '尼日利亚', '肯尼亚', '坦桑尼亚', '南非', '埃及', '埃塞俄比亚',
             '加纳', '科特迪瓦', '刚果金', '刚果布', '乌干达', '赞比亚', '津巴布韦',
             '莫桑比克', '喀麦隆', '塞内加尔', '卢旺达', '几内亚', '多哥', '毛里求斯', '吉布提']
# 国家词条内嵌别名（用于 country 冲突判断）
COUNTRY_ALIAS = {'刚果金': ['刚果（金）', '金沙萨', '卢本巴希']}

# 手动同指映射：抖音原始项目名 → 基准 canonical（经人工核实）
MANUAL_MAP = {
    '非洲肯尼亚铜锣湾商贸城': '肯尼亚内罗毕中国商贸城（待补基准）',
}

# 跨实体营销话术：多个园区都在用的自夸语，不能强制合并到任一园区。
# 这些词曾误挂到「安哥拉世纪城」，导致非洲旭日集团旗下（中国城/迪高路/新时代）账号串号。
# 处理方式：不进 MANUAL_MAP，落回账号级归属判定（昵称/签名说了算）。
GENERIC_PHRASE = {
    '非洲最大商贸城', '非洲人流最旺的商贸城', '最成熟的华人投资商贸城',
    '香港商贸城', '新时代商贸中心', '非洲最大中国城', '非洲第一商贸城',
}

# 特殊规则：(关键词, 需要匹配到的国家子串, 目标canonical)
# 用于 基准库别名与抖音叫法一字差 的兜底（如 轻工业园≈华坚轻工业城）
SPECIAL_RULES = [
    ('轻工业', '埃塞俄比亚', '华坚（埃塞俄比亚）国际轻工业城'),
    ('苏伊士工业', '埃及', '中埃·泰达苏伊士经贸合作区'),
    ('华非', '尼日利亚', '尼日利亚拉各斯中国商城（China Town Ojota）'),
    # 2026-09-04：张华荣 = 华坚集团董事长，其号签名「埃塞俄比亚经济特区」即华坚轻工业城
    ('经济特区', '埃塞俄比亚', '华坚（埃塞俄比亚）国际轻工业城'),
]

# 国内地名开头 → 大概率是国内实体被误标为非洲项目 → 判噪
DOMESTIC_CITY = ('广州', '临沂', '潍坊', '昌乐', '浙江', '上海', '义乌', '深圳', '石家庄', '济南', '青岛')

# 2026-09-04 新增：非非洲地区的园区/市场。
# 背景：扩关键词「加纳工业园」后，洛加纳工业园（泰国 Rojana，名字里带「加纳」二字）
# 被国家匹配器误判为加纳项目。这类不是非洲资产，必须剔除。
FOREIGN_PARK = ('洛加纳', '泰国', '越南', '柬埔寨', '印尼', '印度', '迪拜', '中东',
                '马来西亚', '菲律宾', '孟加拉', '墨西哥', '巴西')


def load_reference() -> list[dict]:
    d = json.load(open(REF_FILE, encoding='utf-8'))
    # 派生专名关键词：canonical + aliases 中长度>=2 且非纯泛后缀的片段
    for r in d['parks']:
        keys = set()
        for t in [r['canonical']] + r.get('aliases', []):
            if len(t) < 2:
                continue
            keys.add(t)
        # 若 canonical 较长(>4字)，把去国家前缀后的主干也作为 key
        bare = re.sub(r'^(埃塞俄比亚|乌干达|安哥拉|尼日利亚|赞比亚|多哥|坦桑尼亚|埃及|肯尼亚|毛里求斯|塞拉利昂)', '', r['canonical'])
        if len(bare) >= 2:
            keys.add(bare)
        r['_keys'] = [k for k in keys if not (len(k) == 3 and k in ('工业园', '商贸城', '中国城', '产业园'))]
        # 泛后缀词（如 世纪城/中国城 在特定国家语境有效）单独保留在 aliases 中
        r['_keys'] = sorted({k for k in r['_keys']})
    return d['parks']


def country_match(proj_countries: list[str], ref_country: str) -> bool:
    """抖音项目国家 与 基准国家 是否兼容"""
    if not proj_countries or not ref_country:
        return True
    for c in proj_countries:
        if c in ref_country or ref_country in c:
            return True
        for alias in COUNTRY_ALIAS.get(c, []):
            if alias in ref_country:
                return True
    return False


def nick_hits_reference(nick: str, refs: list[dict]) -> dict | None:
    """账号昵称匹配基准（官方号昵称=园区名的强信号）"""
    for r in refs:
        for k in r['_keys']:
            if len(k) >= 3 and k in nick:
                return r
    return None


def proj_hits_reference(project: str, refs: list[dict]) -> dict | None:
    """项目名文本匹配基准：优先长关键词，避免泛词误伤"""
    best, best_len = None, 0
    for r in refs:
        for k in r['_keys']:
            if len(k) >= 3 and k in project and len(k) > best_len:
                best, best_len = r, len(k)
    return best


def competing_park(acc: dict, target: dict, refs: list[dict], country: list[str]) -> dict | None:
    """账号若明确指向【另一个】园区的专名，则返回该园区，用于纠正批量合并带来的串号。

    典型场景：抖音项目名是泛称（如「非洲最大商贸城」），一批账号被整批并入某园区，
    但其中部分账号的昵称/签名写的是另一个园区的专名（如「安哥拉中国城」）。
    """
    text = f"{acc.get('nickname') or ''} {acc.get('signature') or ''}"
    if not text.strip():
        return None
    tgt_keys = set(target.get('_keys', [])) | {target['canonical']}
    for r in refs:
        if r['canonical'] == target['canonical']:
            continue
        if not country_match(country or [], r['country']):
            continue
        for k in r.get('_keys', []):
            if len(k) < 3 or k not in text:
                continue
            # 目标园区自身的别名字样优先（避免 "安哥拉世纪城" 被 "中国城" 抢走）
            if any(t and t in text for t in tgt_keys):
                return None
            return r
    return None


def account_country_conflict(acc: dict, ref: dict) -> bool:
    """账号国别与园区国别冲突判定（2026-09-17 新增）。

    背景：项目名层面匹配成功（如抖音项目组「中达工业园」）时，整组账号会被一并挂到园区。
    若组内某账号的昵称/签名**明确写了另一个非洲国家**、且**不含园区专名、也不含园区所在国**，
    说明是项目组打包带来的串号（实测：乌干达「盛唐机械」被挂进坦桑尼亚中达工业园）。
    这类账号必须剔出，否则会让「抖音无号」的园区被伪造成「有号」。
    """
    text = f"{acc.get('nickname') or ''} {acc.get('signature') or ''}"
    rc = (ref.get('country') or '').strip()
    if not text.strip() or not rc:
        return False
    # 命中园区专名（≥3字）→ 强证据，不判冲突
    for k in ref.get('_keys', []):
        if len(k) >= 3 and k in text:
            return False
    def _same(c: str) -> bool:
        return c in rc or rc in c or (len(c) >= 2 and len(rc) >= 2 and c[:2] == rc[:2])
    # 文本出现与园区国别兼容的国家词 → 不冲突
    if rc in text or any((c in text and _same(c)) for c in COUNTRIES):
        return False
    # 文本只出现不兼容的非洲国家 → 判冲突
    return any((c in text and not _same(c)) for c in COUNTRIES)


def reassign_misattributed(verified: dict, refs: list[dict]) -> list[dict]:
    """扫描已核验园区的账号，把串号的账号迁到其真正所属的园区。返回迁移记录。"""
    moves = []
    for canon in list(verified.keys()):
        rec = verified[canon]
        target = next((x for x in refs if x['canonical'] == canon), None)
        if target is None:
            continue
        keep, moved_map = [], {}
        for a in rec['accounts']:
            other = competing_park(a, target, refs, [rec.get('country')])
            if other is None:
                keep.append(a)
                continue
            dest = verified.setdefault(other['canonical'], mk_rec(other))
            dest['accounts'].append(a)
            dest['_raw_names'].append(f"{canon}(串号纠正)")
            moved_map[other['canonical']] = moved_map.get(other['canonical'], 0) + 1
        if moved_map:
            rec['accounts'] = keep
            for dest_canon, cnt in moved_map.items():
                moves.append({'from': canon, 'to': dest_canon, 'count': cnt})
    return moves


def is_noise(name: str) -> bool:
    """营销话术/泛称噪音：如『还做海外仓』『本地市场』『为您打通中东市场』"""
    for v in NOISE_VERB:
        if name.startswith(v):
            return True
    # 纯 "X市场/X海外仓" 且 X 是国家/泛词（无专名）
    m = re.fullmatch(r'([\u4e00-\u9fa5A-Za-z0-9]{1,8})(市场|海外仓|仓库|展厅|渠道)', name)
    if m:
        return True
    return False


def is_entity(name: str) -> bool:
    return any(s in name for s in ENTITY_SUFFIX) and len(name) >= 3


def norm_douyin_name(name: str) -> str:
    """抖音线索名归一：去国家前缀/去大小写/去残词"""
    n = name.lower().replace('epz', 'EPZ')
    for c in COUNTRIES:
        n = n.replace(c, '')
    n = re.sub(r'^[u\r资内日及成业洲东非]{1,4}', '', n)
    n = re.sub(r'^[\u4e00-\u9fa5]{1,4}的', '', n)
    return n.strip() or name


def main():
    refs = load_reference()
    master = json.load(open(MASTER_FILE, encoding='utf-8'))
    projs = master['projects']

    verified = {}   # canonical -> rec
    douyin_map = {}  # norm_name -> rec
    noise = []

    def account_of(p):
        return p.get('accounts', []) or [{'nickname': p.get('project')}]

    misfits = []   # 2026-09-17：项目组打包导致的国别串号账号

    def split_by_country(accs, ref):
        """把国别明显冲突的账号从项目中剔出，返回 (保留, 剔除)"""
        keep, drop = [], []
        for a in accs:
            (drop if account_country_conflict(a, ref) else keep).append(a)
        for a in drop:
            misfits.append({'nickname': a.get('nickname'), 'sec_uid': a.get('sec_uid'),
                            'park': ref['canonical'], 'park_country': ref.get('country'),
                            'why': '账号昵称/签名指向其他非洲国家，与园区国别不符'})
        return keep, drop

    for p in projs:
        raw = p['project']
        ctry = p.get('countries') or []
        accs = account_of(p)

        # 1) 手动映射
        man = MANUAL_MAP.get(raw)
        if man:
            key = man
            r = next((x for x in refs if x['canonical'] == key), None)
            if r:
                verified.setdefault(key, mk_rec(r))
                rec = verified[key]
                _k, _d = split_by_country(accs, r)
                rec['douyin_hits'] += p['account_count'] - len(_d)
                rec['accounts'].extend(_k)
                rec['_raw_names'].append(raw)
                continue

        # 1.5) 特殊规则（含国家限定）
        sp = None
        for kw, ctry_kw, canon in SPECIAL_RULES:
            if kw in raw and (not ctry_kw or any(c in ctry_kw or ctry_kw in c for c in ctry)):
                sp = next((x for x in refs if x['canonical'] == canon), None)
                if sp:
                    break
        if sp:
            key = sp['canonical']
            verified.setdefault(key, mk_rec(sp))
            rec = verified[key]
            _k, _d = split_by_country(accs, sp)
            rec['douyin_hits'] += p['account_count'] - len(_d)
            rec['accounts'].extend(_k)
            rec['_raw_names'].append(raw)
            continue

        # 2) 账号昵称强归属（官方号：安哥拉世纪城 / 中乌辽沈工业园 ...）
        nick_r = None
        for a in accs:
            nick_r = nick_hits_reference(a.get('nickname') or '', refs)
            if nick_r:
                break
        if nick_r and country_match(ctry, nick_r['country']):
            key = nick_r['canonical']
            verified.setdefault(key, mk_rec(nick_r))
            rec = verified[key]
            rec['douyin_hits'] += p['account_count']
            rec['accounts'].extend(accs)
            rec['_raw_names'].append(raw)
            continue

        # 3) 项目名关键词匹配
        pr = proj_hits_reference(raw, refs)
        if pr and country_match(ctry, pr['country']):
            key = pr['canonical']
            verified.setdefault(key, mk_rec(pr))
            rec = verified[key]
            _k, _d = split_by_country(accs, pr)
            rec['douyin_hits'] += p['account_count'] - len(_d)
            rec['accounts'].extend(_k)
            rec['_raw_names'].append(raw)
            continue

        # 4) 噪音剔除
        is_foreign = any(f in raw for f in FOREIGN_PARK)
        if is_noise(raw) or (not is_entity(raw)) or raw.startswith(DOMESTIC_CITY) or is_foreign:
            why = ('非非洲地区园区' if is_foreign else
                   '国内实体误标非洲' if raw.startswith(DOMESTIC_CITY) else
                   ('营销话术/泛称无专名' if is_noise(raw) else '无实体专名'))
            noise.append({'project': raw, 'country': ctry, 'accounts': p['account_count'],
                          'why': why})
            continue

        # 5) 仅抖音线索（名称归一后合并）
        key = norm_douyin_name(raw) or raw
        rec = douyin_map.setdefault(key, {
            'project': key, 'name': key, 'canonical': '', 'raw_names': [],
            'country': list(dict.fromkeys(ctry)),
            'type': p.get('types', []), 'douyin_hits': 0, 'accounts': []})
        rec['douyin_hits'] += p['account_count']
        rec['raw_names'].append(raw)
        rec['accounts'].extend(accs)
        rec['country'] = list(dict.fromkeys(rec['country'] + ctry))

    # 2.5) 串号纠正：泛称项目名整批并入后，按账号专名迁回真正所属园区
    moves = reassign_misattributed(verified, refs)
    for m in moves:
        print(f"   ↪ 串号纠正：{m['count']} 个账号 {m['from']} → {m['to']}")

    # 去重账号
    for rec in [*verified.values(), *douyin_map.values()]:
        seen, accs = set(), []
        for a in rec['accounts']:
            k = a.get('sec_uid')
            if k and k in seen:
                continue
            if k:
                seen.add(k)
            accs.append(a)
        rec['accounts'] = accs
        rec['_raw_names'] = list(dict.fromkeys(rec.get('_raw_names', [])))

    # 2.6) 基准库已有账号的园区直接并入 verified
    # 背景：这些园区的抖音账号来自历史反向补搜，昵称不含泛搜关键词，当日泛搜捞不到；
    # 但它们有公开资料 evidence_level，且 douyin_accounts 已人工确认 → 属「公开可查证」，
    # 不应因当日搜索未复现而被降级到第五段、也不该被漏出核心清单。
    merged_from_ref = []
    for r in refs:
        canon = r['canonical']
        if canon in verified:
            continue
        accs = r.get('douyin_accounts') or []
        if str(r.get('douyin_found')).lower() not in ('yes', 'true', '1') or not accs:
            continue
        rec = mk_rec(r)
        rec['accounts'] = list(accs)
        rec['douyin_hits'] = len(accs)
        rec['_raw_names'] = []
        rec['from_reference_db'] = True
        verified[canon] = rec
        merged_from_ref.append(canon)
    for c in merged_from_ref:
        print(f"   ⤵ 基准库并入：{c}（账号来自历史补搜，本轮泛搜未复现）")

    # 5.5) 仅抖音线索二次合并：抖音侧同一个项目常被切成多个残名条目
    #     （如「雅普化工工业园」与「范围主要从事化工工业园」），ds 造成计数虚高。
    #     判据：① 名字互为包含关系（长度≥4）② 账号 sec_uid 集合有交集
    #     两者居其一即合并到更长更完整的名字上。
    def _merge_douyin_map(dmap):
        keys = sorted(dmap.keys(), key=len, reverse=True)
        merged = []
        for k in list(keys):
            if k not in dmap:
                continue
            for other in keys:
                if other == k or other not in dmap:
                    continue
                if len(other) >= len(k):
                    continue
                same_entity = (len(other) >= 4 and other in k)
                if not same_entity:
                    su_k = {a.get('sec_uid') for a in dmap[k]['accounts'] if a.get('sec_uid')}
                    su_o = {a.get('sec_uid') for a in dmap[other]['accounts'] if a.get('sec_uid')}
                    same_entity = bool(su_k and su_o and (su_k & su_o))
                if same_entity:
                    tgt = dmap[k]
                    tgt['raw_names'].extend(dmap[other].get('raw_names', []) or [other])
                    tgt['accounts'].extend(dmap[other]['accounts'])
                    tgt['country'] = list(dict.fromkeys(tgt['country'] + dmap[other]['country']))
                    merged.append(f"{other} → {k}")
                    del dmap[other]
        for rec in dmap.values():
            rec['raw_names'] = list(dict.fromkeys(rec.get('raw_names') or []))
            seen, accs = set(), []
            for a in rec['accounts']:
                s = a.get('sec_uid')
                if s and s in seen:
                    continue
                if s:
                    seen.add(s)
                accs.append(a)
            rec['accounts'] = accs
            rec['douyin_hits'] = len(accs)
        return merged

    for m in _merge_douyin_map(douyin_map):
        print(f"   ⇢ 线索合并：{m}")

    # 5.6) 空壳剔除：账号被串号纠正/国别剔除搬空后，园区不应继续挂「已核验」的名义，
    #      否则会在主清单里留下 0 账号的假条目，并让真正待补搜的园区永久不进种子池。
    emptied = []
    for canon in list(verified.keys()):
        rec = verified[canon]
        if not rec.get('accounts') and not rec.get('from_reference_db'):
            verified.pop(canon)
            emptied.append(canon)
    for c in emptied:
        print(f"   ⌀ 空壳剔除（0 账号，回落待补搜）：{c}")

    for mf in misfits:
        print(f"   ✂ 国别冲突剔除：{mf['nickname']} ← {mf['park']}（{mf['park_country']}）")

    douyin_only = sorted(douyin_map.values(), key=lambda x: -x['douyin_hits'])

    out = {
        'updated': __import__('time').strftime('%Y-%m-%d %H:%M'),
        'method': '公开资料基准库(africa_parks_reference.json)交叉核验：专名匹配+账号归属+噪音剔除',
        'summary': {
            'matched_to_public_reference': len(verified),
            'douyin_only_leads': len(douyin_only),
            'noise_filtered': len(noise),
            'reference_parks_not_found_on_douyin': len([r for r in refs if r['canonical'] not in verified]),
            'reference_parks_pending_reverse_search': len([r for r in refs if r['canonical'] not in verified and not r.get('douyin_found')]),
            'country_misfit_accounts_dropped': len(misfits),
        },
        'country_misfits': misfits,
        'verified': sorted(verified.values(), key=lambda x: (x['evidence_level'], -x['douyin_hits'])),
        'douyin_only': douyin_only,
        'noise': noise,
        'not_found_on_douyin': [{
            'canonical': r['canonical'], 'country': r['country'], 'type': r['type'],
            'evidence_level': r['evidence_level'], 'operator': r.get('operator', ''),
            'facts': r.get('facts', ''),
        } for r in refs if r['canonical'] not in verified and not r.get('douyin_found')],
        'reverse_searched_no_accounts': [{
            'canonical': r['canonical'], 'country': r['country'], 'type': r['type'],
            'evidence_level': r['evidence_level'], 'operator': r.get('operator', ''),
            'facts': r.get('facts', ''),
        } for r in refs if r['canonical'] not in verified and r.get('douyin_found') == 'no'],
        'reverse_searched_with_accounts': [{
            'canonical': r['canonical'], 'country': r['country'], 'type': r['type'],
            'evidence_level': r['evidence_level'], 'operator': r.get('operator', ''),
            'facts': r.get('facts', ''), 'accounts': r.get('douyin_accounts', []),
        } for r in refs if r['canonical'] not in verified and r.get('douyin_found') == 'yes'],
    }
    jf = DISCOVERY_DIR / 'projects_verified.json'
    jf.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    write_md(out, verified, douyin_only, noise)
    print(f"✅ 核验完成：公开可查证 {len(verified)} | 仅抖音线索 {len(douyin_only)} | 噪音剔除 {len(noise)}")
    for r in sorted(verified.values(), key=lambda x: (x['evidence_level'], -x['douyin_hits'])):
        print(f"  [{r['evidence_level']}] {r['canonical']} ({r['country']}) 抖音{r['douyin_hits']}号")


def mk_rec(r: dict) -> dict:
    return {
        'canonical': r['canonical'], 'country': r['country'], 'type': r['type'],
        'evidence_level': r['evidence_level'], 'operator': r.get('operator', ''),
        'facts': r.get('facts', ''), 'sources': r.get('sources', []),
        'aliases': r.get('aliases', []), 'douyin_hits': 0, 'accounts': [], '_raw_names': [],
        'from_reference_db': False}


def write_md(out, verified, douyin_only, noise):
    fmt = lambda n: f"{n/10000:.1f}万" if n and n >= 10000 else (str(n) if n else '-')
    lv_name = {'A': '商务部确认', 'B': '政府/权威媒体', 'C': '公开报道可查'}
    md = ["# 非洲中资园区/商贸城 项目核验主清单（公开资料去重版）\n",
          f"> 更新时间：{__import__('time').strftime('%Y-%m-%d %H:%M')}",
          "> 方法：抖音线索 ↔ 公开资料基准库(africa_parks_reference.json) 交叉核验 · 同一实体合并 · 噪音剔除\n",
          f"**核验结果**：公开可查证 **{len(verified)}** 个 | 仅抖音线索 **{len(douyin_only)}** 个 | 噪音剔除 **{len(noise)}** 条\n",
          "## 一、公开资料可查证项目（核心清单）\n",
          "| # | 标准名 | 国家 | 类型 | 证据 | 抖音账号数 | 头部账号 | 关键事实 |",
          "|---|--------|------|------|------|----------|---------|---------|"]
    vlist = sorted(verified.values(), key=lambda x: (x['evidence_level'], -x['douyin_hits']))
    for i, r in enumerate(vlist, 1):
        top = max(r['accounts'], key=lambda a: a.get('followers') or 0) if r['accounts'] else {}
        facts = r['facts'][:55].replace('|', '\\|')
        md.append(f"| {i} | **{r['canonical']}** | {r['country']} | {r['type']} | "
                  f"{lv_name.get(r['evidence_level'], r['evidence_level'])} | {r['douyin_hits']} | "
                  f"{top.get('nickname','-')} | {facts} |")

    md.append("\n### 明细（抖音账号 × 公开来源）\n")
    for i, r in enumerate(vlist, 1):
        md.append(f"#### {i}. {r['canonical']}　`{r['country']}`　`{r['type']}`　`{lv_name.get(r['evidence_level'], r['evidence_level'])}`")
        raw = ('、'.join(r['_raw_names'][:6]) if r['_raw_names']
               else ('基准库已有账号（本轮泛搜未复现）' if r.get('from_reference_db') else '-'))
        md.append(f"- 抖音原始名：{raw}")
        md.append(f"- 运营方：{r['operator'] or '-'}")
        if r['accounts']:
            md.append("| 抖音账号 | 粉丝 | 签名 |")
            md.append("|---|---|---|")
            for a in r['accounts'][:6]:
                md.append(f"| {a['nickname']} | {fmt(a.get('followers'))} | {(a.get('signature') or '')[:36]} |")
        md.append(f"- 公开事实：{r['facts']}")
        md.append(f"- 公开来源：{'；'.join(r['sources'][:3])}\n")

    md.append("## 二、仅抖音线索（未匹配公开基准库，需逐条核验）\n")
    md.append("| # | 线索名 | 国家 | 类型 | 抖音账号数 | 头部账号 | 抖音原始名 |")
    md.append("|---|--------|------|------|----------|---------|-----------|")
    for i, r in enumerate(douyin_only, 1):
        top = max(r['accounts'], key=lambda a: a.get('followers') or 0) if r['accounts'] else {}
        t = '/'.join(r['type']) if isinstance(r['type'], list) else r['type']
        md.append(f"| {i} | {r['project']} | {'/'.join(r['country'])} | {t} | "
                  f"{r['douyin_hits']} | {top.get('nickname','-')} | {'、'.join(r['raw_names'][:3])} |")

    md.append("\n## 三、剔除的营销话术噪音（不作为项目）\n")
    md.append("| 抖音原始项目名 | 国家 | 账号数 | 判噪理由 |")
    md.append("|---|---|---|---|")
    for i, n in enumerate(noise[:40], 1):
        md.append(f"| {n['project']} | {'/'.join(n['country'])} | {n['accounts']} | {n['why']} |")

    # 基准库有公开资料、但抖音尚未发现的 → 反向补搜线索
    nf = [r for r in out['not_found_on_douyin']]
    if nf:
        md.append("\n## 四、公开资料存在、抖音泛搜未命中（反向补搜种子）\n")
        md.append("这些项目在商务部名录/权威报道中确凿存在。已反向补搜过的(douyin_found标记)不重复列出。\n")
        md.append("| # | 标准名 | 国家 | 类型 | 证据 | 运营方 | 关键事实 |")
        md.append("|---|--------|------|------|------|--------|---------|")
        for i, r in enumerate(sorted(nf, key=lambda x: x['evidence_level']), 1):
            md.append(f"| {i} | **{r['canonical']}** | {r['country']} | {r['type']} | "
                      f"{lv_name.get(r['evidence_level'], r['evidence_level'])} | {r['operator'] or '-'} | "
                      f"{r['facts'][:55].replace('|', '\\|')} |")
    # 已补搜过、结论为无号的园区单列提示（避免误解为漏网）
    searched_no = out.get('reverse_searched_no_accounts', [])
    if searched_no:
        md.append("\n> 已反向补搜确认**无抖音运营账号**：" +
                  '、'.join(r['canonical'] for r in sorted(searched_no, key=lambda x: x['country'])) + "\n")
    # 反向补搜找到账号、但泛搜未匹配 master 的园区（账号在基准库 douyin_accounts 字段）
    searched_yes = out.get('reverse_searched_with_accounts', [])
    if searched_yes:
        md.append("\n## 五、反向补搜发现账号的园区（账号已入基准库 douyin_accounts）\n")
        md.append("泛搜未命中但这些园区在抖音有官方/入驻/关联账号，见基准库对应条目 douyin_accounts 字段。\n")
        md.append("| 标准名 | 国家 | 账号数 | 代表账号 |")
        md.append("|---|---|---|---|")
        for r in sorted(searched_yes, key=lambda x: x['country']):
            top = r['accounts'][0]['nickname'] if r.get('accounts') else '-'
            md.append(f"| {r['canonical']} | {r['country']} | {len(r['accounts'])} | {top} |")

    mf = DISCOVERY_DIR / 'projects_verified.md'
    mf.write_text('\n'.join(md), encoding='utf-8')
    # 归档文件名用当天日期，避免硬编码日期被新版本覆盖（历史遗留的 _2026-09-02 为硬编码产物）
    from datetime import date
    today = date.today().isoformat()
    (ARCHIVE_DIR / f'【核验】非洲中资园区_公开资料去重主清单_{today}.md').write_text('\n'.join(md), encoding='utf-8')


if __name__ == '__main__':
    main()
