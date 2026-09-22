#!/usr/bin/env python3
"""离线自检：不碰浏览器，只验证判新逻辑、解析器与报告渲染。

存在的理由：CDP 取数部分需要登录态，无法在 CI/离线环境下回归；
而判新逻辑恰恰是本技能最容易改坏的地方（抖音版为此积累过 21 条踩坑）。
所以把「不依赖网络」的部分全部覆盖掉。

跑法：
    python scripts/_selftest.py
"""

from __future__ import annotations

import argparse
import io
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}{(' — ' + extra) if extra and not cond else ''}")


def fresh_db() -> sqlite3.Connection:
    """指向一个临时库，绝不碰真实 monitor.db。"""
    tmp = tempfile.mkdtemp(prefix="xhs_selftest_")
    monitor.DATA_DIR = tmp
    monitor.REPORT_DIR = os.path.join(tmp, "reports")
    monitor.DB_PATH = os.path.join(tmp, "monitor.db")
    return monitor.connect()


# ---------------------------------------------------------------------------


def test_parse_count() -> None:
    print("\n[1] parse_count 数值解析")
    check("裸数字", monitor.parse_count("1234") == 1234)
    check("千分位", monitor.parse_count("12,340") == 12340)
    check("万", monitor.parse_count("1.2万") == 12000)
    check("亿", monitor.parse_count("1.5亿") == 150_000_000)
    check("已是 int", monitor.parse_count(88) == 88)
    check("破折号 → None", monitor.parse_count("-") is None)
    check("None 透传", monitor.parse_count(None) is None)
    check("空串 → None", monitor.parse_count("") is None)
    check("带前缀文本", monitor.parse_count("点赞 3.4万") == 34000)
    check("w 后缀", monitor.parse_count("2w") == 20000)


def test_extract_ids() -> None:
    print("\n[2] 链接 / 口令解析")
    u = "https://www.xiaohongshu.com/user/profile/5f1a2b3c4d5e6f7a8b9c0d1e?xsec_token=ABC"
    check("主页链接取 user_id", monitor.extract_user_id(u) == "5f1a2b3c4d5e6f7a8b9c0d1e")
    n = "https://www.xiaohongshu.com/explore/66554433221100aabbccddee?xsec_token=XY"
    check("笔记链接取 note_id", monitor.extract_note_id(n) == "66554433221100aabbccddee")
    check("错链接返回 None", monitor.extract_user_id("https://example.com") is None)
    uid, nid = monitor.resolve_target(u)
    check("resolve_target 主页", uid == "5f1a2b3c4d5e6f7a8b9c0d1e" and nid is None)
    uid2, nid2 = monitor.resolve_target(n)
    check("resolve_target 笔记", uid2 is None and nid2 == "66554433221100aabbccddee")


def test_note_detail_parse() -> None:
    print("\n[3] 详情解析（含小红书常见的字符串计数 / 毫秒时间戳）")
    detail = {
        "note": {
            "noteId": "abc123",
            "title": "阿比让找房避坑",
            "desc": "第一段\n\n第二段 #阿比让 #非洲",
            "type": "normal",
            "time": 1757000000000,
            "user": {"nickname": "非洲地产人"},
            "interactInfo": {
                "likedCount": "1.2万",
                "collectedCount": "3421",
                "commentCount": "128",
                "shareCount": "56",
            },
            "tagList": [{"name": "阿比让"}, {"name": "非洲"}],
        }
    }
    info = monitor.parse_note_detail(detail)
    check("noteId", info["note_id"] == "abc123")
    check("标题", info["title"] == "阿比让找房避坑")
    check("点赞 1.2万", info["likes"] == 12000)
    check("收藏", info["collects"] == 3421)
    check("评论", info["comments_cnt"] == 128)
    check("分享", info["shares"] == 56)
    check("发布时间格式", bool(info["publish_time"] and "-" in info["publish_time"]))
    check("标签", info["tags"] == "阿比让,非洲")
    check("作者", info["author"] == "非洲地产人")

    # 结构变动兜底：interactInfo 被挪到顶层也应能找到
    weird = {"note": {"noteId": "x", "title": "t", "likedCount": "99"}}
    check("结构变动兜底（_dig 搜索）", monitor.parse_note_detail(weird)["likes"] == 99)

    # 空 payload 不应崩
    empty = monitor.parse_note_detail({})
    check("空 payload 不崩", empty["note_id"] is None and empty["likes"] is None)


def test_is_stale() -> None:
    print("\n[4] freshness 复核（防线 2）")
    from datetime import datetime, timedelta

    old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M")
    new = datetime.now().strftime("%Y-%m-%d %H:%M")
    check("90 天前 → 判为陈旧", monitor._is_stale(old) is True)
    check("今天 → 不判陈旧", monitor._is_stale(new) is False)
    check("时间缺失 → 不判（宁可放过不误杀）", monitor._is_stale(None) is False)
    check("时间格式异常 → 不判", monitor._is_stale("昨天") is False)


def test_judge_new() -> None:
    """三道防线 + 「入队不设预算、抓详情才设预算」的核心不变量。"""
    print("\n[5] 判新三防线")
    conn = fresh_db()
    uid = "u" * 24
    conn.execute(
        """INSERT INTO accounts (user_id, nickname, followers, baselined, active)
           VALUES (?,?,?,1,1)""",
        (uid, "测试号", 1000),
    )
    conn.commit()

    def note(i: int) -> dict:
        nid = f"{i:024x}"
        return {"id": nid, "xsec_token": f"tok{i}", "title": f"笔记{i}", "cover": ""}

    def acc_row() -> sqlite3.Row:
        return conn.execute("SELECT * FROM accounts WHERE user_id=?", (uid,)).fetchone()

    def count(sql: str) -> int:
        return conn.execute(sql).fetchone()["c"]

    # —— 场景 A：头部窗口内的新 ID → 入队，本轮不报警 ——
    listed = [note(i) for i in range(1, 11)]
    ready, candidates = monitor._judge_new(conn, uid, acc_row(), listed, "run_a")
    check("A1 首轮确认 0 条（二次确认）", len(ready) == 0)
    check("A2 头部 8 条入队", len(candidates) == 8, f"实得 {len(candidates)}")
    check(
        "A3 队列条数 = 8",
        count("SELECT COUNT(*) c FROM notes WHERE seen_count=1 AND notified=0") == 8,
    )
    check(
        "A4 深部 2 条被压制",
        count("SELECT COUNT(*) c FROM notes WHERE suppressed='deep_position'") == 2,
    )

    # —— 场景 B：同一批再次出现 → 确认（但 notified 仍为 0，等详情抓完才写）——
    ready, candidates = monitor._judge_new(conn, uid, acc_row(), listed, "run_b")
    check("B1 二次确认 8 条", len(ready) == 8, f"实得 {len(ready)}")
    check("B2 本轮无新候选", len(candidates) == 0)
    # 关键不变量：notified=1 只能代表「详情已抓到并已报告」
    check(
        "B3 ⚠️ 确认后 notified 仍为 0（未抓详情不得标记已报）",
        count("SELECT COUNT(*) c FROM notes WHERE seen_count=2 AND notified=0") == 8,
        f"实得 {count('SELECT COUNT(*) c FROM notes WHERE seen_count=2 AND notified=0')}",
    )

    # —— 场景 C：真新笔记出现在头部 → 同样走二次确认 ——
    listed2 = [note(99)] + listed
    ready, candidates = monitor._judge_new(conn, uid, acc_row(), listed2, "run_c")
    check("C1 新笔记不立即确认（只入队）", f"{99:024x}" not in ready)
    check("C2 新笔记入队", f"{99:024x}" in candidates)

    # —— 场景 D：下轮确认 ——
    ready, _ = monitor._judge_new(conn, uid, acc_row(), listed2, "run_d")
    check("D1 新笔记被确认", f"{99:024x}" in ready)

    # —— 场景 D2：欠账重试 ——
    # 场景 B/D 里那 8+1 条已确认但 notified 仍为 0（模拟详情抓取失败）。
    # 若下轮不把它们重新带出来，就会永久卡在未报告状态（抖音坑 14 同类错误）。
    conn.execute("UPDATE notes SET notified=1 WHERE note_id=?", (f"{99:024x}",))
    conn.commit()
    ready, _ = monitor._judge_new(conn, uid, acc_row(), listed2, "run_d2")
    backlog_n = sum(1 for nid in ready if nid != f"{99:024x}")
    check("D2 ⚠️ 上轮详情失败的笔记被重新带出（欠账重试）", backlog_n == 8, f"实得 {backlog_n}")
    check("D3 已报告的笔记不再重试", f"{99:024x}" not in ready)

    # —— 场景 E：入队不设预算，只靠头部窗口自然限流 ——
    conn2 = fresh_db()
    conn2.execute(
        "INSERT INTO accounts (user_id, nickname, baselined, active) VALUES (?,?,1,1)",
        (uid, "宽窗号"),
    )
    conn2.commit()
    many = [note(i) for i in range(500, 540)]
    acc2 = conn2.execute("SELECT * FROM accounts WHERE user_id=?", (uid,)).fetchone()
    _, cand2 = monitor._judge_new(conn2, uid, acc2, many, "run_e", head_window=30)
    check("E1 宽窗下入队 30 条（未被配额截断）", len(cand2) == 30, f"实得 {len(cand2)}")
    deep2 = conn2.execute(
        "SELECT COUNT(*) c FROM notes WHERE suppressed='deep_position'"
    ).fetchone()["c"]
    check("E2 窗外 10 条被压制", deep2 == 10, f"实得 {deep2}")
    # 配额概念已被移除，不应再有 quota_exceeded（那是会造成永久漏报的旧实现）
    qx = conn2.execute(
        "SELECT COUNT(*) c FROM notes WHERE suppressed='quota_exceeded'"
    ).fetchone()["c"]
    check("E3 不存在 quota_exceeded 永久压制（抖音坑14 的翻版已消除）", qx == 0)

    # —— 场景 F：未建基线的新账号 → 一律不报警 ——
    conn3 = fresh_db()
    uid3 = "z" * 24
    conn3.execute(
        "INSERT INTO accounts (user_id, nickname, baselined, active) VALUES (?,?,0,1)",
        (uid3, "新号"),
    )
    conn3.commit()
    acc3 = conn3.execute("SELECT * FROM accounts WHERE user_id=?", (uid3,)).fetchone()
    conf3, cand3 = monitor._judge_new(
        conn3, uid3, acc3, [note(i) for i in range(1, 20)], "run_f"
    )
    check("F1 基线轮零确认", len(conf3) == 0)
    check("F2 基线轮零候选", len(cand3) == 0)
    bl = conn3.execute(
        "SELECT COUNT(*) c FROM notes WHERE suppressed='baseline'"
    ).fetchone()["c"]
    check("F3 全部标为 baseline", bl == 19, f"实得 {bl}")

    conn.close()
    conn2.close()
    conn3.close()


def test_coalesce_protection() -> None:
    """详情抓取失败返回 None 时，绝不能抹掉已知值（对齐抖音坑 10）。"""
    print("\n[6] COALESCE 保护")
    conn = fresh_db()
    uid = "u" * 24
    conn.execute(
        "INSERT INTO accounts (user_id, nickname, baselined, active) VALUES (?,?,1,1)",
        (uid, "t"),
    )
    nid = "a" * 24
    conn.execute(
        """INSERT INTO notes (note_id, user_id, title, likes, collects, publish_time,
                              seen_count, notified)
           VALUES (?,?,?,?,?,?,2,1)""",
        (nid, uid, "原标题", 5000, 800, "2026-09-10 10:00"),
    )
    conn.commit()

    # 模拟一次风控/渲染失败：所有字段为空
    monitor.write_detail(conn, nid, {})
    row = conn.execute("SELECT * FROM notes WHERE note_id=?", (nid,)).fetchone()
    check("赞未被抹成 NULL", row["likes"] == 5000, f"实得 {row['likes']}")
    check("藏未被抹成 NULL", row["collects"] == 800)
    check("原标题保留", row["title"] == "原标题")
    check("原发布时间保留", row["publish_time"] == "2026-09-10 10:00")

    # 正常抓取应能更新
    monitor.write_detail(
        conn,
        nid,
        {"note": {"noteId": nid, "title": "新标题", "time": 1757000000000,
                  "interactInfo": {"likedCount": "9.9万"}}},
    )
    row = conn.execute("SELECT * FROM notes WHERE note_id=?", (nid,)).fetchone()
    check("正常抓取可更新", row["likes"] == 99000, f"实得 {row['likes']}")
    conn.close()


def test_baseline_and_reports() -> None:
    print("\n[7] 基线计算与报告渲染")
    conn = fresh_db()
    uid = "u" * 24
    conn.execute(
        "INSERT INTO accounts (user_id, nickname, baselined, active) VALUES (?,?,1,1)",
        (uid, "报告号"),
    )
    for i, likes in enumerate([100, 200, 300, 400, 5000]):
        conn.execute(
            """INSERT INTO notes (note_id, user_id, title, likes, collects,
                                  comments_cnt, content, publish_time,
                                  seen_count, notified, tags)
               VALUES (?,?,?,?,?,?,?,?,2,1,?)""",
            (
                f"{i:024x}", uid, f"笔记{i}", likes, likes // 5, 10,
                "第一段\n第二段\n第三段 #标签", "2026-09-10 10:00", "标签1,标签2",
            ),
        )
    for i, fans in enumerate([1000, 1050, 1120]):
        conn.execute(
            "INSERT INTO snapshots (user_id, captured_at, followers, liked, ok) "
            "VALUES (?,?,?,?,1)",
            (uid, f"2026-09-1{i} 04:00", fans, 9000 + i * 100),
        )
    conn.commit()

    med = monitor.recompute_baseline(conn, uid)
    check("中位数 = 300", med == 300.0, f"实得 {med}")
    check("baselined 置 1",
          conn.execute("SELECT baselined FROM accounts WHERE user_id=?", (uid,)).fetchone()[0] == 1)

    # 空点赞账号 → NULL 且不崩（对齐抖音坑 18）
    uid2 = "v" * 24
    conn.execute(
        "INSERT INTO accounts (user_id, nickname, baselined, active) VALUES (?,?,1,1)",
        (uid2, "无数据号"),
    )
    conn.commit()
    check("无点赞数据 → baseline 为 NULL", monitor.recompute_baseline(conn, uid2) is None)

    # 报告渲染
    import argparse
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_report(argparse.Namespace(user_id=uid))
    out = buf.getvalue()
    check("趋势报告含表头", "| 时间 | 粉丝 | 变化 |" in out)
    check("趋势报告含首行数据", "2026-09-10 04:00" in out)

    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_notes(argparse.Namespace(user_id=uid, n=10))
    out = buf.getvalue()
    check("排行含倍数", "16.7x" in out, out[:300])
    check("排行含藏赞比", "0.20" in out or "0.2" in out)

    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_list(argparse.Namespace())
    out = buf.getvalue()
    check("名单含账号", "报告号" in out)

    # 结构拆解：必须产出结构参数，且不得含正文原文
    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_matrix(argparse.Namespace(user_id=uid, n=5))
    out = buf.getvalue()
    check("matrix 含钩子类型列", "钩子类型" in out)
    check("matrix 含结构归纳", "钩子类型分布" in out)
    check("⚠️ matrix 不得出现正文原文", "第一段\n第二段" not in out and "第一段 第二段" not in out)
    check("matrix 含防抄袭声明", "不可复用表述" in out)

    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_opportunities(argparse.Namespace())
    out = buf.getvalue()
    check("opportunities 含样本统计", "样本：" in out)
    check("opportunities 含使用建议", "不要**拿代表账号的原文当参照物改写" in out.replace(" ", ""))

    conn.close()


def test_hook_classifier() -> None:
    print("\n[8] 钩子类型判定")
    cases = [
        ("3 个细节看出中介靠不靠谱", "", "数字锚点"),
        ("为什么阿比让的房租这么贵？", "", "疑问式"),
        ("千万别碰这种房子", "", "反常识/否定"),
        ("开店第一年我亏了多少钱", "", "结果前置"),
        ("今天天气不错", "", "陈述式"),
        # 回归：正文数字不得盖过标题的疑问句式
        (
            "为什么阿比让的仓库租金一年涨了 40%？",
            "很多人以为是我在抬价。清关周期从 7 天涨到 18 天，租金不涨才怪。",
            "疑问式",
        ),
        # 回归：标题判不出来时，正文头部兜底
        ("这周市场纪实", "千万别在这个时间点进货，我踩过。", "反常识/否定"),
    ]
    for title, content, expect in cases:
        got = monitor._hook_type(title, content)
        check(f"「{title[:16]}…」→ {expect}", got == expect, f"实得 {got}")


def test_geo_track() -> None:
    """地图赛道（geo_map）专属能力验证。

    这批测试守的是「赛道分档」这个改造的核心：同一批标题在服务号规则和
    地图号规则下必须给出不同判定，否则分档就是白做的。
    """
    print("\n[9] 地图赛道：钩子分档")
    # 同一条标题在两个赛道下应给出不同判定 —— 证明 track 参数真的生效
    t = "为什么阿比让的仓库租金涨了 40%？"
    svc = monitor._hook_type(t, "", "overseas_service")
    geo = monitor._hook_type(t, "", "geo_map")
    check("同标题在服务号轨道 → 疑问式", svc == "疑问式", f"实得 {svc}")
    check("同标题在地图轨道 → 数字锚点", geo == "数字锚点", f"实得 {geo}")
    check("两轨道判定确实不同", svc != geo)

    cases = [
        ("你以为非洲最穷的国家是哪个", "", "认知反差"),
        ("全网没人讲过的非洲出海逻辑", "", "稀缺信息"),
        ("全球最富的 10 个国家", "", "排名榜单"),
        ("科特迪瓦注册公司要多久", "", "投资视角"),
        ("为什么这个国家没有出海口", "", "地理特征"),
        ("一张图看懂西非 15 国的钱从哪来", "", "数字锚点"),
    ]
    for title, content, expect in cases:
        got = monitor._hook_type(title, content, "geo_map")
        check(f"「{title[:16]}…」→ {expect}", got == expect, f"实得 {got}")

    print("\n[10] 地图赛道：地理尺度判定")
    unit_cases = [
        ("全球 10 个最赚钱的新兴市场", "全球"),
        ("西非三国投资环境对比", "区域（西非）"),
        ("科特迪瓦和塞内加尔哪个更适合开厂", "多国并列"),
        ("看懂科特迪瓦的钱", "单国（科特迪瓦）"),
        ("阿比让的仓库租金为什么这么贵", "城市（阿比让）"),
        ("今天天气不错", "未判定"),
    ]
    for text, expect in unit_cases:
        got = monitor._geo_unit(text)
        check(f"「{text[:18]}…」→ {expect}", got == expect, f"实得 {got}")

    print("\n[11] 地图赛道：信息类型判定")
    info_cases = [
        ("西非有哪些投资机会", "机会"),
        ("在非洲开厂的 5 个坑", "风险"),
        ("全球 GDP 排名前 20 的国家", "数据排名"),
        ("越南 vs 印尼，工厂该放哪", "对比"),
        ("为什么这条河决定了三个国家的命运", "科普"),
    ]
    for text, expect in info_cases:
        got = monitor._info_type(text)
        check(f"「{text[:18]}…」→ {expect}", got == expect, f"实得 {got}")

    print("\n[12] 地图赛道：账号赛道自动判定")
    conn = fresh_db()
    geo_uid, svc_uid = "g" * 24, "s" * 24
    conn.execute(
        "INSERT INTO accounts (user_id,nickname,baselined,active) VALUES (?,?,1,1)",
        (geo_uid, "地图号"),
    )
    conn.execute(
        "INSERT INTO accounts (user_id,nickname,baselined,active) VALUES (?,?,1,1)",
        (svc_uid, "服务号"),
    )
    geo_notes = [
        ("全球最富的 10 个国家，第 3 个你绝对想不到", "地图 分布 各国 GDP 人口"),
        ("一张图看懂西非 15 国的钱从哪来", "地图 出海口 港口 资源"),
        ("为什么这个国家没有出海口", "地理 内陆国 边界 地图"),
        ("各国人均 GDP 排名，中国排第几", "全球 排行 数据 地图"),
        ("非洲 54 国资源分布一览", "地图 资源分布 国家"),
        ("阿比让的仓库租金为什么涨得这么快", "港口 物流 仓储 租金"),
    ]
    svc_notes = [
        ("在非洲开店第一年我亏了 80 万", "门店 客户 房租 亏"),
        ("千万别这样和非洲供应商谈账期", "外贸 合同 定金 客户"),
        ("3 个细节判断非洲客户是不是真买家", "客户 门店 中介"),
        ("本地员工管理我用这 3 个办法", "员工 管理 老板"),
        ("客户问我最多的问题", "客户 咨询 门店"),
    ]
    for i, (t, c) in enumerate(geo_notes):
        conn.execute(
            "INSERT INTO notes (note_id,user_id,title,content,likes,collects,seen_count) "
            "VALUES (?,?,?,?,?,?,2)",
            (f"g{i}".ljust(24, "0"), geo_uid, t, c, 1000, 400),
        )
    for i, (t, c) in enumerate(svc_notes):
        conn.execute(
            "INSERT INTO notes (note_id,user_id,title,content,likes,collects,seen_count) "
            "VALUES (?,?,?,?,?,?,2)",
            (f"s{i}".ljust(24, "0"), svc_uid, t, c, 1000, 200),
        )
    conn.commit()
    t1, why1 = monitor.detect_track(conn, geo_uid)
    t2, why2 = monitor.detect_track(conn, svc_uid)
    check("地图号被判为 geo_map", t1 == "geo_map", f"实得 {t1}（{why1}）")
    check("服务号被判为 overseas_service", t2 == "overseas_service", f"实得 {t2}（{why2}）")
    check("判定依据非空且可复核", bool(why1) and bool(why2))

    print("\n[13] 地图赛道：matrix 输出维度")
    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_matrix(argparse.Namespace(user_id=geo_uid, n=10, track="auto"))
    out = buf.getvalue()
    check("自动判出赛道并写进报告", "赛道判定：地理／投资地图" in out)
    check("含地理尺度列", "地理尺度" in out)
    check("含信息类型列", "信息类型" in out)
    check("含尺度×表现对照表", "尺度 × 表现对照" in out)
    check("含泛流量陷阱提示", "你要的客户在后一类" in out.replace("**", ""))
    check("城市尺度被识别", "城市（阿比让）" in out)

    print("\n[14] 地图赛道：opportunities 输出维度")
    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_opportunities(argparse.Namespace(track="geo_map"))
    out = buf.getvalue()
    check("含地理尺度×信息类型交叉表", "地理尺度 × 信息类型" in out)
    check("建议改为藏赞比优先", "优先看「藏赞比」" in out)
    check("含封面不可复用警告", "封面图／底图不可复用" in out)

    print("\n[15] 分类器健康度告警（兜底桶溢出）")
    conn2 = fresh_db()
    bad_uid = "b" * 24
    conn2.execute(
        "INSERT INTO accounts (user_id,nickname,baselined,active) VALUES (?,?,1,1)",
        (bad_uid, "判不出的号"),
    )
    for i in range(10):
        conn2.execute(
            "INSERT INTO notes (note_id,user_id,title,content,likes,collects,seen_count) "
            "VALUES (?,?,?,?,?,?,2)",
            (f"b{i}".ljust(24, "0"), bad_uid, "今天天气不错", "记录一下生活", 100, 10),
        )
    conn2.commit()
    buf = io.StringIO()
    with redirect_stdout(buf):
        monitor.cmd_matrix(argparse.Namespace(user_id=bad_uid, n=10, track="geo_map"))
    out = buf.getvalue()
    check("兜底桶溢出时给出告警", "分类器健康度告警" in out)

    conn.close()
    conn2.close()


def main() -> int:
    print("=" * 62)
    print("xhs-account-monitor 离线自检")
    print("=" * 62)
    test_parse_count()
    test_extract_ids()
    test_note_detail_parse()
    test_is_stale()
    test_judge_new()
    test_coalesce_protection()
    test_baseline_and_reports()
    test_hook_classifier()
    test_geo_track()

    print()
    print("=" * 62)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败清单：")
        for name in FAIL:
            print(f"  ❌ {name}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
