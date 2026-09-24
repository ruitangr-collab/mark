# -*- coding: utf-8 -*-
"""
亮度曲线匹配（tone-curve matching）—— 常数偏移的升级版
==========================================================
背景：hybrid_pipeline 的"全局常数偏移"假设 Seedream 色偏是均匀加减，
      实测发现是**非线性压暗**（暗部压得多、亮部压得少），
      常数偏移修暗部就牺牲亮部（PG-005 亮部 +7.6、PG-004 背景 +7.2）。

原理：按"像素亮度"分箱，统计每箱的原图均值与生成均值，
      得到一条 gen→orig 的映射曲线；每个像素按自己所在亮度箱的
      偏移量修正 —— **同一亮度修正量相同**，所以空间均匀、零拼接块，
      但能同时对齐暗部与亮部。
"""
import numpy as np
from PIL import Image


def _lum(a):
    return 0.299*a[..., 0] + 0.587*a[..., 1] + 0.114*a[..., 2]


def build_tone_curve(orig, gen, mask, bins=24, smooth=2):
    """按生成图亮度分箱，返回每个箱的逐通道偏移量 + 箱中心亮度。"""
    lg = _lum(gen)
    v = lg[mask]
    lo_, hi_ = np.percentile(v, 1), np.percentile(v, 99)
    edges = np.linspace(lo_, hi_, bins + 1)
    centers, offsets = [], []
    for i in range(bins):
        sel = mask & (lg >= edges[i]) & (lg < edges[i+1] if i < bins-1 else lg <= edges[i+1])
        if sel.sum() < 200:
            centers.append((edges[i] + edges[i+1]) / 2)
            offsets.append(np.array([0.0, 0.0, 0.0]))
            continue
        centers.append(float(lg[sel].mean()))
        offsets.append(np.array([float(gen[..., c][sel].mean() - orig[..., c][sel].mean())
                                 for c in range(3)]))
    offsets = np.array(offsets)
    # 平滑（滑动平均），避免分箱跳变
    if smooth > 0:
        k = np.ones(2*smooth + 1) / (2*smooth + 1)
        for c in range(3):
            offsets[:, c] = np.convolve(np.pad(offsets[:, c], smooth, mode="edge"),
                                        k, mode="valid")
    return np.array(centers), offsets


def apply_tone_curve(gen, centers, offsets):
    """按像素亮度线性插值查表修正（空间均匀）。"""
    lg = _lum(gen).ravel()
    out = gen.reshape(-1, 3).copy()
    order = np.argsort(centers)
    ce, of = np.array(centers)[order], offsets[order]
    for c in range(3):
        adj = np.interp(lg, ce, of[:, c], left=of[order][0, c], right=of[order][-1, c])
        out[:, c] = out[:, c] - adj
    return np.clip(out.reshape(gen.shape), 0, 255)


def body_mask(arr, excl=None, lum_lo=15, lum_hi=250):
    """中性色衣身像素（排除偏黄地板与彩色背景）"""
    h, w, _ = arr.shape
    l = _lum(arr)
    neutral = (np.abs(arr[:, :, 0]-arr[:, :, 2]) < 25) & (np.abs(arr[:, :, 1]-arr[:, :, 2]) < 25)
    m = neutral & (l > lum_lo) & (l < lum_hi)
    if excl:
        y0, y1, x0, x1 = [int(round(v)) for v in (excl[0]*h, excl[1]*h, excl[2]*w, excl[3]*w)]
        box = np.zeros((h, w), bool); box[y0:y1, x0:x1] = True
        m &= ~box
    return m
