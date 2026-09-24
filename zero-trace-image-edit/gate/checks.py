#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checks.py — 闸门② 量化点检（交付前，逐项判定；任一 FAIL = 整体 FAIL）
================================================================
每项返回 CheckResult(pass, measured, tolerance, detail)，可机读可人读。
默认容差（用户 2026-09-04 拍板）：
    颜色 ΔE < 3
    斜纹角度差 ≤ 3°
    尺寸偏差 ± 5%
    协调比（口袋宽/落袋部位宽）≤ 40%
仅依赖 numpy + Pillow（可选 opencv 仅加速，非必需）。
"""
import os
import math
import numpy as np
from PIL import Image


class CheckResult:
    def __init__(self, ok, measured, tolerance, detail=""):
        self.pass_ = bool(ok)
        self.measured = measured
        self.tolerance = tolerance
        self.detail = detail

    def __repr__(self):
        tag = "PASS" if self.pass_ else "FAIL"
        return f"[{tag}] 实测={self.measured} | 容差={self.tolerance} | {self.detail}"


# ---------------- 色彩空间 ----------------
def _rgb_to_lab(rgb):
    """rgb: uint8 [H,W,3] → lab float [H,W,3]"""
    rgb = rgb.astype(np.float64) / 255.0
    mask = rgb > 0.04045
    rgb = np.where(mask, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    x /= 0.95047; y /= 1.0; z /= 1.08883
    def f(t):
        return np.where(t > 0.008856, t ** (1/3), 7.787 * t + 16/116)
    fx, fy, fz = f(x), f(y), f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return np.stack([L, a, bb], axis=-1)


def delta_e76(lab1, lab2):
    d = lab1 - lab2
    return float(np.sqrt((d ** 2).sum(axis=-1)).mean())


# ---------------- 1. 颜色 ----------------
def check_color(pocket_patch, compare_patch, mode="same", tol_de=3.0):
    """mode: 'same'(同料同色,应与周边A一致) / 'keep_b'(保持B色,应与B原色一致)。
    pocket_patch / compare_patch: PIL Image(RGB) 或 numpy uint8 [H,W,3]。"""
    if isinstance(pocket_patch, Image.Image):
        pocket_patch = np.array(pocket_patch.convert("RGB"))
    if isinstance(compare_patch, Image.Image):
        compare_patch = np.array(compare_patch.convert("RGB"))
    # [H,W,3] 与 [N,3]（扁平像素）两种输入统一拉平成 [N,1,3]
    lab_p = _rgb_to_lab(np.asarray(pocket_patch).reshape(-1, 1, 3))
    lab_c = _rgb_to_lab(np.asarray(compare_patch).reshape(-1, 1, 3))
    de = delta_e76(lab_p.mean(axis=0), lab_c.mean(axis=0))
    ok = de < tol_de
    return CheckResult(ok, f"ΔE={de:.2f}", f"<{tol_de}", f"颜色模式={mode}")


# ---------------- 2. 纹理方向（斜纹角度） ----------------
def _dominant_angle(gray):
    """灰度图 → 主纹理梯度方向(角度,度)。结构张量法。"""
    if isinstance(gray, Image.Image):
        gray = np.array(gray.convert("L"), dtype=np.float64)
    gx = np.gradient(gray, axis=1)
    gy = np.gradient(gray, axis=0)
    Gxx = np.sum(gx * gx); Gyy = np.sum(gy * gy); Gxy = np.sum(gx * gy)
    ang = 0.5 * math.atan2(2 * Gxy, Gxx - Gyy)  # 弧度
    deg = math.degrees(ang) % 180
    return deg


def check_texture_angle(pocket_patch, garment_patch, tol_deg=3.0):
    if isinstance(pocket_patch, Image.Image):
        pocket_patch = pocket_patch.convert("L")
    if isinstance(garment_patch, Image.Image):
        garment_patch = garment_patch.convert("L")
    a_p = _dominant_angle(pocket_patch)
    a_g = _dominant_angle(garment_patch)
    diff = abs(a_p - a_g) % 180
    if diff > 90:
        diff = 180 - diff
    ok = diff <= tol_deg
    return CheckResult(ok, f"角度差={diff:.1f}° (袋{a_p:.0f}/衣{a_g:.0f})", f"≤{tol_deg}°", "斜纹走向一致性")


# ---------------- 3. 尺寸 ----------------
def check_size(box, expected_w, expected_h, tol_pct=5.0):
    """box=(x1,y1,x2,y2) 像素；与期望尺寸比偏差。"""
    w = box[2] - box[0]; h = box[3] - box[1]
    dw = abs(w - expected_w) / max(1, expected_w) * 100
    dh = abs(h - expected_h) / max(1, expected_h) * 100
    dev = max(dw, dh)
    ok = dev <= tol_pct
    return CheckResult(ok, f"偏差={dev:.1f}% (实{w}x{h}/期{expected_w}x{expected_h})",
                       f"±{tol_pct}%", "尺寸 SIZE")


# ---------------- 4. 协调性（口袋宽/落袋部位宽） ----------------
def check_coordination(pocket_box, body_part_box, tol_pct=40.0):
    pw = pocket_box[2] - pocket_box[0]
    bw = body_part_box[2] - body_part_box[0]
    ratio = pw / max(1, bw) * 100
    ok = ratio <= tol_pct
    return CheckResult(ok, f"占比={ratio:.1f}%", f"≤{tol_pct}%", "口袋/落袋部位宽")


# ---------------- 5. 落点偏移 ----------------
def check_position_offset(placed_box, intended_box, tol_px=15):
    pc = ((placed_box[0]+placed_box[2])/2, (placed_box[1]+placed_box[3])/2)
    ic = ((intended_box[0]+intended_box[2])/2, (intended_box[1]+intended_box[3])/2)
    dist = math.hypot(pc[0]-ic[0], pc[1]-ic[1])
    ok = dist <= tol_px
    return CheckResult(ok, f"偏移={dist:.1f}px", f"≤{tol_px}px", "落点偏移")


# ---------------- 6. 形状（长宽比比对） ----------------
def check_shape(box, ref_aspect, tol_pct=8.0):
    w = box[2] - box[0]; h = box[3] - box[1]
    aspect = w / max(1, h)
    dev = abs(aspect - ref_aspect) / max(1e-6, ref_aspect) * 100
    ok = dev <= tol_pct
    return CheckResult(ok, f"长宽比偏差={dev:.1f}% (实{aspect:.2f}/参{ref_aspect:.2f})",
                       f"±{tol_pct}%", "形状长宽比")


def demo():
    # 合成图：A 深蓝底 + 斜纹45°；口袋区 45° 同蓝(同料) / 或 135°红(撞色错向)
    W, H = 400, 400
    ys, xs = np.mgrid[0:H, 0:W]
    a45 = np.radians(45)
    phase = xs * np.cos(a45) + ys * np.sin(a45)
    stripe = (np.sin(phase / 6.0) * 0.5 + 0.5) * 30
    base = np.zeros((H, W, 3), dtype=np.float64)
    base[:, :, 2] = 90 + stripe   # 蓝
    base[:, :, 0] = 20
    base[:, :, 1] = 30
    A = base.astype(np.uint8)
    # 口袋区(左上 80x80)
    pocket_box = (40, 40, 120, 120)
    # 同料：口袋=同蓝，斜纹45°
    pocket_same = A[pocket_box[1]:pocket_box[3], pocket_box[0]:pocket_box[2]].copy()
    # 撞色错向：口袋=红，斜纹135°
    pa = np.radians(135)
    pphase = xs[:80, :80] * np.cos(pa) + ys[:80, :80] * np.sin(pa)
    sv2 = (np.sin(pphase / 6.0) * 0.5 + 0.5) * 30
    pocket_accent = np.zeros((80, 80, 3), dtype=np.float64)
    pocket_accent[:, :, 0] = 180 + sv2
    pocket_accent[:, :, 1] = 30
    pocket_accent[:, :, 2] = 30
    pocket_accent = pocket_accent.astype(np.uint8)

    print("① 颜色·同料同色(应与A一致):", check_color(pocket_same, A, mode="same", tol_de=3))
    print("① 颜色·撞色保持B(应保留红,与A差异大但保留B):",
          check_color(pocket_accent, pocket_accent, mode="keep_b", tol_de=3))
    print("② 纹理·同料(45° vs A45°):", check_texture_angle(pocket_same, A, tol_deg=3))
    print("② 纹理·错向(90° vs A45°):", check_texture_angle(pocket_accent, A, tol_deg=3))
    print("③ 尺寸(80x80 vs 80x80):", check_size(pocket_box, 80, 80))
    print("④ 协调(袋80 / 身400=20%):", check_coordination(pocket_box, (0, 0, 400, 400)))
    print("⑤ 落点(同框):", check_position_offset(pocket_box, pocket_box))
    print("⑥ 形状(长宽比1.0 vs 1.0):", check_shape(pocket_box, 1.0))


if __name__ == "__main__":
    demo()
