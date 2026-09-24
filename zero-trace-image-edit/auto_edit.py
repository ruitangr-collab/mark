#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PocketGraft 一键 · 自动流水线(确定性部分 + 后端调用)
输入: 图A(目标裤子) 图B(裁好的口袋参考图) 一句中文指令
输出: 高清改款图(经 Fooocus 后端)

调用:
  # 只拼请求、不出图(默认,安全可演示)
  python auto_edit.py --a A.png --b B.png --sentence "把B的口袋原样放到A的右前袋,洗水和走线跟A一致"
  # 真出图(需先起 Fooocus API 服务,见 SKILL.md)
  python auto_edit.py --a A.png --b B.png --sentence "..." --execute

后端说明(已核对真实接口):
- 采用 Fooocus-API 风格多段上传接口 POST /v1/generation/image-prompt
  (官方文档示例验证可用),该接口原生支持:输入图 + 蒙版 + 参考图(cn_img) + 提示词,
  正好对应"inpaint A + 用 B 当参考 + 套提示词"。
- 官方 Fooocus --api 用 /v2/... 且为 base64 JSON,字段近似;本脚本默认 v1,
  装官方版时把 --port 指向 7860 并自行微调 endpoint 即可。
"""

import argparse
import json
import os
import time

# ---------- 1. 落袋位解析: 中文关键词 -> region_coords.json ----------
COORD_FILE = os.path.join(os.path.dirname(__file__), "region_coords.json")

def resolve_position(sentence):
    """从中文句里找落袋位关键词,返回坐标键名。找不到回退 right_front。"""
    with open(COORD_FILE, "r", encoding="utf-8") as f:
        coords = json.load(f)
    # 顺序很重要:越具体的关键词在前(避免被"右后"等更通用的先匹配掉)
    mapping = {
        "臀部下面": "right_back_low", "臀下": "right_back_low", "双袋": "right_back_low",
        "左前袋": "left_front", "左前": "left_front",
        "右前袋": "right_front", "右前": "right_front",
        "零钱袋": "coin", "表袋": "coin",
        "左后袋": "left_back", "左后": "left_back",
        "右后袋": "right_back", "右后": "right_back",
    }
    for kw, key in mapping.items():
        if kw in sentence:
            return key, coords[key]
    return "right_front", coords["right_front"]


# ---------- 2. 中文翻英文提示词(槽位填充) ----------
SLOT_DEFAULT = {
    "pocket_type": "welt",
    "wash": "mid-wash blue rigid denim",
    "stitching": "double topstitching in contrast thread",
    "hardware": "antique brass rivet",
}

POS_TPL = ("a {pocket_type} denim jeans pocket, made of the same {wash} as the garment, "
           "{stitching}, {hardware}, photorealistic, matching fabric texture and lighting, "
           "highly detailed, 8k")
NEG = ("extra pocket, deformed pocket, misaligned, distorted seams, low quality, blurry, "
       "watermark, mutated, cartoon, illustration, extra limbs")


def build_prompt(sentence, pos_key=None):
    is_accent = "撞色" in sentence
    if is_accent:
        # 撞色款专用模板(Coleman B 卡其 + A 牛仔):袋料保留 B 棕卡其
        pos = ("a single patch pocket on the back-right hip of denim trousers, "
               "made of Cedar-brown heavy canvas (contrasting with the indigo denim garment), "
               "single topstitching in mustard-yellow contrast thread, "
               "rounded upper corners, sharp lower corners, "
               "photorealistic, matching fabric texture and lighting, highly detailed, 8k")
    elif "同料" in sentence or pos_key == "right_back_low":
        # 同料款专用模板(Coleman B 袋型/走线/圆角 + A 牛仔布):料与裤身一致
        pos = ("a single patch pocket on the back-right hip of indigo denim trousers, "
               "same fabric as the garment, "
               "single topstitching in mustard-yellow contrast thread, "
               "rounded upper corners, sharp lower corners, "
               "photorealistic, matching fabric texture and lighting, highly detailed, 8k")
    else:
        slots = dict(SLOT_DEFAULT)
        if "明线" in sentence:
            slots["stitching"] = "double topstitching in contrast thread"
        if "黄铜" in sentence or "钉" in sentence:
            slots["hardware"] = "antique brass rivet"
        if "双唇" in sentence or "唇袋" in sentence:
            slots["pocket_type"] = "welt"
        pos = POS_TPL.format(**slots)
    # "原样"靠参考图B承载,文本只补一句,不污染袋型槽位
    if "原样" in sentence:
        pos = pos + ", identical to the supplied reference pocket"
    return pos


# ---------- 3. 按坐标生成蒙版 PNG(归一化框 -> 像素白块) ----------
def make_mask(a_path, coord, out_path="mask.png"):
    """在 A 图尺寸上,按归一化坐标画白色矩形蒙版(黑底),供 Fooocus inpaint。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("出图需要 Pillow,请先按 requirements.txt 安装依赖。")
    with Image.open(a_path) as im:
        w, h = im.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    x1, y1 = int(coord["x"] * w), int(coord["y"] * h)
    x2, y2 = int((coord["x"] + coord["w"]) * w), int((coord["y"] + coord["h"]) * h)
    d.rectangle([x1, y1, x2, y2], fill=255)
    mask.save(out_path)
    return out_path


# ---------- 4. 后端调用(Fooocus /v1/generation/image-prompt) ----------
def call_fooocus(a_path, b_path, mask_path, positive, negative, host, port, execute,
                 c_path=None):
    url = f"http://{host}:{port}/v1/generation/image-prompt"
    # B 作为参考图:ImagePrompt 类型,权重 0.6(stop 0.6)
    image_prompts = [{"cn_stop": 0.6, "cn_weight": 0.6, "cn_type": "ImagePrompt"}]
    # 三图同改：C 作为第二参考图（形状/材质/颜色来源），权重略低
    if c_path:
        image_prompts.append({"cn_stop": 0.5, "cn_weight": 0.5, "cn_type": "ImagePrompt"})
    data = {
        "prompt": positive,
        "negative_prompt": negative,
        "style_selections": "Fooocus Photograph",
        "image_prompts": json.dumps(image_prompts),
        "async_process": True,
    }

    if not execute:
        print("\n== DRY-RUN: 将发送如下请求(未联网,不读取图片) ==")
        print("POST", url)
        print("form 字段:", {k: (v if k != "image_prompts" else "见下") for k, v in data.items()})
        print("image_prompts:", image_prompts)
        print("files: input_image=A, input_mask=蒙版, cn_img1=B(参考图)" +
              (", cn_img2=C(第三参考图)" if c_path else ""))
        print("== 加 --execute 且起好 Fooocus API 即可真出图 ==")
        return None

    # 真正出图:读取图片与蒙版
    with open(a_path, "rb") as f:
        a_bytes = f.read()
    with open(b_path, "rb") as f:
        b_bytes = f.read()
    with open(mask_path, "rb") as f:
        m_bytes = f.read()
    files = {"input_image": a_bytes, "input_mask": m_bytes, "cn_img1": b_bytes}
    if c_path:
        with open(c_path, "rb") as f:
            files["cn_img2"] = f.read()

    try:
        import requests
    except ImportError:
        raise SystemExit("出图需要 requests,请先按 requirements.txt 安装依赖。")

    r = requests.post(url, data=data, files=files, timeout=120)
    r.raise_for_status()
    job = r.json()
    job_id = job.get("job_id") or job.get("request_id")
    print("已提交, job_id =", job_id)

    # 轮询结果
    for _ in range(60):
        q = requests.get(f"http://{host}:{port}/v1/generation/query-job",
                         params={"job_id": job_id}, timeout=30)
        q.raise_for_status()
        res = q.json()
        results = res.get("results") or []
        if results:
            return results[0]
        time.sleep(3)
    raise SystemExit("轮询超时,未拿到结果(后端可能在排队)")


def save_result(result, out_image):
    import requests as _req
    if isinstance(result, str) and result.startswith("data:image"):
        import base64
        b64 = result.split(",", 1)[1]
        with open(out_image, "wb") as f:
            f.write(base64.b64decode(b64))
    elif isinstance(result, str) and result.startswith("http"):
        with open(out_image, "wb") as f:
            f.write(_req.get(result, timeout=60).content)
    else:
        raise SystemExit("未知结果格式,无法保存")
    return out_image


def main():
    ap = argparse.ArgumentParser(description="PocketGraft 一键 自动流水线")
    ap.add_argument("--a", required=True, help="图A路径(目标裤子)")
    ap.add_argument("--b", required=True, help="图B路径(裁好的口袋参考图)")
    ap.add_argument("--sentence", required=True, help="一句中文指令")
    ap.add_argument("--host", default="127.0.0.1", help="Fooocus API 主机")
    ap.add_argument("--port", default="8888", help="Fooocus API 端口(官方--api用7860)")
    ap.add_argument("--execute", action="store_true", help="真正出图(默认 dry-run 只拼请求)")
    ap.add_argument("--out-json", default="payload.json", help="调试用 payload 文件")
    ap.add_argument("--out-image", default="pocketgraft_out.png", help="出图文件名")
    args = ap.parse_args()

    pos_key, coord = resolve_position(args.sentence)
    positive = build_prompt(args.sentence, pos_key=pos_key)
    mask_norm = {"x": coord["x"], "y": coord["y"], "w": coord["w"], "h": coord["h"]}

    # 调试载荷
    payload = {
        "input": {"image_a": args.a, "image_b_reference": args.b, "mask_normalized": mask_norm},
        "prompt": {"positive": positive, "negative": NEG},
        "params": {"steps": 30, "cfg": 7, "inpaint_denoise": 0.65, "upscale": "4x-UltraSharp"},
    }
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("落袋位解析 ->", pos_key, coord)
    print("英文提示词 ->", positive)
    print("蒙版(归一化) ->", mask_norm)

    if args.execute:
        mask_path = make_mask(args.a, coord)
        result = call_fooocus(args.a, args.b, mask_path, positive, NEG,
                               args.host, args.port, execute=True)
        if result:
            out = save_result(result, args.out_image)
            print("出图完成 ->", out)
    else:
        call_fooocus(args.a, args.b, "mask.png", positive, NEG,
                     args.host, args.port, execute=False)


if __name__ == "__main__":
    main()
