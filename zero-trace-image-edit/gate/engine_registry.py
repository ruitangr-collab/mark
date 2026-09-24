#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engine_registry.py — 出图引擎可插拔注册表（v3.0.0 新增）
=========================================================================
背景（2026-09-11 用户决策）：
  完全对齐豆包"多参考图条件编辑"方案。原「无外部依赖」规则升级为：
    ① 默认零配置可跑（上架版护城河：不填 key 不报错）
    ② 引擎可插拔、可降级（主力挂了自动切备用）
    ③ 数据分级路由（涉密客户图禁出网）
  原规则降级为"默认体验档"，外接引擎成为"质量上限开关"。

实测依据（同条件盲测，输入图 MD5 一致）：
  平台内置通道 3 条硬伤 —— ①画幅被锁 1:1（原图 3:4 被重构图，轮廓长宽比
  0.713→0.849 约 +19%）②分辨率 1024² vs 1536×2048 差 3 倍 ③输出带
  WORKBUDDY 半透明水印（v6a/v4b/v6c 三张全带、位置固定）。
  带水印的成图不可交付客户 —— 这是引擎可插拔成为必选项的直接原因。

本模块只做**登记与选择**，不产出图像、不发起任何网络请求。
"""
import argparse
import json
import os

# ---------------------------------------------------------------------------
# 引擎登记表
# 字段说明：
#   kind             builtin(平台内置) | external_api(外部API) | local(本机)
#   multi_ref        是否支持多参考图条件编辑（image1=主体 / image2=部件来源）
#   local_edit       是否支持"以图改图"（在已出成图上做局部二轮编辑）
#   sizes            支持的输出画幅档位；["native"]=原生跟随输入比例
#   aspect_follow    是否原生跟随输入画幅
#   watermark        已知水印标识；None=无
#   credential_env   需要的凭据环境变量名；[]=零配置
#   privacy          cloud=图出网 | local=图不出厂
#   quality_rank     质量上限排序（1 最高）；同分按可用性
# ---------------------------------------------------------------------------
ENGINES = {
    "seedream": {
        "label": "Seedream 5.0 Pro（火山方舟 image_edit）",
        "kind": "external_api",
        "multi_ref": True,
        "local_edit": True,
        "sizes": ["native", "2K", "4K"],
        "aspect_follow": True,
        "watermark": None,
        "credential_env": ["ARK_API_KEY"],
        "privacy": "cloud",
        "quality_rank": 1,
        "note": "豆包方案同款主力。原生画幅、无平台水印、支持多参考图。"
                "需火山方舟 API Key，按次计费。"
                "⚠ 适用边界（2026-09-11 三轮实测）：这是**生成式重绘**不是编辑式，"
                "改动覆盖全幅，且负向约束（'不许改/不许提亮'）无效、迭代会单调恶化"
                "（亮度 −27→−29→−30）。适合'整体风格化输出'，"
                "**不适合要求框外像素级不变的商品图局部微调** —— 后者应走 local 通道。",
    },
    "kling": {
        "label": "可灵 AI（图生图 / 参考图）",
        "kind": "external_api",
        "multi_ref": True,
        "local_edit": True,
        "sizes": ["native"],
        "aspect_follow": True,
        "watermark": None,
        "credential_env": ["KLING_ACCESS_KEY", "KLING_SECRET_KEY"],
        "privacy": "cloud",
        "quality_rank": 2,
        "note": "国内合规主力备选，通过连接器授权无需手填 key。",
    },
    "nanobanana": {
        "label": "Nano-Banana 系列（多参考图编辑）",
        "kind": "external_api",
        "multi_ref": True,
        "local_edit": True,
        "sizes": ["native"],
        "aspect_follow": True,
        "watermark": None,
        "credential_env": ["AIHIVE_API_KEY"],
        "privacy": "cloud",
        "quality_rank": 2,
        "note": "多参考图局部编辑能力突出，适合部件嫁接类任务。",
    },
    "qwen-image-edit": {
        "label": "Qwen-Image-Edit",
        "kind": "external_api",
        "multi_ref": True,
        "local_edit": True,
        "sizes": ["native"],
        "aspect_follow": True,
        "watermark": None,
        "credential_env": ["DASHSCOPE_API_KEY"],
        "privacy": "cloud",
        "quality_rank": 3,
        "note": "国内合规备选。",
    },
    "fdplus": {
        "label": "平台内置通道（零配置兜底）",
        "kind": "builtin",
        "multi_ref": True,
        "local_edit": True,
        "sizes": ["1024x1024", "1024x1536", "1536x1024"],
        "aspect_follow": False,
        "watermark": "WORKBUDDY",
        "credential_env": [],
        "privacy": "cloud",
        "quality_rank": 4,
        "note": "装机即用的默认档，不填 key 不报错。已知限制：画幅离散只能逼近、"
                "输出右下角带平台水印（交付前需处理）。",
    },
    "local-fooocus": {
        "label": "本机 Fooocus-API（图不出厂）",
        "kind": "local",
        "multi_ref": True,
        "local_edit": True,
        "sizes": ["1024x1024", "1024x1536", "1536x1024"],
        "aspect_follow": False,
        "watermark": None,
        "credential_env": [],
        "privacy": "local",
        "quality_rank": 5,
        "note": "涉密客户图专用通道；需本机 GPU 环境就绪（一键启动 Fooocus-API.bat）。",
    },
}

# 数据分级 → 允许的通道类型
PRIVACY_POLICY = {
    "public":  {"kinds": {"builtin", "external_api", "local"}, "desc": "一般款式图，可出网"},
    "client":  {"kinds": {"external_api", "local"},             "desc": "客户图，允许合规外接引擎，禁平台内置兜底"},
    "secret":  {"kinds": {"local"},                             "desc": "涉密图，绝不出网，仅本机"},
}


def _ark_key_present():
    """方舟系凭据是否存在（与 ark_engine.load_credential 同源的二级查找）。

    ⚠ v3.4 修复：本函数原先只查环境变量，导致 user 已用
    `ark_engine.py --save` 把 Key 落盘到 ~/.workbuddy/ark_config.json 后，
    引擎表仍显示"❌缺凭据"，进而使 choose_engine() 误判 seedream 不可用
    并触发错误降级。现与环境变量并列检查用户配置文件。
    """
    if os.environ.get("ARK_API_KEY"):
        return True
    p = os.path.join(os.path.expanduser("~"), ".workbuddy", "ark_config.json")
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("api_key"))
        except Exception:
            return False
    return False


def has_credential(engine):
    """凭据是否齐备（零配置引擎恒为 True；方舟系走环境变量 + 用户配置文件）。"""
    need = ENGINES[engine].get("credential_env") or []
    if not need:
        return True
    for k in need:
        if k == "ARK_API_KEY":
            if not _ark_key_present():
                return False
        elif not os.environ.get(k):
            return False
    return True


def list_engines(only_ready=False):
    rows = []
    for name, e in ENGINES.items():
        ready = has_credential(name)
        if only_ready and not ready:
            continue
        rows.append(dict(name=name, ready=ready, **e))
    rows.sort(key=lambda r: (not r["ready"], r["quality_rank"]))
    return rows


def choose_engine(prefer=None, privacy="public", allow_fallback=True):
    """按 数据分级 + 凭据齐备 + 质量档位 选出图引擎。

    返回 dict: {engine, label, degraded, reason}
    degraded=True 表示用户点名的引擎不可用、已自动降级。
    """
    kinds = PRIVACY_POLICY.get(privacy, PRIVACY_POLICY["public"])["kinds"]

    def allowed(n):
        e = ENGINES[n]
        return has_credential(n) and e["kind"] in kinds

    if prefer:
        if prefer not in ENGINES:
            return {"engine": None, "label": None, "degraded": False,
                    "reason": "未知引擎 %s；可选：%s" % (prefer, "、".join(ENGINES))}
        if allowed(prefer):
            return {"engine": prefer, "label": ENGINES[prefer]["label"],
                    "degraded": False,
                    "reason": "点名引擎可用（数据分级=%s）。" % privacy}
        if not allow_fallback:
            return {"engine": None, "label": None, "degraded": False,
                    "reason": "点名引擎 %s 不可用（缺凭据或违反数据分级=%s），且未允许降级。"
                              % (prefer, privacy)}

    # 自动挑选：质量档位优先，跳过不可用
    for n, e in sorted(ENGINES.items(), key=lambda kv: kv[1]["quality_rank"]):
        if allowed(n):
            return {"engine": n, "label": e["label"], "degraded": bool(prefer),
                    "reason": ("已自动选用 %s（数据分级=%s，凭据齐备）。" % (n, privacy))
                              + ("原点名引擎 %s 不可用，已降级。" % prefer if prefer else "")}

    return {"engine": None, "label": None, "degraded": False,
            "reason": "在当前数据分级=%s 下无可用引擎（凭据全缺或全被分级挡下）。" % privacy}


def fit_size(src_w, src_h, engine):
    """画幅跟随：为离散画幅的引擎挑最接近输入比例的档位。

    返回 (size_str, aspect_err)。原生跟随的引擎返回 ("native", 0.0)。
    这是修掉"原图 3:4 被塞进 1:1 方图导致重构图"的关键一步。
    """
    e = ENGINES.get(engine)
    if not e:
        return None, None
    if e["aspect_follow"]:
        return "native", 0.0
    src_ar = src_w / src_h
    best, best_err = None, None
    for s in e["sizes"]:
        try:
            w, h = (int(x) for x in s.lower().split("x"))
        except Exception:
            continue
        err = abs((w / h) / src_ar - 1.0)
        if best_err is None or err < best_err:
            best, best_err = s, err
    return best, round(best_err, 4)


def watermark_zone(size_pct=0.18, height_pct=0.10):
    """平台水印已知落点（右下角）。返回归一化 (x0,y0,x1,y1)，供出图后目检/检测。"""
    return (round(1 - size_pct, 3), round(1 - height_pct, 3), 1.0, 1.0)


def main():
    ap = argparse.ArgumentParser(description="出图引擎注册表 / 画幅跟随计算")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ready-only", action="store_true")
    ap.add_argument("--src", default=None, help="输入图路径，用于算画幅跟随档位")
    ap.add_argument("--privacy", default="public", choices=list(PRIVACY_POLICY))
    args = ap.parse_args()

    if args.src:
        from PIL import Image
        w, h = Image.open(args.src).size
        print("输入图 %dx%d  比例 %.4f" % (w, h, w / h))
        for n in ENGINES:
            s, err = fit_size(w, h, n)
            print("  %-18s -> %-10s 画幅误差 %.1f%%" % (n, s, (err or 0) * 100))
        print("\n分级=%s 下的选择：%s" % (args.privacy, choose_engine(privacy=args.privacy)["reason"]))
        return

    rows = list_engines(only_ready=args.ready_only)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print("%-18s%-8s%-10s%-8s%-9s%s" % ("引擎", "就绪", "多参考图", "二轮改图", "画幅跟随", "备注"))
    print("-" * 96)
    for r in rows:
        print("%-18s%-8s%-10s%-8s%-9s%s" % (
            r["name"], "✅" if r["ready"] else "❌缺凭据",
            "✅" if r["multi_ref"] else "—",
            "✅" if r["local_edit"] else "—",
            "原生" if r["aspect_follow"] else "离散",
            (r["watermark"] and "水印=" + r["watermark"] or "无水印"),
        ))


if __name__ == "__main__":
    main()
