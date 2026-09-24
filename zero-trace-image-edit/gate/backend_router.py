#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backend_router.py — 出图通道自适应决策（真图红线不可绕过）
=========================================================================
用户 2026-09-04 铁律（自适应版，写死，不可绕过）：
  ① 技能必须自动检测本机 GPU 与出图环境，禁止伪造探测结果。
  ② 本地不可用（没装 GPU 环境 / 没条件装 / 探测不到）→ 技能**自主**改走
     **公开开源渠道**（平台调用的开源模型）把任务干完，同时**明确告知**
     使用者「图会出网」。不许把使用者挡死在半路。
  ③ **严禁**在任何情况下生成模拟图/占位图/假图充数 —— 必须出真图。
  ④ 使用者可显式选 --no-public（隐私模式）：图绝不出网；此时本地不可用
     即封锁出图（BLOCKED），宁可不做也不造假、不擅自出网。

通道：
  LOCAL_FOOOCUS      本机 GPU + 后端就绪 → 本地出图（图不出厂，首选）
  PUBLIC_OPENSOURCE  本地不可用 → **自动**走公开开源渠道出真图（告知出网）
  BLOCKED            仅当 --no-public 且本地不可用 → 禁止出图
  （永不存在"模拟通道"—— 这是红线）

本模块只做**决策**，不产出任何图像；出图由 run_pipeline 按通道调用真实后端。

用法：
  python gate/backend_router.py                 # 自适应决策（默认公开渠道兜底）
  python gate/backend_router.py --no-public     # 隐私模式：图绝不出网
  python gate/backend_router.py --force-public  # 本机已就绪仍走公开渠道（显式覆盖）
  python gate/backend_router.py --json
"""
import argparse
import json
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import env_check                                             # noqa: E402


class BlockedError(RuntimeError):
    """禁止出图（隐私模式下本地不可用）。调用方必须中止，不得退而求其次。"""


def route(res=None, allow_public=True, force_public=False, no_public=False):
    """自适应决定出图通道。

    参数：
      allow_public : 是否允许公开开源渠道兜底（默认 True = 自适应）。
      force_public : 本机已就绪仍坚持走公开渠道（显式覆盖本地优先）。
      no_public    : 隐私模式——图绝不出网；本地不可用即 BLOCKED。

    返回 dict：
      channel   : 'LOCAL_FOOOCUS' | 'PUBLIC_OPENSOURCE' | 'BLOCKED'
      reason    : 人话原因
      action    : 使用者该做什么
      privacy   : 图是否出网
      allow_public_used : 是否用到了公开渠道
    """
    if res is None:
        res = env_check.run_full_check()

    v = res["verdict"]
    venv = res.get("venv") or {}
    backend_up = res.get("backend", {}).get("up")

    if v == "READY_LOCAL" and not force_public:
        return {"channel": "LOCAL_FOOOCUS",
                "reason": "本机 GPU 与 Fooocus-API 后端均已就绪。",
                "action": "直接 --execute 本地出图。",
                "privacy": "图不出本机（不出网、不按次付费）",
                "allow_public_used": False}

    # ---- 本地不可用（NEED_SETUP / NO_GPU / UNKNOWN）或显式 force_public ----
    if no_public or not allow_public:
        return {"channel": "BLOCKED",
                "reason": ("你已选择隐私模式（--no-public），图绝不出网；"
                           "而本机当前不具备本地出图条件（%s）。" % v),
                "action": ("二选一：\n"
                           "    A. 加载本机环境：跑「一键启动 Fooocus-API.bat」（GPU 机器）；\n"
                           "    B. 去掉 --no-public 允许公开开源渠道兜底（会告知出网）。\n"
                           "    在选定之前：禁止出图，也不会生成任何模拟图/占位图。"),
                "privacy": "未出图（隐私模式）",
                "allow_public_used": False}

    # 公开开源渠道兜底（自适应核心：不让使用者卡死）
    local_hint = ""
    if v == "NO_GPU":
        why = "本机无可用 GPU（或探测不到可信 GPU），已自动改走公开开源渠道完成任务。"
        local_hint = "    若日后装好 GPU 环境，可重新 --execute 自动转回本地（图不出厂）。"
    elif v == "NEED_SETUP":
        why = "检测到本机有 GPU，但出图环境未装好/未启动；已自动改走公开开源渠道先完成任务。"
        missing = venv.get("missing") or []
        steps = []
        if missing:
            steps.append("安装缺失依赖（%s）" % "、".join(missing))
        if not backend_up:
            steps.append("启动后端（监听 127.0.0.1:%s）" % res["backend"]["port"])
        if steps:
            local_hint = ("    想转回本地（图不出厂）：" + "；".join(steps) + "——\n"
                          "    跑「一键启动 Fooocus-API.bat」即可，装好后 --execute 自动走本地。")
        else:
            local_hint = "    想转回本地（图不出厂）：跑「一键启动 Fooocus-API.bat」后 --execute。"
    else:  # UNKNOWN 或 READY+force_public
        if v == "READY_LOCAL":
            why = "本机已就绪，但你显式要求走公开开源渠道（--force-public）。"
        else:
            why = "本机 GPU 探测手段全部失败、无法判定；已自动改走公开开源渠道完成任务。"
        local_hint = "    本机条件待确认；确认后可 --execute 自动转回本地。"

    return {"channel": "PUBLIC_OPENSOURCE",
            "reason": why,
            "action": ("调用平台提供的开源图像生成能力出真图（图会出网）。\n"
                       "    📢 已自动启用本通道并告知：你的图片将经由网络处理，\n"
                       "    若客户图涉密请改用 --no-public + 本地环境。\n" + local_hint),
            "privacy": "⚠ 图片出网（公开开源渠道，已自动启用并告知）",
            "allow_public_used": True}


def assert_can_render(decision):
    """闸门：通道为 BLOCKED 时抛异常，强制中止。调用方不得捕获后继续出图。"""
    if decision["channel"] == "BLOCKED":
        raise BlockedError(
            "【禁止出图】%s\n  该怎么做：%s\n  （红线：隐私模式下本地不可用即封锁；"
            "任何情况严禁模拟试跑、严禁出假图。）" % (decision["reason"], decision["action"]))


def human(decision, res):
    icons = {"LOCAL_FOOOCUS": "🟢 本地出图（图不出厂）",
             "PUBLIC_OPENSOURCE": "🔵 公开开源渠道（自动兜底）",
             "BLOCKED": "🔴 禁止出图（隐私模式）"}
    L = ["", "【出图通道决策】",
         "  通道：%s" % icons.get(decision["channel"], decision["channel"]),
         "  原因：%s" % decision["reason"],
         "  隐私：%s" % decision["privacy"],
         "  该怎么做：%s" % decision["action"]]
    if decision["channel"] == "PUBLIC_OPENSOURCE":
        L.append("  📢 告知：本任务将由公开开源渠道完成（图会出网）；"
                 "绝无模拟图/占位图，产出必为真实生成图。")
    if decision["channel"] == "BLOCKED":
        L.append("")
        L.append("  ⛔ 此刻不会生成任何图片 —— 包括模拟图、占位图、示意图。")
        L.append("     这是 2026-09-04 确立的红线，不可绕过。")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="出图通道自适应决策（拒绝模拟）")
    ap.add_argument("--no-public", action="store_true",
                    help="隐私模式：图绝不出网；本地不可用即禁止出图")
    ap.add_argument("--force-public", action="store_true",
                    help="本机已就绪仍坚持走公开渠道（显式覆盖本地优先）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fooocus-dir", default=None)
    ap.add_argument("--port", default=env_check.DEFAULT_PORT)
    args = ap.parse_args()

    res = env_check.run_full_check(args.fooocus_dir, args.port)
    decision = route(res, allow_public=True,
                     force_public=args.force_public, no_public=args.no_public)

    if args.json:
        print(json.dumps({"env": res, "decision": decision},
                         ensure_ascii=False, indent=2))
    else:
        print(env_check.human_report(res))
        print(human(decision, res))

    sys.exit(0 if decision["channel"] != "BLOCKED" else 2)


if __name__ == "__main__":
    main()
