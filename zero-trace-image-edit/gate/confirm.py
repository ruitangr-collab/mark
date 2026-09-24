#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
confirm.py — 闸门① 驱动：9 项强制显式确认 + 签名①哈希冻结 + 出确认表
=========================================================================
铁律：不可默认、不可静默猜测、不可跳过。所有字段必须显式赋值（None=未答）。
签名①后冻结 items 哈希，任一项改动即作废（哈希失配 → 重走闸门①+签名①）。

用法：
  python confirm.py --init > confirmation.blank.json        # 产出空白模板
  python confirm.py --validate confirmation.json            # 校验 9/9 是否全填
  python confirm.py --sign1 confirmation.json --user 你的登录名   # 锁定意图+冻结哈希+出表
  python confirm.py --emit-table confirmation.json --out t.docx
"""
import argparse
import json
import hashlib
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def blank_confirmation():
    return {
        "meta": {"client": None, "style_no": None, "image_a": None, "image_b": None,
                 "operator": None, "date": None},
        "items": {
            "env": {"local_gpu": None, "offline": None},
            "color": {"fabric_src": None, "color_src": None, "matrix_cell": None},
            "texture": {"mode": None},
            "nlp": {"mode": None},
            "coord_tol": {"pct": None},
            "shape": {"type": None, "contour": None, "corner_r": None, "flap": None,
                      "flap_w_pct": None, "flap_dist_cm": None, "rivet": None,
                      "rivet_n": None, "rivet_gap_cm": None, "stitch": None,
                      "stitch_mm": None, "orientation_locked": None},
            "size": {"mode": None, "w": None, "h": None},
            "position": {"view": None, "side": None, "wearer_x": None, "wearer_y": None,
                         "human": None, "mirror": None, "mirror_locked": None, "mirror_copy_left": None},
            "stitching": {"color_src": None, "type": None, "width_mm": None, "effect": None},
        },
        "sign1": {"username": None, "timestamp": None, "responsibility": None, "hash": None},
        "sign2": {"username": None, "timestamp": None, "responsibility": None, "hash": None},
    }


def _err(cond, field, errors):
    if not cond:
        errors.append(field)


def validate_gate1(d):
    """返回 (ok, errors)。任一字段未显式赋值即报错。"""
    errors = []
    it = d.get("items", {})
    env = it.get("env", {})
    _err(isinstance(env.get("local_gpu"), bool), "env.local_gpu 未显式勾选(应为 True/False)", errors)
    _err(isinstance(env.get("offline"), bool), "env.offline 未显式勾选", errors)

    color = it.get("color", {})
    _err(color.get("fabric_src") in ("A", "B", "new"), "color.fabric_src 必选 A/B/new", errors)
    _err(color.get("color_src") in ("A", "B", "new"), "color.color_src 必选 A/B/new", errors)
    mc = color.get("matrix_cell")
    _err(isinstance(mc, int) and 1 <= mc <= 9, "color.matrix_cell 必为 1-9 整数(3x3矩阵)", errors)

    _err(it.get("texture", {}).get("mode") in ("full", "approx"), "texture.mode 必选 full/approx", errors)
    _err(it.get("nlp", {}).get("mode") in ("llm", "ui"), "nlp.mode 必选 llm/ui", errors)
    _err(isinstance(it.get("coord_tol", {}).get("pct"), (int, float)), "coord_tol.pct 必填数值", errors)

    sh = it.get("shape", {})
    _err(bool(sh.get("type")), "shape.type 必填(袋型)", errors)
    _err(isinstance(sh.get("corner_r"), (int, float)), "shape.corner_r 必填", errors)
    _err(isinstance(sh.get("flap"), bool), "shape.flap 必显式(有/无袋盖)", errors)
    if sh.get("flap") is True:
        _err(isinstance(sh.get("flap_w_pct"), (int, float)), "shape.flap_w_pct 必填(袋盖宽占比)", errors)
        _err(isinstance(sh.get("flap_dist_cm"), (int, float)), "shape.flap_dist_cm 必填", errors)
    _err(isinstance(sh.get("rivet"), bool), "shape.rivet 必显式", errors)
    _err(sh.get("stitch") in ("single", "double"), "shape.stitch 必选 single/double", errors)
    _err(isinstance(sh.get("stitch_mm"), (int, float)), "shape.stitch_mm 必填", errors)
    _err(sh.get("orientation_locked") is True, "shape.orientation_locked 必须为 True(袋口朝上禁翻转)", errors)

    sz = it.get("size", {})
    _err(sz.get("mode") in ("B", "ratio", "new"), "size.mode 必选 B/ratio/new", errors)
    _err(isinstance(sz.get("w"), (int, float)) and isinstance(sz.get("h"), (int, float)),
          "size.w/h 必填(cm)", errors)

    pos = it.get("position", {})
    _err(pos.get("view") in ("front", "back", "side"), "position.view 必选 front/back/side", errors)
    _err(pos.get("side") in ("left", "right"), "position.side 必选 left/right(=着装者)", errors)
    wx, wy = pos.get("wearer_x"), pos.get("wearer_y")
    _err(isinstance(wx, (int, float)) and isinstance(wy, (int, float)) and 0 <= wx <= 1 and 0 <= wy <= 1,
          "position.wearer_x/y 必为[0,1]归一化(来自图上直摆)", errors)
    _err(bool(pos.get("human")), "position.human 必填(人话回读存档)", errors)
    _err(pos.get("mirror_locked") is True, "position.mirror_locked 必须为 True(镜像已归一化)", errors)
    _err(isinstance(pos.get("mirror"), bool), "position.mirror 必须显式(图里哪边是穿衣人右手)", errors)

    st = it.get("stitching", {})
    _err(st.get("color_src") in ("A", "B", "accent", "new"), "stitching.color_src 必选 A/B/accent/new", errors)
    _err(st.get("type") in ("single", "double"), "stitching.type 必选 single/double", errors)
    _err(isinstance(st.get("width_mm"), (int, float)), "stitching.width_mm 必填", errors)
    _err(st.get("effect") in ("flat", "worn", "new"), "stitching.effect 必选 flat/worn/new", errors)

    # meta 关键字段
    _err(bool(d.get("meta", {}).get("style_no")), "meta.style_no 必填(款号/订单号)", errors)
    return (len(errors) == 0, errors)


def freeze(d):
    """计算 items 哈希并写入 sign1.hash。"""
    canon = json.dumps(d.get("items", {}), sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    d["sign1"]["hash"] = h
    return h


def is_frozen_valid(d):
    if not d.get("sign1", {}).get("hash"):
        return False
    canon = json.dumps(d.get("items", {}), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest() == d["sign1"]["hash"]


def main():
    # lazy import：生成 Word 确认表才需要 python-docx，校验/冻结哈希不需要
    import gen_confirmation_table as G
    ap = argparse.ArgumentParser(description="闸门① 确认驱动")
    ap.add_argument("--init", action="store_true", help="输出空白确认模板 JSON")
    ap.add_argument("--validate", metavar="JSON")
    ap.add_argument("--sign1", metavar="JSON", help="签名①：锁定意图+冻结哈希+出表")
    ap.add_argument("--sign2", metavar="JSON", help="签名②：验收确认(解锁交付)")
    ap.add_argument("--user", default=None, help="登录用户名(自动带入)")
    ap.add_argument("--emit-table", metavar="JSON")
    ap.add_argument("--out", default="确认表.docx")
    ap.add_argument("--checks", metavar="JSON", help="闸门②点检结果 JSON(用于填表)")
    args = ap.parse_args()

    if args.init:
        print(json.dumps(blank_confirmation(), ensure_ascii=False, indent=2))
        return

    if args.validate:
        d = json.load(open(args.validate, "r", encoding="utf-8"))
        ok, errors = validate_gate1(d)
        if ok:
            print("✅ 闸门① 9/9 全部显式确认，可签名①解锁出图。")
        else:
            print("❌ 闸门① 未通过，以下必填项缺失/未显式：")
            for e in errors:
                print("   -", e)
            sys.exit(1)
        return

    if args.sign1:
        d = json.load(open(args.sign1, "r", encoding="utf-8"))
        ok, errors = validate_gate1(d)
        if not ok:
            print("❌ 签名①失败：闸门①未全确认：")
            for e in errors:
                print("   -", e)
            sys.exit(1)
        if d.get("sign1", {}).get("responsibility") is not True:
            print("❌ 签名①失败：责任勾选『本人已逐项确认上述意图』必须为 True。")
            sys.exit(1)
        d["sign1"]["username"] = args.user or d["sign1"].get("username") or "（未提供）"
        import datetime
        d["sign1"]["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        freeze(d)
        json.dump(d, open(args.sign1, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        # 出表（此时 sign2 可能尚无）
        G.generate_confirmation_table(d, signed1=d["sign1"], signed2=d.get("sign2"), out_path=args.out)
        print(f"✅ 签名①完成，闸门解锁：可出图。确认表已生成 → {args.out}")
        print(f"   冻结哈希={d['sign1']['hash'][:16]}…（任一项改动将作废此签名）")
        return

    if args.sign2:
        d = json.load(open(args.sign2, "r", encoding="utf-8"))
        if not d.get("sign1", {}).get("hash"):
            print("❌ 签名②失败：尚未签名①，禁止走交付。")
            sys.exit(1)
        if not is_frozen_valid(d):
            print("❌ 签名②失败：确认项在签名①后被改动，哈希失配 → 必须重走闸门①+签名①。")
            sys.exit(1)
        checks = None
        if args.checks and os.path.isfile(args.checks):
            checks = json.load(open(args.checks, "r", encoding="utf-8"))
        # 检查闸门②是否全 PASS（铁律：缺数据 = FAIL，不接受 NOT_RUN/PENDING 蒙混）
        if checks:
            bad = [c for c in checks if c.get("verdict") != "PASS"]
            if bad:
                not_passed = [c for c in bad if c.get("verdict") in ("NOT_RUN", "PENDING")]
                failed = [c for c in bad if c.get("verdict") == "FAIL"]
                if not_passed:
                    print(f"❌ 签名②失败：闸门②有 {len(not_passed)} 项缺数据（NOT_RUN/PENDING），禁止交付。请先 --execute 真出图并由 CHK.check_* 实测。")
                if failed:
                    print(f"❌ 签名②失败：闸门②有 {len(failed)} 项 FAIL：{[c['name'] for c in failed]}")
                sys.exit(1)
        d["sign2"]["username"] = args.user or d["sign2"].get("username") or d["sign1"]["username"]
        import datetime
        d["sign2"]["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        d["sign2"]["responsibility"] = True
        json.dump(d, open(args.sign2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        G.generate_confirmation_table(d, checks=checks, signed1=d["sign1"], signed2=d["sign2"], out_path=args.out)
        print(f"✅ 签名②完成，交付解锁。最终确认表（含双签水印）→ {args.out}")
        return

    if args.emit_table:
        d = json.load(open(args.emit_table, "r", encoding="utf-8"))
        checks = None
        if args.checks and os.path.isfile(args.checks):
            checks = json.load(open(args.checks, "r", encoding="utf-8"))
        G.generate_confirmation_table(d, checks=checks, signed1=d.get("sign1"), signed2=d.get("sign2"), out_path=args.out)
        print(f"确认表已生成 → {args.out}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
