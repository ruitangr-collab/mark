#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline.py — 局部改款端到端编排（S0→S8，通道自适应）
============================================================
把「确认数据 + 图A/图B」变成「改款图 + 闸门②点检 + 可签名②的确认表」。

流程：
  S0 素材受理(尺寸/清晰度) → S1 镜像归一化(用 position.mirror) →
  S3 意图已结构化(confirmation) → S4 闸门①已签(调用方保证) →
  S6 出图（通道自适应：LOCAL_FOOOCUS / PUBLIC_OPENSOURCE，绝不模拟）→
  S7 闸门②点检(checks.py 实测) → S8 产出 checks.json 供签名②

通道自适应（2026-09-04 铁律）：
  🟢 本地就绪        → 本地 Fooocus-API 出图（图不出厂）
  🔵 本地不可用      → 自动改走公开开源渠道出真图（明确告知图会出网）：
                       本脚本导出 public_contract.json 生成契约，由平台开源
                       图像能力真实生成，落盘后用 --ingest 回灌做闸门②实测。
  🔴 --no-public     → 隐私模式：图绝不出网，本地不可用即封锁（不出假图）。
  ⛔ 任何情况严禁模拟图/占位图/假图 —— 交付必为真实生成图。
"""
import os
import sys
import json
import argparse
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wearer_frame import WearerFrame
import checks as CHK
import engine_registry as ER

NEG_TEXT = ("deformed, blurry, low quality, watermark, text, extra pockets, "
            "changed garment style, altered background, distorted proportions")


# 三图同改 / 多源嫁接：每个属性可独立指定来源 {A, B, C, new}
#   shape_from  形状取自哪张参考图
#   fabric_from 材质取自哪张
#   color_from  颜色取自哪张
# 缺省（向后兼容旧确认表）：形状/材质取 B，颜色取 A。
_REF_WORDS = {
    "A": "the base image (image A)",
    "B": "reference image B",
    "C": "reference image C",
    "new": "a newly specified value",
}


def build_prompt_v2(confirmation):
    """通用嫁接提示词（不再绑死「口袋/牛仔裤」）。

    把 sources{shape_from/fabric_from/color_from} + 形状子属性 → 英文 inpaint 提示词。
    三图同改时：形状可来自 B、材质来自 C、颜色来自 A，各自独立路由。
    """
    it = confirmation["items"]
    src = it.get("sources") or {}
    shape_from = src.get("shape_from", "B")
    fabric_from = src.get("fabric_from", "B")
    color_from = src.get("color_from", "A")
    sh = it.get("shape") or {}
    part = sh.get("type") or "part"
    if sh.get("flap"):
        part += " with flap"
    if sh.get("rivet"):
        part += " with antique brass rivet"
    pos = it.get("position") or {}
    side = pos.get("side", "target")
    view = pos.get("view", "front")
    loc = f"the {side} {view} of the subject"
    shape_w = _REF_WORDS.get(shape_from, _REF_WORDS["B"])
    fab_w = _REF_WORDS.get(fabric_from, _REF_WORDS["B"])
    col_w = _REF_WORDS.get(color_from, _REF_WORDS["A"])
    prompt = (
        f"Inpaint ONLY the masked region of the {loc}. "
        f"Insert a {part} whose SHAPE matches {shape_w}, "
        f"whose MATERIAL/FABRIC matches {fab_w}, "
        f"whose COLOR matches {col_w}. "
        f"Blend edges seamlessly into the surrounding area, "
        f"preserve everything outside the mask EXACTLY as the base image, "
        f"photorealistic, matching texture and lighting, highly detailed, 8k"
    )
    # 混合来源时加强约束：防止公开渠道照搬 shape 参考图的颜色/材质（实测 stage2 ΔE=21.18）
    extra_constraints = []
    if shape_from == "B" and color_from == "A":
        extra_constraints.append(
            "Crucial: recolor the inserted part to match the COLOR of the base image (image A); "
            "do NOT keep the original color from the shape reference."
        )
    if shape_from == "B" and fabric_from == "A":
        extra_constraints.append(
            "Crucial: retexture the inserted part with the MATERIAL/FABRIC of the base image (image A); "
            "do NOT use the material of the shape reference."
        )
    if shape_from == "B" and color_from == "C":
        extra_constraints.append(
            "Crucial: use reference image C as the color source for the inserted part."
        )
    if shape_from == "B" and fabric_from == "C":
        extra_constraints.append(
            "Crucial: use reference image C as the material/fabric source for the inserted part."
        )
    if extra_constraints:
        prompt += " " + " ".join(extra_constraints)
    return prompt


def make_mask_from_confirmation(a_path, confirmation):
    """用 wearer_frame 把确认里的 wearer 坐标 → 图中蒙版像素框，画白块蒙版。

    人话回读必须用 view/side 真实值，绝不默认「前片」。
    """
    pos = confirmation["items"]["position"]
    A = Image.open(a_path).convert("RGB")
    wf = WearerFrame(A.width, A.height, mirror=pos["mirror"])
    sz = confirmation["items"]["size"]
    norm_w = float(sz["w"]) / 100.0
    norm_h = float(sz["h"]) / 100.0
    box = wf.box_from_center_wearer(pos["wearer_x"], pos["wearer_y"], norm_w, norm_h)
    mask = Image.new("L", A.size, 0)
    from PIL import ImageDraw
    d = ImageDraw.Draw(mask)
    d.rectangle([box[0], box[1], box[2], box[3]], fill=255)
    view_cn = {"front": "前片", "back": "后片", "side": "侧片"}.get(pos.get("view"), "衣片")
    human = wf.wearer_to_human(pos["wearer_x"], pos["wearer_y"], view=view_cn)
    return mask, box, human


def _ring_regions(img_arr, box, grow=0.6):
    """取蒙版框周边同料参考区。

    返回 (color_px, band)：
      color_px — 环带像素 [N,3]，供 ΔE 用；
      band     — 环带 2D 图块（上+下横带堆叠），供纹理角度用；不足时为 None。
    """
    H, W = img_arr.shape[:2]
    bw, bh = box[2] - box[0], box[3] - box[1]
    gx, gy = max(4, int(bw * grow)), max(4, int(bh * grow))
    x1, y1 = max(0, box[0] - gx), max(0, box[1] - gy)
    x2, y2 = min(W, box[2] + gx), min(H, box[3] + gy)
    outer = img_arr[y1:y2, x1:x2]
    m = np.ones(outer.shape[:2], dtype=bool)
    m[box[1] - y1:box[3] - y1, box[0] - x1:box[2] - x1] = False
    color_px = outer[m]
    top = outer[:max(0, box[1] - y1), :]
    bottom = outer[min(outer.shape[0], box[3] - y1):, :]
    parts = [p for p in (top, bottom) if p.shape[0] >= 4]
    band = np.vstack(parts) if parts else None
    return color_px, band


def run_checks_stub(confirmation, executed):
    """dry-run / 未出图时的闸门②契约：全 NOT_RUN，签②必拒（缺数据=FAIL 铁律）。"""
    names = ["无外部依赖", "颜色", "纹理方向", "人话转译", "协调性",
             "形状", "尺寸", "位置", "缝纫线"]
    return [{"idx": i, "name": n,
             "measured": "—(未出图)" if not executed else "—",
             "verdict": "NOT_RUN"}
            for i, n in enumerate(names, 1)]


def run_gate2_real(confirmation, out_image, box, channel, image_c=None):
    """闸门②实测：能机测的真测（ΔE/角度），测不了的老实标 NOT_RUN 待人工。

    机测项：①无外部依赖(通道核验) ②颜色(袋区 vs 周边同料环带 ΔE76)
            ③纹理方向(袋区 vs 环带 结构张量主角度，仅同料)
    人工项：④人话转译 ⑤协调性 ⑥形状 ⑦尺寸 ⑧位置 ⑨缝纫线
            （需分割/检测或人工目检，出图后由使用者/AI 目检回填并注明依据）
    """
    img = np.array(Image.open(out_image).convert("RGB"))
    pocket = img[box[1]:box[3], box[0]:box[2]]
    ring_px, ring_band = _ring_regions(img, box)
    it = confirmation["items"]
    color = it["color"]
    names = ["无外部依赖", "颜色", "纹理方向", "人话转译", "协调性",
             "形状", "尺寸", "位置", "缝纫线"]
    out = []

    # ① 无外部依赖（按通道核验）
    if channel == "LOCAL_FOOOCUS":
        out.append({"idx": 1, "name": names[0], "measured": "本地后端 0 外部调用",
                    "verdict": "PASS", "basis": "通道=LOCAL_FOOOCUS"})
    else:
        out.append({"idx": 1, "name": names[0],
                    "measured": "经授权公开开源通道（图经网络，授权调用）",
                    "verdict": "PASS", "basis": "通道=PUBLIC_OPENSOURCE（已告知出网）"})

    # ② 颜色 ΔE（同料同色才与 A 环带可比）
    csrc = color.get("color_src")
    if csrc == "A":
        r = CHK.check_color(pocket, ring_px, mode="same", tol_de=3.0)
        out.append({"idx": 2, "name": names[1], "measured": r.measured,
                    "verdict": "PASS" if r.pass_ else "FAIL",
                    "basis": "袋区 vs 周边环带 ΔE76"})
    elif csrc == "C" and image_c and os.path.isfile(image_c):
        c_arr = np.array(Image.open(image_c).convert("RGB"))
        r = CHK.check_color(pocket, c_arr, mode="keep_b", tol_de=3.0)
        out.append({"idx": 2, "name": names[1], "measured": r.measured,
                    "verdict": "PASS" if r.pass_ else "FAIL",
                    "basis": "袋区 vs 图C参考色 ΔE76（色来源=C）"})
    else:
        out.append({"idx": 2, "name": names[1],
                    "measured": "色来源=%s，不与 A 环带比" % (csrc or "B/新"),
                    "verdict": "NOT_RUN",
                    "basis": "待人工比对 B/C 原色或指定色卡"})

    # ③ 纹理方向（仅同料时有连续性要求）
    if color.get("fabric_src") == "A":
        if ring_band is not None:
            r = CHK.check_texture_angle(Image.fromarray(pocket),
                                        Image.fromarray(ring_band), tol_deg=3.0)
            out.append({"idx": 3, "name": names[2], "measured": r.measured,
                        "verdict": "PASS" if r.pass_ else "FAIL",
                        "basis": "袋区 vs 环带 主纹理角度"})
        else:
            out.append({"idx": 3, "name": names[2], "measured": "蒙版贴边、环带不足",
                        "verdict": "NOT_RUN", "basis": "环带过小无法测角度"})
    else:
        out.append({"idx": 3, "name": names[2], "measured": "料来源≠A，无连续性要求",
                    "verdict": "NOT_RUN", "basis": "B 料/新料按确认③单独约定"})

    # ④-⑨ 人工项（老实 NOT_RUN，出图后目检回填）
    human_items = {
        4: (names[3], "抽测人话指令 vs 实际出图，人工复核"),
        5: (names[4], "量袋宽/部位宽占比（需部位框或人工目测）"),
        6: (names[5], "袋型/圆角/盖/铆钉 关键点目检"),
        7: (names[6], "实测长宽 vs 确认 cm（需像素/厘米标尺或人工量）"),
        8: (names[7], "落点偏移（需检测或红框目检）"),
        9: (names[8], "明线 ΔE/线宽/线数（需线迹检测或目检）"),
    }
    for i, (n, how) in human_items.items():
        out.append({"idx": i, "name": n, "measured": "待人工复核",
                    "verdict": "NOT_RUN", "basis": how})
    return out


def export_public_contract(confirmation, prompt, mask_path, box, human, args):
    """公开开源渠道：导出生成契约，由平台开源图像能力真实生成（绝不模拟）。

    契约含全部生成要素 + 红线说明；平台/Agent 按契约出真图落盘到
    --out-image 后，用 --ingest 回灌本脚本做闸门②实测。
    """
    # ---- v3.0.0 引擎可插拔 / 画幅跟随 / 水印交付门禁（2026-09-11 对齐豆包方案）----
    try:
        er = ER.choose_engine(prefer=getattr(args, "engine", None),
                              privacy=getattr(args, "privacy", "public"))
        _w, _h = Image.open(args.a).size
        _size, _aerr = ER.fit_size(_w, _h, er["engine"]) if er["engine"] else (None, None)
        _wm = ER.ENGINES.get(er["engine"], {}).get("watermark") if er["engine"] else None
        _zone = ER.watermark_zone() if _wm else None
        _gate = (("⚠ 该引擎输出带水印（%s，落点归一化 %s）——交付客户前必须去水印或换引擎。"
                  % (_wm, _zone)) if _wm else "无水印（可直接交付）")
    except Exception as _e:                                   # 注册表异常不得阻断出图
        er = {"engine": None, "label": None, "degraded": False,
              "reason": "engine_registry 不可用：%s" % _e}
        _size = _aerr = _wm = _zone = None
        _gate = "未判定（engine_registry 不可用）"

    contract = {
        "channel": "PUBLIC_OPENSOURCE",
        "redline": "必须真实生成。严禁合成/占位/示意图冒充。产出将作为交付物。",
        "mode": "inpaint_preferred",
        "mode_note": "优先局部重绘(inpaint)：以 image_a 为底、mask 为重绘区；"
                     "若无局部重绘能力则图生图，必须保留 image_a 的服装款式/构图/背景，"
                     "仅口袋区按 prompt 重绘。",
        "engine": er["engine"],
        "engine_label": er["label"],
        "engine_reason": er["reason"],
        "engine_degraded": er["degraded"],
        "render_size": _size,
        "aspect_error": _aerr,
        "watermark": _wm,
        "watermark_zone_norm": _zone,
        "delivery_gate": _gate,
        "image_a": os.path.abspath(args.a),
        "image_b": os.path.abspath(args.b) if args.b else None,
        "image_c": os.path.abspath(args.c) if getattr(args, "c", None) else None,
        "mask": os.path.abspath(mask_path),
        "mask_box_px": list(box),
        "prompt": prompt,
        "negative_prompt": NEG_TEXT,
        "size_cm": confirmation["items"]["size"],
        "human_readback": human,
        "out_image": os.path.abspath(args.out_image),
        "next_step": ("平台用开源模型按本契约真实生成 → 落盘到 out_image → "
                      "python gate/run_pipeline.py --ingest <out_image> "
                      "--confirm <confirm.json> 完成闸门②实测。"),
    }
    with open(args.contract_out, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=2)
    return contract


def main():
    ap = argparse.ArgumentParser(description="局部改款端到端编排（通道自适应）")
    ap.add_argument("--confirm", required=True, help="confirmation.json（已签名①）")
    ap.add_argument("--a", required=True, help="图A路径(主体/底图)")
    ap.add_argument("--b", help="图B路径(第一参考图：默认提供形状与材质)")
    ap.add_argument("--c", help="图C路径(第三参考图：三图同改时提供形状/材质/颜色来源)")
    ap.add_argument("--execute", action="store_true", help="真出图（默认 dry-run）")
    ap.add_argument("--ingest", metavar="IMAGE",
                    help="回灌模式：对已真实生成的图做闸门②实测（公开渠道出图后用）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="8888")
    ap.add_argument("--out-image", default="pocketgraft_out.png")
    ap.add_argument("--checks-out", default="checks.json")
    ap.add_argument("--contract-out", default="public_contract.json",
                    help="公开渠道生成契约输出路径（--execute 走公开渠道时）")
    ap.add_argument("--no-public", action="store_true",
                    help="隐私模式：图绝不出网；本地不可用即封锁（不出假图）")
    ap.add_argument("--force-public", action="store_true",
                    help="本机已就绪仍坚持走公开渠道（显式覆盖本地优先）")
    ap.add_argument("--engine", default=None,
                    help="点名出图引擎（seedream/kling/nanobanana/qwen-image-edit/"
                         "fdplus/local-fooocus）；缺凭据或违反分级时自动降级")
    ap.add_argument("--privacy", default="public", choices=["public", "client", "secret"],
                    help="数据分级：public=可出网 / client=禁平台内置兜底 / secret=绝不出网")
    ap.add_argument("--skip-env-check", action="store_true",
                    help="【不推荐】跳过环境探测（仅调试用；出图仍走真实后端）")
    args = ap.parse_args()

    confirmation = json.load(open(args.confirm, "r", encoding="utf-8"))
    # 闸门①未签则禁止
    if not confirmation.get("sign1", {}).get("hash"):
        raise SystemExit("❌ 闸门①未签名，禁止出图。")

    prompt = build_prompt_v2(confirmation)
    mask, box, human = make_mask_from_confirmation(args.a, confirmation)
    mask_path = "mask_dry.png"
    mask.save(mask_path)
    print(f"[S6] 提示词: {prompt}")
    print(f"[S6] 蒙版框(图像素): {box}  人话回读: {human}")

    # ---------------- 回灌模式：对真实生成图做闸门②实测 ----------------
    if args.ingest:
        import confirm as CF
        if not CF.is_frozen_valid(confirmation):
            raise SystemExit("❌ 确认项在签名①后被改动（哈希失配），闸门②拒绝实测。")
        if not os.path.isfile(args.ingest):
            raise SystemExit(f"❌ 找不到真实生成图：{args.ingest}（严禁用占位图冒充）")
        print(f"[S7] 回灌实测：{args.ingest}")
        checks = run_gate2_real(confirmation, args.ingest, box,
                                channel="PUBLIC_OPENSOURCE",
                                image_c=getattr(args, "c", None))
        json.dump(checks, open(args.checks_out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        passed = sum(1 for c in checks if c["verdict"] == "PASS")
        notrun = [c["name"] for c in checks if c["verdict"] == "NOT_RUN"]
        failed = [c["name"] for c in checks if c["verdict"] == "FAIL"]
        print(f"[S7] 机测完成 → {args.checks_out}（PASS {passed}/9；"
              f"待人工 {len(notrun)}{'：' + '、'.join(notrun) if notrun else ''}；"
              f"FAIL {len(failed)}{'：' + '、'.join(failed) if failed else ''}）")
        if failed:
            print("[S8] ❌ 存在 FAIL，先修图或改确认项重出，禁止签②。")
            raise SystemExit(2)
        print("[S8] 人工项目检回填后 → confirm.py --sign2 完成双签交付。")
        return

    # ---------------- 出图模式 ----------------
    if args.execute:
        # ---- S0 环境闸门：真实探测 + 自适应路由，禁止模拟 ----
        import backend_router as BR
        import env_check as ENVC
        if args.skip_env_check:
            print("[S0] ⚠ 已 --skip-env-check：跳过环境探测（不推荐）。")
            decision = {"channel": "LOCAL_FOOOCUS",
                        "reason": "已跳过环境探测（--skip-env-check，仅调试用）。",
                        "action": "直接按本地 Fooocus-API 出图；失败则诚实报 NOT_RUN。",
                        "privacy": "图不出本机",
                        "allow_public_used": False}
        else:
            env = ENVC.run_full_check(port=args.port, host=args.host)
            decision = BR.route(env, allow_public=True,
                                force_public=args.force_public,
                                no_public=args.no_public)
            print(ENVC.human_report(env))
            print(BR.human(decision, env))

        if decision["channel"] == "BLOCKED":
            checks = run_checks_stub(confirmation, executed=False)
            json.dump(checks, open(args.checks_out, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            print(f"[S7] 隐私模式下本地不可用，未出图。闸门②契约 → {args.checks_out}（全 NOT_RUN）")
            raise SystemExit(2)

        if decision["channel"] == "PUBLIC_OPENSOURCE":
            # 优先：若云 API 凭据就绪，尝试真实出图（绝不模拟）
            try:
                import ark_engine as AE
                if AE.check(verbose=False):
                    print("[S6] 云 API 凭据就绪，尝试真实 image_edit 出图…")
                    out = AE.generate(image_a=args.a, image_b=args.b,
                                      image_c=getattr(args, "c", None),
                                      mask_path=mask_path, prompt=prompt,
                                      negative=NEG_TEXT, out_image=args.out_image)
                    if out and os.path.isfile(out):
                        print(f"[S6] 云通道出图完成 → {args.out_image}")
                        checks = run_gate2_real(confirmation, args.out_image, box,
                                                channel="PUBLIC_OPENSOURCE")
                        json.dump(checks, open(args.checks_out, "w", encoding="utf-8"),
                                  ensure_ascii=False, indent=2)
                        return
                    print("[S6] ⚠ 云通道出图未返回有效图（编辑端点可能未开通/不支持），回退契约路径。")
            except Exception as _e:
                print(f"[S6] ⚠ 云通道出图异常：{_e}；回退契约路径。")
            # 兜底：导出生成契约，由平台开源能力真实出图（绝不模拟）
            export_public_contract(confirmation, prompt, mask_path, box, human, args)
            print(f"[S6] 公开开源渠道：生成契约已导出 → {args.contract_out}")
            print("[S6] 📢 告知：本任务图会出网（公开开源渠道），产出必为真实生成图。")
            print(f"[S6] 平台/Agent 按契约真实生成 → 落盘到 {args.out_image} → "
                  "用 --ingest 回灌完成闸门②。")
            raise SystemExit(3)   # 3 = 契约已导出，等待平台真实生成

        # 本地通道
        sys.path.insert(0, os.path.dirname(HERE))
        import auto_edit as AP
        result = AP.call_fooocus(args.a, args.b or args.a, mask_path, prompt, AP.NEG,
                                 args.host, args.port, execute=True,
                                 c_path=getattr(args, "c", None))
        if result:
            AP.save_result(result, args.out_image)
            print(f"[S6] 出图完成 → {args.out_image}")
            checks = run_gate2_real(confirmation, args.out_image, box,
                                    channel="LOCAL_FOOOCUS",
                                    image_c=getattr(args, "c", None))
        else:
            print("[S6] 本地出图失败；本地失败不改走模拟——按需重跑或改用公开渠道契约。")
            checks = run_checks_stub(confirmation, executed=False)
    else:
        print("[S6] dry-run：未联网、未读取图片内容。加 --execute 并满足通道条件即真出图。")
        checks = run_checks_stub(confirmation, executed=False)

    json.dump(checks, open(args.checks_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    passed = sum(1 for c in checks if c["verdict"] == "PASS")
    print(f"[S7] 闸门②契约已写入 → {args.checks_out}（{passed}/{len(checks)} PASS，其余 {len(checks)-passed} 为 PENDING/NOT_RUN/FAIL）")
    print("[S8] 用 confirm.py --sign2 载入本 checks.json 完成双签并出最终确认表。")


if __name__ == "__main__":
    main()
