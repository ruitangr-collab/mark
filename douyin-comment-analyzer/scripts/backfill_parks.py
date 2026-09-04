#!/usr/bin/env python3
"""把 reconcile 产出的 verified 园区账号回填进 africa_parks_reference.json。

规则（专名+国家+运营方 三重判定）：
- 匹配主体：reconcile_projects.py 已用「专名关键词」把账号归到园区，本脚本只做角色判定与去重回填
- 角色判定：official(官方/招商/运营) > tenant(入驻商户) > personal(个人生活博主) > unknown
- 去重：按 sec_uid；已回填过的园区（douyin_found 非 None）只补新账号，不覆盖原有标注
- 同时把 official/tenant 属性账号追加进 parks_watchlist.json（按 sec_uid 去重）
"""
import json
import re
from datetime import date
from pathlib import Path

ARCHIVE = Path.home() / ".workbuddy/douyin_analysis/_archive"
DISCOVERY = Path.home() / ".workbuddy/douyin_analysis/_discovery"
TODAY = date.today().isoformat()

OFFICIAL_PAT = re.compile(
    r"官方|招商|运营|管委会|有限公司|集团|投资|development|自贸区|合作区|产业园$|工业园$|商贸城$|中国城$",
    re.I)
PERSONAL_PAT = re.compile(
    r"生活|日常|vlog|记录|随手|打工|厨师|司机|保姆|相亲|恋爱|旅游|见闻|民宿|美食|钓鱼|高尔夫",
    re.I)
CONTACT_PAT = re.compile(r"微信|V[:：]|wechat|whatsapp|电话|TEL|联系", re.I)


def role_of(acc: dict, park: dict) -> str:
    nick = acc.get("nickname") or ""
    sig = acc.get("signature") or ""
    text = nick + " " + sig
    operator = park.get("operator") or ""
    # 官方/招商：昵称或签名含运营方名，或含招商/官方/管委会等强信号
    op_key = re.split(r"[（(]", operator)[0] if operator else ""
    if op_key and len(op_key) >= 3 and op_key in text:
        return "official"
    if OFFICIAL_PAT.search(text):
        return "official"
    if CONTACT_PAT.search(sig) or re.search(r"店|铺|档口|批发|零售|专营|总代|实体店", text):
        return "tenant"
    if PERSONAL_PAT.search(text):
        return "personal"
    return "unknown"


def main():
    ref = json.load(open(ARCHIVE / "africa_parks_reference.json", encoding="utf-8"))
    ver = json.load(open(DISCOVERY / "projects_verified.json", encoding="utf-8"))
    by_canon = {p["canonical"]: p for p in ref["parks"]}

    wl = json.load(open(ARCHIVE / "parks_watchlist.json", encoding="utf-8"))
    wl_secs = {a["sec_uid"] for a in wl.get("accounts", [])}

    backfilled, new_accounts, watch_added = [], 0, []

    for v in ver["verified"]:
        park = by_canon.get(v["canonical"])
        if park is None:
            continue
        was_unmarked = park.get("douyin_found") is None

        existing = {a["sec_uid"]: a for a in (park.get("douyin_accounts") or [])}
        for acc in v.get("accounts", []):
            su = acc.get("sec_uid")
            if not su or su in existing:
                continue
            role = role_of(acc, v)
            existing[su] = {
                "nickname": acc.get("nickname"),
                "sec_uid": su,
                "followers": acc.get("followers", 0),
                "signature": (acc.get("signature") or "")[:120],
                "role": role,
                "found_date": TODAY,
                "found_via": "泛搜匹配" if was_unmarked else "补搜",
            }
            new_accounts += 1
            if role in ("official", "tenant") and su not in wl_secs:
                wl_secs.add(su)
                wl.setdefault("accounts", []).append({
                    "nickname": acc.get("nickname"),
                    "sec_uid": su,
                    "park": v["canonical"],
                    "country": v["country"],
                    "role": role,
                    "followers": acc.get("followers", 0),
                    "added_date": TODAY,
                    "last_crawled": "",
                })
                watch_added.append(f"{v['canonical']} / {acc.get('nickname')} ({role})")

        park["douyin_accounts"] = list(existing.values())
        if was_unmarked:
            park["douyin_found"] = "yes" if existing else "no"
            park["douyin_found_date"] = TODAY
            backfilled.append(
                f"{v['canonical']} ({v['country']}) → {len(existing)} 账号")

    ref["updated"] = f"{TODAY} (回填泛搜命中账号)"
    json.dump(ref, open(ARCHIVE / "africa_parks_reference.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    wl["updated"] = TODAY
    json.dump(wl, open(ARCHIVE / "parks_watchlist.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"✅ 回填完成：{len(backfilled)} 个园区首次标记，新增 {new_accounts} 个账号")
    for b in backfilled:
        print("   -", b)
    print(f"✅ 监控名单新增 {len(watch_added)} 个官方/商户账号，现共 {len(wl.get('accounts', []))} 个")
    for w in watch_added[:20]:
        print("   +", w)


if __name__ == "__main__":
    main()
