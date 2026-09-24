# -*- coding: utf-8 -*-
"""
移除部件专用点检（v3.2 新增）

用途：当任务类型是「结构改款·移除部件」（拆口袋/去装饰/删绣花）时，
      用「平整度（边缘强度下降）」判据验收，而不是「改动率」。

为什么要有这个脚本（PG-003 踩坑记录）：
  1. 用「改动率 ≥85%」判 → 假 FAIL。因为口袋分两类像素：
     缝线/袋盖（细线，占比小）+ 袋身平面（占比大，移除后≈周围裙面，差值极小）。
     移动平均算出来只有 10%，但缝线其实已经全没了。
  2. 检测出的「残留纵线」可能是衣物固有结构线（侧缝/公主线/腰省），
     不是被移除部件的轮廓。纯数值检测会把结构线算成残留 → 误判 FAIL。
     → 报残留前必须先放大目检确认。

正确判据：
  口袋本体（或任意被移除部件）的边缘强度 → 是否降到「干净面料基准」水平。
  出图边缘强度 / 干净面料边缘强度 ≤ 2.5 → PASS（越小越平）。

用法：
  python gate/check_removal.py --orig A.jpg --gen out.jpg \
      --part 0.055,0.345,0.300,0.630 --part 0.760,0.345,0.940,0.610 \
      --clean 0.40,0.45,0.60,0.75 --json report.json
  坐标均为画面比例 x0,y0,x1,y1。
"""
import os, sys, json, argparse
import numpy as np
from PIL import Image


def lum(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def grad_mag(a):
    """简易梯度幅值（4 邻域最大绝对差）"""
    l = lum(a)
    gx = np.zeros_like(l)
    gy = np.zeros_like(l)
    gx[:, :-1] = np.abs(np.diff(l, axis=1))
    gy[:-1, :] = np.abs(np.diff(l, axis=0))
    return np.maximum(gx, gy)


def parse_box(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("区域需 4 个比例值 x0,y0,x1,y1")
    return v


def main():
    ap = argparse.ArgumentParser(description="移除部件点检（平整度判据）")
    ap.add_argument("--orig", required=True, help="原图")
    ap.add_argument("--gen", required=True, help="出图（移除后）")
    ap.add_argument("--part", action="append", default=[], type=parse_box,
                    help="被移除部件区域 x0,y0,x1,y1（可重复，多个部件）")
    ap.add_argument("--clean", type=parse_box, default=[0.40, 0.45, 0.60, 0.75],
                    help="干净面料基准区 x0,y0,x1,y1（默认画面中偏下）")
    ap.add_argument("--tolerance", type=float, default=2.5,
                    help="判定阈值：出图/干净面 ≤ 该值算 PASS（默认 2.5）")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    o_img = Image.open(args.orig).convert("RGB")
    W, H = o_img.size
    g_img = Image.open(args.gen).convert("RGB").resize((W, H), Image.LANCZOS)
    o = np.asarray(o_img, dtype=np.float32)
    g = np.asarray(g_img, dtype=np.float32)
    go, gg = grad_mag(o), grad_mag(g)

    def region(m, box):
        x0, y0, x1, y1 = box
        return m[int(H*y0):int(H*y1), int(W*x0):int(W*x1)]

    clean_o = float(region(go, args.clean).mean())
    clean_g = float(region(gg, args.clean).mean())

    rep = {"task": "remove_part_check", "orig": args.orig, "gen": args.gen,
           "canvas": [W, H], "tolerance": args.tolerance,
           "clean_ref": {"box": args.clean, "edges_orig": round(clean_o, 2),
                         "edges_gen": round(clean_g, 2)},
           "parts": [], "verdict": "PASS"}

    print("=" * 68)
    print("移除部件点检 —— 平整度判据（不是改动率）")
    print("=" * 68)
    print("  干净面料基准  边缘强度 %6.2f → %6.2f   （PASS 基准线 = %.2f x 干净面）"
          % (clean_o, clean_g, args.tolerance))
    print("-" * 68)

    allpass = True
    for i, box in enumerate(args.part, 1):
        eo = float(region(go, box).mean())
        eg = float(region(gg, box).mean())
        ratio = eg / max(clean_g, 1e-6)
        ok = ratio <= args.tolerance
        allpass = allpass and ok
        rep["parts"].append({"box": box, "edges_orig": round(eo, 2),
                             "edges_gen": round(eg, 2),
                             "drop_pct": round((1 - eg / max(eo, 1e-6)) * 100, 1),
                             "ratio_vs_clean": round(ratio, 2),
                             "verdict": "PASS" if ok else "FAIL"})
        print("  部件#%d  %s" % (i, box))
        print("         边缘强度 %6.2f → %6.2f   下降 %5.1f%%   /干净面 %.2fx   [%s]"
              % (eo, eg, (1 - eg / max(eo, 1e-6)) * 100, ratio, "PASS" if ok else "FAIL"))

    # 色偏（只统计中性色面料，排除背景）
    yy, xx = np.mgrid[0:H, 0:W]
    inner = (xx > W*0.10) & (xx < W*0.90) & (yy > H*0.10) & (yy < H*0.92)
    r_, g_, b_ = o[..., 0], o[..., 1], o[..., 2]
    neutral = (np.abs(r_-g_) < 22) & (np.abs(g_-b_) < 22) & (np.abs(r_-b_) < 22)
    lo_, lg_ = lum(o), lum(g)
    body = inner & neutral & (lo_ > 90) & (lo_ < 253)
    d_lum = float((lg_[body] - lo_[body]).mean())
    d_rgb = [round(float((g[..., i][body] - o[..., i][body]).mean()), 1) for i in range(3)]
    rep["color_drift"] = {"lum": round(d_lum, 1), "rgb": d_rgb}
    print("-" * 68)
    print("  大身色偏  亮度 %+.1f   逐通道 R%+.1f G%+.1f B%+.1f" % (d_lum, *d_rgb))

    print("-" * 68)
    print("  总判定：%s" % ("✅ PASS — 部件已移除，裙面平整度达标"
                          if allpass else "❌ FAIL — 部件区仍不平整，需重出图"))
    print("=" * 68)
    print("  ⚠ 提示：若脚本报「部分区域仍不平」，先放大目检——")
    print("     可能是衣物固有结构线（侧缝/公主线/腰省），不是残留部件轮廓。")

    rep["verdict"] = "PASS" if allpass else "FAIL"
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print("  报告：%s" % args.json_out)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
