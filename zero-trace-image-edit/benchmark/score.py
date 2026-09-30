# -*- coding: utf-8 -*-
"""
零痕改图基准测试评分器（Zero-Trace Benchmark Score, v4.4.0）

任何人可用同一组标准测试图（orig_XX.png + mask_XX.png）复测任何"零痕改图"技能：
    python score.py --orig orig_01_color.png --edited <你的改后图>.png --mask mask_01_color.png

评分维度：
  1) 框外保真度 = 改动点 mask 外区域，原图与改后图像素一致率（单通道差>8 计为差异）
  2) 残影率     = 改动点 mask 内区域，改后图与原图的平均像素差 / 255（去物体/去水印任务）
  3) 零痕分     = A+ / A / B / C 综合评级

诚实原则：本脚本只做客观像素统计，不替任何技能"美言"；改坏就是改坏。
"""
import argparse
import json
import sys
from PIL import Image, ImageChops


def analyze(orig_path, edited_path, mask_path, threshold=8):
    orig = Image.open(orig_path).convert("RGB")
    edited = Image.open(edited_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    if orig.size != edited.size or orig.size != mask.size:
        raise ValueError("尺寸不一致：orig=%s edited=%s mask=%s" %
                         (orig.size, edited.size, mask.size))

    diff = ImageChops.difference(orig, edited)
    diff_px = list(diff.getdata())
    mask_px = list(mask.getdata())

    out_total = out_diff = in_total = in_diff_sum = 0
    for (r, g, b), mk in zip(diff_px, mask_px):
        d = max(r, g, b)
        if mk == 0:                      # 框外（应保持原样）
            out_total += 1
            if d > threshold:
                out_diff += 1
        else:                            # 框内（改动点区域）
            in_total += 1
            in_diff_sum += d

    frame_fidelity = (100.0 * (out_total - out_diff) / out_total) if out_total else 0.0
    residual = (100.0 * in_diff_sum / in_total / 255.0) if in_total else 0.0

    if frame_fidelity >= 99.5 and residual < 5:
        grade = "A+"
    elif frame_fidelity >= 99.0 and residual < 10:
        grade = "A"
    elif frame_fidelity >= 95.0:
        grade = "B"
    else:
        grade = "C"

    return {
        "frame_fidelity_pct": round(frame_fidelity, 3),
        "residual_rate_pct": round(residual, 3),
        "zero_trace_score": grade,
        "out_pixels": out_total,
        "out_diff_pixels": out_diff,
        "in_pixels": in_total,
    }


def main():
    ap = argparse.ArgumentParser(description="Zero-Trace Benchmark Score")
    ap.add_argument("--orig", required=True)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--mask", required=True)
    ap.add_argument("--threshold", type=int, default=8)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()
    try:
        res = analyze(args.orig, args.edited, args.mask, args.threshold)
    except Exception as e:
        print("❌ 评测失败：%s" % e, file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print("框外保真度 : %.3f%%" % res["frame_fidelity_pct"])
        print("残影率     : %.3f%%" % res["residual_rate_pct"])
        print("零痕分     : %s" % res["zero_trace_score"])


if __name__ == "__main__":
    main()
