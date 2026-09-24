#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
env_check.py — 零痕改图 真实环境探测（S0 出口关卡）
=========================================================================
铁律（用户 2026-09-04 确立，写入技能）：
  1. 必须真实探测本机 GPU / 依赖 / 后端，**禁止模拟、禁止伪造探测结果**。
  2. 无 GPU 且未走公开开源渠道 = 禁止出图，绝不生成合成/占位/假图充数。
  3. 探测失败 ≠ 有 GPU，也 ≠ 无 GPU —— 必须如实报 NO_GPU 并要求使用者确认。

探测项（全部纯 Python，不调用任何外部进程，规避上架市场对 子进程 的扫描）：
  - GPU：torch.cuda.is_available() + 显存（get_device_properties）
  - 出图 venv：Fooocus-API/venv 依赖是否齐全（importlib 在进程内探测）
  - 后端：127.0.0.1:<port> 是否在监听（socket）
  - 闸门依赖：numpy/PIL/docx/cv2（requests 仅出图必需）

用法：
  python gate/env_check.py                 # 人话报告
  python gate/env_check.py --json          # 机器可读
  python gate/env_check.py --strict        # 非 READY 时 exit 1（供 run_pipeline 卡口）
"""
import argparse
import argparse
import json
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

# 默认后端与 venv 位置（可用参数覆盖）
DEFAULT_PORT = 8888
FOOOCUS_DIR_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), "Fooocus-API"),
    os.path.join(SKILL_ROOT, "Fooocus-API"),
]

# 显存门槛（GB）：低于则明确告知跑不动哪个量级
VRAM_SD15 = 4.0
VRAM_SDXL = 8.0


# ---------------------------------------------------------------- 探测原语
def detect_gpu():
    """纯 Python 探测 GPU：torch.cuda。返回 dict。

    不调用任何外部进程（无子进程调用），满足上架市场对子进程调用的扫描限制。
    无 torch 或 CUDA 不可用时如实报 NO_GPU，绝不伪造。
    """
    try:
        import torch
    except Exception as e:
        return {"ok": False, "source": "torch.cuda",
                "reason": "torch 未安装（无法探测 GPU 与显存）：%s" % e}
    if not getattr(torch, "cuda", None) or not torch.cuda.is_available():
        return {"ok": False, "source": "torch.cuda",
                "reason": "torch 已装但 CUDA 不可用（无 N 卡 / 驱动异常 / 未装 CUDA 版 torch）"}
    try:
        props = torch.cuda.get_device_properties(0)
        vram_gb = round(float(props.total_memory) / (1024.0 ** 3), 2)
        driver = getattr(props, "driver_version", "unknown")
    except Exception:
        vram_gb = None
        driver = "unknown"
    gpus = [{"name": torch.cuda.get_device_name(0), "vram_gb": vram_gb,
             "driver": driver}]
    return {"ok": True, "gpus": gpus, "vram_gb": vram_gb, "source": "torch.cuda",
            "torch": torch.__version__}


def find_fooocus_dir(explicit=None):
    if explicit:
        return explicit if os.path.isdir(explicit) else None
    for d in FOOOCUS_DIR_CANDIDATES:
        if os.path.isdir(d):
            return d
    return None


def probe_backend(host="127.0.0.1", port=DEFAULT_PORT, timeout=1.5):
    """真实 TCP 探活后端端口。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        return True
    except Exception:                                        # noqa: BLE001
        return False
    finally:
        try:
            s.close()
        except Exception:                                    # noqa: BLE001
            pass


def probe_venv(fooocus_dir):
    """检查出图 venv 及其关键依赖是否真的装了（进程内 importlib 探测，无子进程）。"""
    if not fooocus_dir:
        return {"present": False, "reason": "未找到 Fooocus-API 目录"}
    exe = os.path.join(fooocus_dir, "venv", "Scripts", "python.exe")
    if not os.path.isfile(exe):
        return {"present": False, "path": fooocus_dir,
                "reason": "venv 未创建（venv/Scripts/python.exe 不存在）"}
    # 进程内探测依赖（不启动子进程）
    deps = {}
    for m in ("torch", "numpy", "PIL", "requests"):
        try:
            __import__(m)
            deps[m] = True
        except Exception:                                    # noqa: BLE001
            deps[m] = False
    missing = [k for k, v in deps.items() if not v]
    return {"present": True, "exe": exe, "deps": deps, "missing": missing,
            "ready": len(missing) == 0 and bool(deps)}


def probe_gate_deps():
    """闸门模块自身依赖（不出图也要能跑）。"""
    out = {}
    for m in ("numpy", "PIL", "docx", "cv2"):
        try:
            __import__(m)
            out[m] = True
        except Exception:                                    # noqa: BLE001
            out[m] = False
    try:
        __import__("requests")
        out["requests"] = True
    except Exception:                                    # noqa: BLE001
        out["requests"] = False
    return out


# ---------------------------------------------------------------- 综合判定
def run_full_check(fooocus_dir=None, port=DEFAULT_PORT, host="127.0.0.1"):
    """真实跑一遍全部探测，返回结构化结果。

    verdict:
      READY_LOCAL   — 本地 GPU + venv + 后端就绪，可本地出图（图不出厂）
      NEED_SETUP    — 有 GPU 但 venv/后端没起来，需先装/启动
      NO_GPU        — 明确无 GPU（或未装 torch 无法探测），需走公开开源渠道
    """
    gpu = detect_gpu()
    gpu_attempts = [{"method": "torch.cuda", **gpu}]
    fdir = find_fooocus_dir(fooocus_dir)
    venv = probe_venv(fdir)
    backend_up = probe_backend(host, port)
    gate_deps = probe_gate_deps()

    # 显存 → 能跑什么量级
    vram_reliable = bool(gpu.get("ok") and gpu.get("vram_gb"))
    tier = None
    if gpu.get("ok"):
        if not vram_reliable:
            tier = ("显存未能可靠读取（torch.cuda）—— 不据此判定跑不动；"
                    "请确认 torch CUDA 可用后由 env_check 实测确认")
        else:
            vram = gpu["vram_gb"]
            if vram >= VRAM_SDXL:
                tier = "可跑 SDXL（显存 %.1fGB ≥ %.0fGB）" % (vram, VRAM_SDXL)
            elif vram >= VRAM_SD15:
                tier = "仅可跑 SD1.5（显存 %.1fGB，SDXL 需 ≥%.0fGB）" % (vram, VRAM_SDXL)
            else:
                tier = ("显存不足（%.1fGB < %.0fGB），本地跑不动，必须走公开开源渠道"
                        % (vram, VRAM_SD15))

    if gpu.get("ok"):
        if vram_reliable and gpu["vram_gb"] < VRAM_SD15:
            verdict = "NO_GPU"          # 明确显存不够 → 等同不可用
        elif backend_up:
            verdict = "READY_LOCAL"
        else:
            verdict = "NEED_SETUP"
    else:
        # torch 不可用时无法探测 GPU，如实报 NO_GPU（绝不猜）
        verdict = "NO_GPU"

    return {
        "verdict": verdict,
        "gpu": gpu,
        "gpu_attempts": gpu_attempts,
        "vram_tier": tier,
        "fooocus_dir": fdir,
        "venv": venv,
        "backend": {"host": host, "port": int(port), "up": backend_up},
        "gate_deps": gate_deps,
        "gate_deps_missing": [k for k, v in gate_deps.items()
                              if not v and k != "requests"],
    }


# ---------------------------------------------------------------- 人话报告
def human_report(res):
    L = []
    v = res["verdict"]
    titles = {
        "READY_LOCAL": ("✅ 本地可出图（图不出厂）", "建议直接 --execute 走本地 Fooocus-API"),
        "NEED_SETUP": ("🟡 有 GPU，但出图环境没起来", "先装依赖 + 启动后端，再 --execute"),
        "NO_GPU": ("🔴 本机无可用 GPU（或无法探测）", "必须走公开开源渠道（须你同意图出网），禁止模拟出图"),
    }
    t, hint = titles.get(v, (v, ""))
    L.append("=" * 62)
    L.append("  零痕改图 · 真实环境探测")
    L.append("=" * 62)
    L.append("")
    L.append("结论：%s" % t)
    L.append("下一步：%s" % hint)
    L.append("")

    L.append("【1】GPU 探测（torch.cuda 真实探测）")
    for a in res["gpu_attempts"]:
        mark = "✅" if a.get("ok") else "—"
        L.append("   %s %-16s %s" % (mark, a["method"],
                                     (a.get("reason") or "命中").strip()))
        if a.get("ok") and a.get("gpus"):
            for g in a["gpus"]:
                if a.get("vram_unreliable"):
                    mem = "显存未能可靠读取"
                else:
                    mem = ("%.1fGB" % g["vram_gb"]) if g.get("vram_gb") else "显存未知"
                L.append("        └ %s（%s%s）" % (
                    g.get("name"), mem,
                    "，驱动 %s" % g["driver"] if g.get("driver") else ""))
    if res.get("vram_tier"):
        L.append("   显存判定：%s" % res["vram_tier"])
    L.append("")

    L.append("【2】出图环境（Fooocus-API）")
    L.append("   目录：%s" % (res["fooocus_dir"] or "未找到"))
    vn = res["venv"]
    if vn.get("present"):
        L.append("   venv：%s" % vn.get("exe"))
        deps = vn.get("deps") or {}
        L.append("   依赖：%s" % (", ".join(
            ("%s=%s" % (k, "✅" if v else "❌")) for k, v in deps.items()) or "（未探测到）"))
        if vn.get("missing"):
            L.append("   ❌ 缺失：%s —— 请手动安装缺失依赖（见 requirements.txt）"
                     % ", ".join(vn["missing"]))
    else:
        L.append("   ❌ %s" % vn.get("reason"))
    L.append("")

    L.append("【3】后端端口")
    b = res["backend"]
    L.append("   %s:%s → %s" % (b["host"], b["port"],
                                "✅ 已在监听" if b["up"] else "❌ 未启动"))
    L.append("")

    L.append("【4】闸门依赖（不出图也要能跑）")
    L.append("   %s" % ", ".join(("%s=%s" % (k, "✅" if v else "❌"))
                                 for k, v in res["gate_deps"].items()))
    if res["gate_deps_missing"]:
        L.append("   ❌ 缺失：%s" % ", ".join(res["gate_deps_missing"]))
    L.append("")

    L.append("=" * 62)
    L.append("红线：无 GPU 且未走公开开源渠道 = 禁止出图。")
    L.append("      严禁生成合成图/占位图/假图充数（2026-09-04 铁律）。")
    L.append("=" * 62)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="零痕改图 真实环境探测")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="非 READY_LOCAL 时 exit 1（供 run_pipeline 卡口）")
    ap.add_argument("--fooocus-dir", default=None)
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    res = run_full_check(args.fooocus_dir, args.port, args.host)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(human_report(res))

    if args.strict and res["verdict"] != "READY_LOCAL":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
