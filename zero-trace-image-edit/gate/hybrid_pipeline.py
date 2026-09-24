#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hybrid_pipeline.py — 组合拳流水线（生成式出形 + 像素法校色，v3.1.0 新增）
=========================================================================
2026-09-11 实战沉淀（PG-002 口袋嫁接）：

问题：Seedream 5.0 Pro 是**生成式重绘**，能生成新结构（口袋、部件），
      但会给整图带来**均匀色偏**（实测 大身亮度 −20 ~ −30），
      交付客户时颜色对不上原款。

解决：**分工协作**
  · Seedream 负责"造形状" —— 这是像素法做不到的
  · 传统像素法负责"校颜色" —— 这是 Seedream 做不好的

  实测效果：大身亮度差 从 −20 收敛到 **−3**，口袋完整保留。

⚠ 关键教训（v2 失败案例）：
  **不要用分块/矩形的逐通道 mean-std 映射！**
  v2 曾按 3x3 网格分块做线性映射，结果在大身产生**可见的矩形拼接块**
  （因为 pocket_mask 是矩形）。
  正确做法：Seedream 的漂移是**全局均匀**的，
  只需算一个**全局色偏向量**，整图统一补偿 —— 空间均匀，零拼接痕迹。
  实测 3x3 分块偏差 ≤ 4（肉眼不可见）。

用法：
  python gate/hybrid_pipeline.py --orig A.jpg --gen gen.jpg --out fixed.jpg \
      --exclude 0.30,0.62,0.10,0.48     # 排除新增部件区域(y0,y1,x0,x1 比例)

  ★ --mode curve（默认）: 亮度曲线匹配 —— 按像素亮度分箱做偏移。
     空间均匀（同亮度修正量相同，零拼接块），且能**同时对齐暗部与亮部**。
     实测（PG-005）：最大区域偏差 从常数偏移的 17.3 压到 4.1。
  ★ --mode shift: 全局常数偏移（旧法）。整图加减同一个值，
     只能对齐一头 —— 修了暗部就牺牲亮部、修了主体就牺牲背景。

⚠ --exclude 顺序是 y0,y1,x0,x1（不是 x0,y0,x1,y1）。
   写反会得到空框、静默失效（PG-004 踩过），本脚本已加校验拦截。

★ --sample-box：显式指定"色调基准取样区"（v3.5 新增，顺序同 --exclude：y0,y1,x0,x1，
   多个框用分号隔开）。
   为什么需要：默认的自动掩膜按**中性色/浅色衣物**设计（|R-B|<25 且亮度 70~155），
   一旦主体是**有色物体**（红棕毛皮、木器、彩色道具）就会被全部排除，
   掩膜转而选到背景 —— 色偏基准就错了（PG-006 实测：红棕牛身 R-B≈47，自动掩膜
   选到的像素平均色与真实主体差 34）。
   跨行业/非浅色主体场景，**必须**用 --sample-box 显式指定主体区域。
   例：--sample-box 0.17,0.70,0.13,0.72;0.42,0.62,0.16,0.30
      （含义：y 17%~70% 且 x 13%~72%，以及 y 42%~62% 且 x 16%~30%）
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tone_match import build_tone_curve, apply_tone_curve, body_mask  # noqa: E402


def body_sample_mask(arr, excl):
    """采样"大身面料"像素，排除背景与新增部件区。

    大身面料判据：
      · 色彩中性（|R-B|<25 且 |G-B|<25）—— 排除偏黄木地板
      · 亮度 70~155 —— 排除纯黑阴影与过曝高光
      · 不在 excl 区域内 —— 排除新增部件
    """
    h, w, _ = arr.shape
    lum = arr.mean(axis=2)
    neutral = (np.abs(arr[:, :, 0] - arr[:, :, 2]) < 25) & \
              (np.abs(arr[:, :, 1] - arr[:, :, 2]) < 25)
    m = neutral & (lum < 155) & (lum > 70)
    if excl:
        box = np.zeros((h, w), bool)
        y0, y1, x0, x1 = [int(round(v)) for v in (excl[0] * h, excl[1] * h, excl[2] * w, excl[3] * w)]
        box[y0:y1, x0:x1] = True
        m &= ~box
    return m


def parse_boxes(spec):
    """把 'y0,y1,x0,x1;y0,y1,x0,x1' 解析为 [[y0,y1,x0,x1], ...]，带顺序校验。"""
    boxes = []
    for part in str(spec).split(";"):
        part = part.strip()
        if not part:
            continue
        v = [float(x) for x in part.split(",")]
        if len(v) != 4:
            raise SystemExit("❌ --sample-box 每段需要 4 个值：y0,y1,x0,x1")
        if v[1] <= v[0] or v[3] <= v[2]:
            raise SystemExit(
                "❌ --sample-box 顺序写反了！必须是 y0,y1,x0,x1 且 y1>y0、x1>x0。\n"
                "   例：主体在画面中下部 → --sample-box 0.17,0.70,0.13,0.72\n"
                "   （含义：y 从 17% 到 70%，x 从 13% 到 72%）")
        boxes.append(v)
    if not boxes:
        raise SystemExit("❌ --sample-box 未解析出任何有效框")
    return boxes


def explicit_sample_mask(arr, boxes, excl=None):
    """按显式框取"色调基准"像素（跨行业/非浅色主体场景必用）。

    与 body_sample_mask 的区别：不做中性色启发式判断，
    只按坐标框取，因此对红棕毛皮、木器、彩色道具等主体同样有效。
    """
    h, w, _ = arr.shape
    m = np.zeros((h, w), bool)
    for y0, y1, x0, x1 in boxes:
        m[int(round(y0 * h)):int(round(y1 * h)),
          int(round(x0 * w)):int(round(x1 * w))] = True
    # 仍排除新增部件区（部件是新生成的，不能当色调基准）
    if excl:
        y0, y1, x0, x1 = [int(round(v)) for v in (excl[0] * h, excl[1] * h, excl[2] * w, excl[3] * w)]
        box = np.zeros((h, w), bool); box[y0:y1, x0:x1] = True
        m &= ~box
    return m


def global_shift(orig, gen, excl=None, boxes=None):
    """估计生成图相对原图的全局色偏向量（逐通道均值差）。"""
    m = explicit_sample_mask(orig, boxes, excl) if boxes else body_sample_mask(orig, excl)
    if m.sum() < 500:
        raise SystemExit("❌ 大身取样像素过少（%d），请检查 --exclude / --sample-box 范围" % m.sum())
    shift = np.array([gen[:, :, c][m].mean() - orig[:, :, c][m].mean() for c in range(3)])
    return shift, int(m.sum())


def spatial_uniformity(out, orig, excl=None, grid=3, boxes=None):
    """3x3 分块检查空间均匀性，返回最大块间偏差。

    boxes 给出时按显式框取主体像素；否则退回中性色启发式掩膜。
    """
    h, w, _ = orig.shape
    devs = []
    for i in range(grid):
        for j in range(grid):
            y0 = int(h * (0.15 + 0.25 * i)); y1 = y0 + int(h * 0.22)
            x0 = int(w * (0.10 + 0.28 * j)); x1 = x0 + int(w * 0.25)
            blk = np.zeros((h, w), bool); blk[y0:y1, x0:x1] = True
            if excl:
                box = np.zeros((h, w), bool)
                yy0, yy1, xx0, xx1 = [int(round(v)) for v in (excl[0]*h, excl[1]*h, excl[2]*w, excl[3]*w)]
                box[yy0:yy1, xx0:xx1] = True
                blk &= ~box
            if boxes:
                # 显式框也必须套用 excl：否则框边缘扫到"新增部件"（如新头部）
                # 会与原作者区混算，块间偏差虚高（实测误报 69）
                mo = blk & explicit_sample_mask(out, boxes, excl)
                ma = blk & explicit_sample_mask(orig, boxes, excl)
            else:
                mo = blk & body_sample_mask(out, None)
                ma = blk & body_sample_mask(orig, None)
            if mo.sum() > 100 and ma.sum() > 100:
                devs.append(float((out[mo].mean(axis=0) - orig[ma].mean(axis=0)).mean()))
    return (max(abs(d) for d in devs) if devs else 0.0), devs


def main():
    ap = argparse.ArgumentParser(description="组合拳：生成式出形 + 像素法校色")
    ap.add_argument("--orig", required=True, help="原图（A图，色调基准）")
    ap.add_argument("--gen", required=True, help="生成图（Seedream 输出）")
    ap.add_argument("--out", required=True, help="输出路径")
    ap.add_argument("--exclude", default=None,
                    help="排除新增部件区域，格式 y0,y1,x0,x1（画面比例），如 0.30,0.62,0.10,0.48")
    ap.add_argument("--sample-box", default=None,
                    help="★显式指定色调基准取样区，格式 y0,y1,x0,x1（同 --exclude），"
                         "多框用分号隔开。非浅色主体(红棕毛皮/木器/彩色道具)场景必用，"
                         "否则自动掩膜会选到背景。例：0.17,0.70,0.13,0.72;0.42,0.62,0.16,0.30")
    ap.add_argument("--mode", default="curve", choices=["curve", "shift"],
                    help="curve=亮度曲线匹配(推荐,默认) / shift=全局常数偏移(旧法)")
    ap.add_argument("--out-res", default="gen", choices=["gen", "orig"],
                    help="输出分辨率：gen=保留生成图原生分辨率(默认，Seedream 出图通常更大，"
                         "降采样会白丢清晰度) / orig=与原图一致")
    ap.add_argument("--json", default=None, help="报告输出路径")
    args = ap.parse_args()

    a_img = Image.open(args.orig).convert("RGB")
    g_native = Image.open(args.gen).convert("RGB")
    if args.out_res == "gen" and g_native.size[0] * g_native.size[1] >= a_img.size[0] * a_img.size[1]:
        W, H = g_native.size
    else:
        W, H = a_img.size
    g_img = g_native.resize((W, H), Image.LANCZOS) if g_native.size != (W, H) else g_native
    a_img = a_img.resize((W, H), Image.LANCZOS) if a_img.size != (W, H) else a_img
    a = np.asarray(a_img).astype(np.float32)
    g = np.asarray(g_img).astype(np.float32)

    excl = None
    if args.exclude:
        excl = [float(v) for v in args.exclude.split(",")]
        if len(excl) != 4:
            raise SystemExit("❌ --exclude 需要 4 个值：y0,y1,x0,x1")
        if excl[1] <= excl[0] or excl[3] <= excl[2]:
            raise SystemExit(
                "❌ --exclude 顺序写反了！必须是 y0,y1,x0,x1 且 y1>y0、x1>x0。\n"
                "   例：排除前片上部两个口袋 → --exclude 0.03,0.36,0.13,0.92\n"
                "   （含义：y 从 3% 到 36%，x 从 13% 到 92%）")

    boxes = None
    if getattr(args, "sample_box", None):
        boxes = parse_boxes(args.sample_box)

    print("=" * 66)
    print("  组合拳流水线 — 生成式出形 + 像素法校色")
    print("  模式: %s" % ("亮度曲线匹配（按亮度分箱，空间均匀）" if args.mode == "curve"
                        else "全局常数偏移（旧法）"))
    print("  取样: %s" % ("显式取样区 %d 个框（跨行业/非浅色主体）" % len(boxes) if boxes
                        else "自动掩膜（中性色启发式，适用浅色衣物）"))
    print("=" * 66)

    if boxes:
        m = explicit_sample_mask(a, boxes, excl)
        n_sample = int(m.sum())
        if n_sample < 5000:
            raise SystemExit("❌ --sample-box 取样像素过少（%d），请检查框是否落在主体上" % n_sample)
        print("取样像素   : %d 像素（显式框，平均色 RGB(%.0f,%.0f,%.0f)）"
              % (n_sample, a[..., 0][m].mean(), a[..., 1][m].mean(), a[..., 2][m].mean()))
        if args.mode == "curve":
            centers, offsets = build_tone_curve(a, g, m, bins=24, smooth=2)
            out = apply_tone_curve(g, centers, offsets)
            mode_used = "curve"
            print("曲线分箱   : %d 箱（亮度 %d ~ %d）"
                  % (len(centers), int(centers[0]), int(centers[-1])))
            print("偏移范围   : R %+.1f ~ %+.1f   （常数偏移只能取单一值）"
                  % (offsets[:, 0].min(), offsets[:, 0].max()))
            extra = {"tone_curve_bins": len(centers),
                     "offset_range_R": [round(float(offsets[:, 0].min()), 1),
                                        round(float(offsets[:, 0].max()), 1)]}
        else:
            shift, _ = global_shift(a, g, excl, boxes)
            print("全局色偏   : R%+.1f G%+.1f B%+.1f" % tuple(shift))
            out = np.clip(g - shift[None, None, :], 0, 255)
            mode_used = "shift"
            extra = {"global_shift": [round(float(v), 2) for v in shift]}
    elif args.mode == "curve":
        # 亮度曲线匹配：按像素亮度分箱做偏移，空间均匀、无拼接块，
        # 能同时对齐暗部与亮部（常数偏移只能对齐一头）
        h_, w_ = a.shape[:2]
        yy, xx = np.mgrid[0:h_, 0:w_]
        central = (xx > w_*0.13) & (xx < w_*0.87) & (yy > h_*0.02) & (yy < h_*0.95)
        m = body_mask(a, excl) & central          # 收紧到衣身主体，排除背景干扰
        if m.sum() < 5000:
            print("⚠ 取样像素偏少（%d），回退到常数偏移模式" % m.sum())
            shift, n_sample = global_shift(a, g, excl)
            out = np.clip(g - shift[None, None, :], 0, 255)
            mode_used = "shift(回退)"
            extra = {"global_shift": [round(float(v), 2) for v in shift]}
        else:
            centers, offsets = build_tone_curve(a, g, m, bins=28, smooth=2)
            out = apply_tone_curve(g, centers, offsets)
            n_sample = int(m.sum())
            mode_used = "curve"
            print("大身取样   : %d 像素" % n_sample)
            print("曲线分箱   : %d 箱（亮度 %d ~ %d）"
                  % (len(centers), int(centers[0]), int(centers[-1])))
            print("偏移范围   : R %+.1f ~ %+.1f   （常数偏移只能取单一值）"
                  % (offsets[:, 0].min(), offsets[:, 0].max()))
            extra = {"tone_curve_bins": len(centers),
                     "offset_range_R": [round(float(offsets[:, 0].min()), 1),
                                        round(float(offsets[:, 0].max()), 1)]}
    else:
        shift, n_sample = global_shift(a, g, excl)
        print("大身取样   : %d 像素" % n_sample)
        print("全局色偏   : R%+.1f G%+.1f B%+.1f" % tuple(shift))
        out = np.clip(g - shift[None, None, :], 0, 255)
        mode_used = "shift"
        extra = {"global_shift": [round(float(v), 2) for v in shift]}

    # 质检（用同一取样口径统计原图/生成/修正，避免掩膜不一致导致误报）
    if boxes:
        m_a = explicit_sample_mask(a, boxes, excl)
    else:
        m_a = body_sample_mask(a, excl)
        # 自动掩膜可靠性自检：若掩膜平均色与"画面中央主体色"相差过大，
        # 说明中性色启发式选错了区域（非浅色主体场景），提示改用 --sample-box
        h_, w_ = a.shape[:2]
        yy, xx = np.mgrid[0:h_, 0:w_]
        core = (xx > w_ * 0.2) & (xx < w_ * 0.8) & (yy > h_ * 0.2) & (yy < h_ * 0.75)
        if m_a.sum() > 1000 and core.sum() > 1000:
            gap = abs(float(a[m_a].mean() - a[core].mean()))
            if gap > 20:
                print("⚠ 自动掩膜可疑：掩膜平均色与画面中央主体色相差 %.0f" % gap)
                print("  → 主体可能不是浅色/中性色。跨行业场景请用 --sample-box 显式指定取样区。")
    ca = a[m_a].mean(axis=0)
    cg = g[m_a].mean(axis=0)
    co = out[m_a].mean(axis=0)
    max_blk, devs = spatial_uniformity(out, a, excl, boxes=boxes)

    print()
    print("大身色 原图 : RGB(%.0f,%.0f,%.0f)" % tuple(ca))
    print("大身色 生成 : RGB(%.0f,%.0f,%.0f)  亮度 %+.0f" % (cg[0], cg[1], cg[2], cg.mean() - ca.mean()))
    print("大身色 修正 : RGB(%.0f,%.0f,%.0f)  亮度 %+.0f" % (co[0], co[1], co[2], co.mean() - ca.mean()))
    print("色偏残差    : R%+.1f G%+.1f B%+.1f" % tuple(co - ca))
    print("空间均匀性  : 3x3 最大块间偏差 %.0f  (越小越均匀，无拼接痕迹)" % max_blk)

    Image.fromarray(out.astype(np.uint8)).save(args.out)
    print()
    print("✅ 已保存: %s" % args.out)

    if args.json:
        rep = {
            "orig": args.orig, "gen": args.gen, "out": args.out,
            "sample_pixels": n_sample,
            "mode": mode_used,
            "sample_mode": ("explicit_box(%d)" % len(boxes)) if boxes else "auto_neutral_mask",
            "sample_boxes": boxes if boxes else None,
            "body_color": {
                "orig": [round(float(v), 1) for v in ca],
                "gen": [round(float(v), 1) for v in cg],
                "fixed": [round(float(v), 1) for v in co],
                "delta_gen": round(float(cg.mean() - ca.mean()), 1),
                "delta_fixed": round(float(co.mean() - ca.mean()), 1),
            },
            "spatial_uniformity_max_dev": round(float(max_blk), 1),
            "method": ("亮度曲线匹配（按亮度分箱偏移，空间均匀，同时对齐暗部与亮部）"
                       if mode_used == "curve" else
                       "全局色偏补偿（空间均匀，非分块映射）"),
        }
        rep.update(extra)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print("报告: %s" % args.json)


if __name__ == "__main__":
    main()
