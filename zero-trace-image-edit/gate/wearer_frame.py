#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wearer_frame.py — 局部改款「位置」的根基：着装者坐标系 + 镜像归一化 + 人话↔坐标双向翻译
============================================================================================

为什么必须有这一层（用户铁律）：
    原 v1 的 region_coords.json 用「观图者视角」定义左右（注释还自称避免歧义），
    但「观图者左」≠「着装者左」是镜像铁律：
      - 模特正面照：模特右手在观图者左边；
      - 平铺拍：正反不一。
    所以任何「靠读文字位置确认」的做法 100% 会做反。本模块从根上消灭它。

核心约定：
    1. 系统内部只存 wearer_frame 归一化坐标 (wx, wy) ∈ [0,1]：
         wx=0 着装者左身侧缝，wx=1 着装者右身侧缝；wy=0 上、wy=1 下。
    2. 原图进来先 `set_mirror()` 锁镜像：记录「着装者右」在图中哪一侧。
    3. 业务人员只在「图上拖放」确认位置（看图标点，不读句）；
       人话回读只是存档副产物，不参与确认。
    4. 出图时 wearer→image 转换，落点恒定，不受图怎么拍/翻转影响。

本文件零外部依赖（仅 stdlib + math），可独立单测。
"""
import os
import re
import math


class AmbiguousPlacement(Exception):
    """解析人话位置失败（歧义/非规范表述）→ 强制回到图上直摆。"""
    pass


# 衣片模板（wearer_frame 归一化锚点）。y 向下增大。
# scale: 该视图下「1.0 归一化单位」对应的真实厘米（用于人话回读，仅存档，非确认依据）。
GARMENT_TEMPLATES = {
    "jeans_front": {
        # 五袋裤正面：腰头下沿 ~0.30，臀围线 ~0.50，膝线 ~0.72
        "waist_y": 0.30, "hip_y": 0.50, "knee_y": 0.72,
        "scale": {"x": 42.0, "y": 100.0},  # 前片宽约 42cm、长(腰→脚口)约 100cm
    },
    "jeans_back": {
        "waist_y": 0.30, "hip_y": 0.50, "knee_y": 0.72,
        "scale": {"x": 42.0, "y": 100.0},
    },
    "generic": {
        "waist_y": 0.25, "hip_y": 0.50, "knee_y": 0.75,
        "scale": {"x": 40.0, "y": 90.0},
    },
}


class WearerFrame:
    """一张原图 ↔ 一个着装者坐标系。"""

    def __init__(self, img_w, img_h, mirror=None, template="jeans_front"):
        self.img_w = int(img_w)
        self.img_h = int(img_h)
        # mirror=True 表示「观图者看到的左边 = 着装者右」（模特正面照即此情况）
        self.mirror = mirror
        self.tpl = GARMENT_TEMPLATES.get(template, GARMENT_TEMPLATES["generic"])
        self.locked = mirror is not None

    # ---------- 镜像锁（S1 强约束：未锁禁止进入位置确认） ----------
    def set_mirror_from_click(self, image_left_is_wearer_right: bool):
        """用户一次点击：『图里哪边是穿衣人的右手？』
        image_left_is_wearer_right=True  → 着装者右在图左 → mirror=True。"""
        self.mirror = bool(image_left_is_wearer_right)
        self.locked = True

    def require_locked(self):
        if not self.locked:
            raise RuntimeError("镜像未归一化：必须先 set_mirror_from_click() 锁定时装者坐标系，"
                               "禁止进入位置确认/出图。")

    # ---------- 坐标互转 ----------
    def wearer_to_image_norm(self, wx, wy):
        """wearer_frame → 图中归一化坐标（供画蒙版/落点）。"""
        self.require_locked()
        ix = (1.0 - wx) if self.mirror else wx
        return ix, float(wy)

    def image_norm_to_wearer(self, ix, iy):
        self.require_locked()
        wx = (1.0 - ix) if self.mirror else ix
        return wx, float(iy)

    def place_pixel(self, px, py):
        """业务人员在原图上拖放的像素点 → wearer_frame 归一化（这是确认的唯一权威来源）。"""
        self.require_locked()
        ix = px / self.img_w
        iy = py / self.img_h
        return self.image_norm_to_wearer(ix, iy)

    # ---------- 人话回读（仅存档，不参与确认） ----------
    def wearer_to_human(self, wx, wy, view="前片"):
        """wearer_frame 坐标 → 大白话（右前片, 腰头下Xcm, 侧缝内Ycm, 袋口平行腰头）。"""
        self.require_locked()
        side = "右" if wx >= 0.5 else "左"
        dy_norm = wy - self.tpl["waist_y"]
        dy_cm = max(0.0, dy_norm) * self.tpl["scale"]["y"]
        dx_norm = (1.0 - wx) if side == "右" else wx  # 距同侧侧缝向中心
        dx_cm = dx_norm * self.tpl["scale"]["x"]
        return (f"{side}{view}, 腰头下{round(dy_cm)}cm, 侧缝内{round(dx_cm)}cm, 袋口平行腰头")

    def human_to_wearer(self, text, view="前片"):
        """反向解析规范人话 → wearer_frame。非规范表述一律抛 AmbiguousPlacement，
        强制回到图上直摆（绝不静默猜）。"""
        self.require_locked()
        t = text.replace(" ", "")
        m_side = re.search(r"(左|右)", t)
        if not m_side:
            raise AmbiguousPlacement(f"未识别左右：{text}")
        side = m_side.group(1)
        m_dy = re.search(r"腰头下(\d+(?:\.\d+)?)cm", t)
        m_dx = re.search(r"侧缝内(\d+(?:\.\d+)?)cm", t)
        if not m_dy or not m_dx:
            raise AmbiguousPlacement(f"缺少『腰头下Xcm / 侧缝内Ycm』规范表述：{text}")
        dy_cm = float(m_dy.group(1))
        dx_cm = float(m_dx.group(1))
        wy = self.tpl["waist_y"] + dy_cm / self.tpl["scale"]["y"]
        dx_norm = dx_cm / self.tpl["scale"]["x"]
        wx = (1.0 - dx_norm) if side == "右" else dx_norm
        # 越界容错
        wx = min(1.0, max(0.0, wx)); wy = min(1.0, max(0.0, wy))
        return wx, wy

    # ---------- 工具 ----------
    def box_from_center_wearer(self, wx, wy, w_norm, h_norm):
        """给定 wearer 中心 + 尺寸(归一化) → 图中蒙版矩形（像素）。"""
        self.require_locked()
        cx_img, cy_img = self.wearer_to_image_norm(wx, wy)
        w_img = w_norm * self.img_w
        h_img = h_norm * self.img_h
        x1 = int((cx_img - w_norm / 2) * self.img_w)
        y1 = int((cy_img - h_norm / 2) * self.img_h)
        x2 = int(x1 + w_img)
        y2 = int(y1 + h_img)
        return (x1, y1, x2, y2)


# ---------- 预设口袋（wearer_frame，UI 点选兜底用） ----------
def load_presets():
    """从技能根 region_coords.json 的 wearer_frame 段加载；失败则用硬编码兜底。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(here, "..", "region_coords.json")
    try:
        import json
        with open(cand, "r", encoding="utf-8") as f:
            data = json.load(f)
        wf = data.get("wearer_frame", {})
        wf.pop("_说明", None)
        if wf:
            return wf
    except Exception:
        pass
    return {
        "left_front":  {"wx": 0.30, "wy": 0.45, "w": 0.18, "h": 0.22},
        "right_front": {"wx": 0.70, "wy": 0.45, "w": 0.18, "h": 0.22},
        "coin":        {"wx": 0.50, "wy": 0.40, "w": 0.06, "h": 0.08},
        "left_back":   {"wx": 0.30, "wy": 0.46, "w": 0.18, "h": 0.22},
        "right_back":  {"wx": 0.70, "wy": 0.46, "w": 0.18, "h": 0.22},
        "right_back_low": {"wx": 0.70, "wy": 0.62, "w": 0.171, "h": 0.179},
    }


PRESET_POCKETS = load_presets()


def demo():
    # 模特正面照：着装者右在图左 → mirror=True
    wf = WearerFrame(1000, 1400, mirror=True, template="jeans_front")
    # 业务在图上把口袋拖到「图左 200px、图高 600px」处（模特右大腿）
    wx, wy = wf.place_pixel(200, 600)
    print("拖放点 → wearer:", round(wx, 3), round(wy, 3), "(应为右半身 0.8, 0.43)")
    human = wf.wearer_to_human(wx, wy)
    print("人话回读:", human)
    # 反向解析应回到同一坐标
    wx2, wy2 = wf.human_to_wearer(human)
    print("回读解析 → wearer:", round(wx2, 3), round(wy2, 3))
    # 出图落点（图中像素）
    ix, iy = wf.wearer_to_image_norm(wx, wy)
    print("出图落点(图归一化):", round(ix, 3), round(iy, 3), "(应为 0.2, 0.43 → 图左)")


if __name__ == "__main__":
    demo()
