#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ark_engine.py — 火山方舟（Seedream）出图适配器（v3.0.0 新增）
=========================================================================
对齐豆包方案的主力通道：多参考图条件编辑（image1=主体 / image2=部件来源）。

凭据三级查找（任一命中即可，避免把 key 硬编码进技能包）：
  1. 环境变量   ARK_API_KEY
  2. 本机配置文件 ~/.workbuddy/ark_config.json  {"api_key": "...", "account_id": "..."}
  3. 命令行参数 --api-key（临时，不落盘）

绝不把 key 写进技能目录、绝不进版本库。缺凭据时**诚实报错**，
不伪造输出、不静默降级成假图。

用法：
  python gate/ark_engine.py --check                      # 只检查凭据是否就绪
  python gate/ark_engine.py --save --api-key <KEY>       # 安全落盘到 ~/.workbuddy/
  python gate/ark_engine.py --models                     # 列出可用出图模型
  python gate/ark_engine.py --ping                       # 真实连通性测试（会消耗极少额度）
"""
import argparse
import json
import os
import sys

CONF_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "ark_config.json")
DEFAULT_HOST = "https://ark.cn-beijing.volces.com/api/v3"
# 多参考图条件编辑主力模型（image_edit 能力）
DEFAULT_MODEL = "doubao-seedream-4-0-250828"

# 已知服务商预设：使用者只需报"我用哪家"，地址/模型自动带出。
# 官方方舟 Key 是 UUID 形（xxxxxxxx-xxxx-....）；中转服务的 Key 形如 apikey-日期-串，
# 必须配对应服务商的接口地址，否则官方端点会返回 401 格式错误。
PROVIDERS = {
    "ark":     {"label": "火山方舟（官方）", "host": "https://ark.cn-beijing.volces.com/api/v3",
                "key_hint": "UUID 形式，如 1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"},
    "custom":  {"label": "第三方中转 / 自建网关", "host": "",
                "key_hint": "由服务商提供，通常配一串接口地址（base url）"},
}


def load_credential(cli_key=None, cli_account=None):
    """按三级顺序找凭据。返回 (api_key, account_id, source)。"""
    if cli_key:
        return cli_key, cli_account, "命令行参数"
    env_key = os.environ.get("ARK_API_KEY")
    if env_key:
        return env_key, cli_account or os.environ.get("ARK_ACCOUNT_ID"), "环境变量"
    if os.path.isfile(CONF_PATH):
        try:
            with open(CONF_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("api_key"):
                return d["api_key"], cli_account or d.get("account_id"), "配置文件"
        except Exception:
            pass
    return None, cli_account, None


def load_runtime():
    """读运行参数（host / model / provider），全部可被使用者覆盖。"""
    cfg = {"host": DEFAULT_HOST, "model": DEFAULT_MODEL, "provider": "ark"}
    if os.path.isfile(CONF_PATH):
        try:
            with open(CONF_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            for k in ("host", "model", "provider"):
                if d.get(k):
                    cfg[k] = d[k]
        except Exception:
            pass
    return cfg


def save_credential(api_key, account_id=None, host=None, model=None, provider=None):
    """安全落盘到 ~/.workbuddy/ark_config.json（不在技能目录内）。

    ⚠ 安全红线：本函数只写使用者的**个人**配置目录，技能包内绝不存任何凭据。
    """
    os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)
    d = {}
    if os.path.isfile(CONF_PATH):
        try:
            with open(CONF_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
    d["api_key"] = api_key
    if account_id:
        d["account_id"] = account_id
    d["provider"] = provider or d.get("provider") or "ark"
    d["host"] = host or d.get("host") or DEFAULT_HOST
    d["model"] = model or d.get("model") or DEFAULT_MODEL
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONF_PATH, 0o600)
    except Exception:
        pass
    return CONF_PATH


def mask_credential(k):
    if not k:
        return "(无)"
    return k[:6] + "…" + k[-4:] if len(k) > 12 else "***"


# 常见 Seedream 图像模型 ID 候选（用于开通状态巡检）
# 说明：带日期后缀的是「正式模型 ID」（方舟按此开通与调用）；
#       去掉日期后缀的简名在方舟上通常是 NotFound，仅保单条巡检的可读性。
SEEDREAM_CANDIDATES = [
    "doubao-seedream-5-0-pro-260628",
    "doubao-seedream-5-0-260128",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-4-0-250828",
    "doubao-seedream-4-0-20260415",
    "doubao-seedream-5-0-pro",
    "doubao-seedream-4-5",
    "doubao-seedream-4-0",
]

# 【易混淆提醒】Seedream=图像生成/编辑（我们要的）；Seedance=视频生成（别开这个）。
# 两者在控制台「开通管理」里名字相邻、只差三个字母，是本技能最常见的开通踩坑点。


def probe_models(key=None):
    """巡检账号下各 Seedream 模型的**真实开通状态**。

    一次性回答"到底哪个能用"，免去逐个手试。
    区分三类结局：
      ✅ OK                 可用
      ⚠ ModelNotOpen        模型存在但未开通（去控制台开通即可）
      ✗ InvalidEndpoint...  模型 ID 不存在（名字写错）
    """
    import requests
    rt = load_runtime()
    url = rt["host"].rstrip("/") + "/images/generations"
    if not key:
        key, _, _ = load_credential()
    if not key:
        print("❌ 无凭据，先 --save 或 --guide")
        return []
    print("【Seedream 模型开通状态巡检】")
    print("  端点:", url)
    print()
    print("  %-36s %-6s %s" % ("模型 ID", "HTTP", "结论"))
    print("  " + "-" * 62)
    ok_list = []
    paused_list = []
    for m in SEEDREAM_CANDIDATES:
        try:
            r = requests.post(url, headers={"Authorization": "Bearer " + key,
                                            "Content-Type": "application/json"},
                              json={"model": m, "prompt": "a red square",
                                    "size": "1024x1024", "n": 1}, timeout=60)
            try:
                code = json.loads(r.text).get("error", {}).get("code", "")
            except Exception:
                code = ""
            if r.status_code == 200:
                concl, mark = "✅ 可用", "✅"
                ok_list.append(m)
            elif code == "ModelNotOpen":
                concl, mark = "⚠ 存在但未开通 → 去控制台「开通管理」点开通", "⚠"
            elif code == "SetLimitExceeded":
                concl, mark = ("⚠ 已开通，但被「安全体验模式」额度上限暂停 → "
                               "去「开通管理」调整或关闭安全体验模式"), "⛔"
                paused_list.append(m)
            elif code in ("InvalidEndpointOrModel.NotFound", "NotFound"):
                concl, mark = "✗ 模型 ID 不存在（名字有误）", "✗"
            else:
                concl, mark = ("? %s" % (code or r.text[:60])), "?"
            print("  %-36s %-6s %s %s" % (m, r.status_code, mark, concl))
        except Exception as e:
            print("  %-36s %-6s ERR %s" % (m, "-", e))
    print()
    if ok_list:
        print("  ✅ 可用模型：%s" % "、".join(ok_list))
        print("     用它落盘：python gate/ark_engine.py --save --api-key <KEY> --model %s" % ok_list[0])
    if paused_list:
        print("  ⛔ 被额度暂停的模型：%s" % "、".join(paused_list))
        print('     这不是「没开通」，是「安全体验模式」把额度卡死了。')
        print("     去方舟「开通管理」→ 找到该模型行 → 操作列「调整安全体验模式」→")
        print("     改为按量付费 / 关闭体验模式；或领右侧「免费资源包」再试。")
    if not ok_list and not paused_list:
        print("  ⚠ 没有可直接调用的模型。四种可能，按顺序排查：")
        print("   ① 开通没真正生效 —— 控制台「开通管理」必须【搜 Seedream 不是 Seedance】，")
        print("      勾选后还要勾【同意服务条款】再点确认开通，之后等 1~3 分钟。")
        print("   ② 账号未实名 —— 「账号管理 → 实名认证」未完成时搜不到 Seedream 条目。")
        print("   ③ Key 与开通不在同一项目 —— 换该项目下新建的 Key 再试。")
        print("   ④ 安全体验模式额度耗尽 —— 报 SetLimitExceeded 时见上方专项提示。")
        print("     注意别开成 Doubao-Seedance（视频），我们要的是 Doubao-Seedream（图像）。")


def list_models(key=None, keyword=None):
    """列出账号可见的模型目录（GET /models），并按需筛选。

    ⚠ 语义提醒：该端点返回的是**方舟平台模型目录**（可见即列出），
      不直接等于"已开通清单"。真实开通状态以 probe_models 的调用结果为准。
      它的价值在于：① 纠正模型 ID 的拼写；② 发现同代的新模型（如 5.0 的 pro/非 pro）。
    """
    import requests
    rt = load_runtime()
    url = rt["host"].rstrip("/") + "/models"
    if not key:
        key, _, _ = load_credential()
    if not key:
        print("❌ 无凭据，先 --save 或 --guide")
        return []
    try:
        r = requests.get(url + "?page_size=200",
                         headers={"Authorization": "Bearer " + key}, timeout=60)
    except Exception as e:
        print("❌ 请求失败：%s" % e)
        return []
    if r.status_code != 200:
        print("❌ HTTP %s  %s" % (r.status_code, r.text[:200]))
        return []
    try:
        items = json.loads(r.text).get("data", [])
    except Exception:
        print("❌ 返回无法解析")
        return []
    kw = (keyword or "").lower()
    hits = [it for it in items if kw in str(it.get("id", "")).lower()]
    print("【模型目录】共 %d 条%s" % (len(items), ("，含 '%s' 的 %d 条" % (keyword, len(hits))) if kw else ""))
    print("  %-42s %s" % ("模型 ID", "status"))
    print("  " + "-" * 56)
    for it in hits:
        print("  %-42s %s" % (it.get("id", ""), it.get("status")))
    print()
    print("  提示：上面的 status 是平台目录状态（Shutdown/Retiring/空），")
    print("        能不能调，要以 --probe 的实调结果为准。")
    return hits


def check(cli_key=None, cli_account=None, verbose=True):
    key, acct, src = load_credential(cli_key, cli_account)
    ready = bool(key)
    if verbose:
        print("【火山方舟凭据检查】")
        print("  状态   :", "✅ 已就绪" if ready else "❌ 未配置")
        print("  来源   :", src or "无")
        print("  API Key:", mask_credential(key))
        print("  账号ID :", acct or "(未提供)")
        print("  配置档 :", CONF_PATH if os.path.isfile(CONF_PATH) else "(无)")
        if not ready:
            print()
            print("  怎么配（任选其一）：")
            print("    A. 环境变量    export ARK_API_KEY=<你的Key>")
            print("    B. 安全落盘    python gate/ark_engine.py --save --api-key <你的Key> --account <你的账号ID>")
            print("    C. 临时传入    python gate/ark_engine.py --api-key <你的Key> ...")
            print()
            print("  红线：无凭据时**不伪造出图结果**，如实报错。")
    return ready


def _client(key):
    try:
        import requests  # noqa
    except ImportError:
        raise SystemExit("缺 requests：请先安装 requests 库（见 requirements.txt）")
    return key


def ping(key, host=None, model=None):
    """真实连通性测试：只发一次极小的请求确认鉴权与配额。"""
    import requests
    rt = load_runtime()
    host = host or rt["host"]
    model = model or rt["model"]
    url = host.rstrip("/") + "/images/generations"
    payload = {"model": model, "prompt": "a red square", "size": "1024x1024", "n": 1}
    print("  端点   :", url)
    print("  模型   :", model)
    try:
        r = requests.post(url, headers={"Authorization": "Bearer " + key,
                                        "Content-Type": "application/json"},
                          json=payload, timeout=60)
    except Exception as e:
        print("  ❌ 连不上该端点：%s" % e)
        print("     → 若用的是中转服务，请用 --host 指定服务商给的接口地址。")
        return False
    print("  HTTP", r.status_code)
    print("  响应:", r.text[:400])
    if r.status_code == 200:
        print("  ✅ 鉴权与出图链路正常")
        return True
    if r.status_code in (401, 403):
        body = r.text
        if "format is incorrect" in body:
            print("  ❌ Key 格式与该端点不匹配 ——")
            print("     官方方舟端点要 UUID 形式的 Key；你给的像是中转服务的 Key。")
            print("     解法：用 --host 换成服务商提供的接口地址，或改用官方方舟 Key。")
        else:
            print("  ❌ 鉴权失败 —— Key 无效，或账号未开通该模型")
    elif r.status_code == 404:
        print("  ⚠ 端点或模型名不对 —— 按你控制台实际开通的模型改 --model")
    else:
        print("  ⚠ 非预期状态，按响应内容判断")
    return False


def generate(image_a, image_b=None, image_c=None, mask_path=None, prompt="",
             negative="", out_image="out.png", host=None, model=None, key=None):
    """真实出图（Seedream image_edit 多参考图条件编辑）。

    返回落盘后的图片路径；任何失败都**抛异常**，绝不返回占位/假图。
    端点当前为 /images/editing（方舟 image_edit）。若该端点在本账号未开通，
    会抛出 RuntimeError，调用方据此诚实回退到公开契约路径。

    参数：
      image_a   主体/底图（必填）
      image_b   第一参考图（形状/材质来源）
      image_c   第三参考图（三图同改时的额外来源）
      mask_path 蒙版（inpaint 区；无则整图按 prompt 重绘）
      prompt / negative  提示词
    """
    import io
    import base64
    import urllib.request
    import ssl
    rt = load_runtime()
    host = host or rt["host"]
    model = model or rt["model"]
    if key is None:
        key, _, _ = load_credential()
    if not key:
        raise RuntimeError("无凭据，无法出图（先 ark_engine.py --save 绑定）。")

    files = [("image", image_a)]
    if image_b:
        files.append(("image", image_b))
    if image_c:
        files.append(("image", image_c))
    if mask_path:
        files.append(("mask", mask_path))

    boundary = "----wbseedreamboundary"
    body = io.BytesIO()

    def _field(name, val):
        body.write(("--%s\r\n" % boundary).encode())
        body.write(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        body.write(val.encode("utf-8") if isinstance(val, str) else val)
        body.write(b"\r\n")

    _field("model", model)
    _field("prompt", prompt)
    if negative:
        _field("negative_prompt", negative)
    for i, (kind, path) in enumerate(files):
        fn = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        body.write(("--%s\r\n" % boundary).encode())
        body.write(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                    % (kind, fn)).encode())
        body.write(b"Content-Type: image/png\r\n\r\n")
        body.write(data)
        body.write(b"\r\n")
    body.write(("--%s--\r\n" % boundary).encode())
    payload = body.getvalue()

    url = host.rstrip("/") + "/images/editing"
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "multipart/form-data; boundary=%s" % boundary})
    try:
        r = urllib.request.urlopen(req, timeout=180,
                                   context=ssl.create_default_context())
        resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("Seedream image_edit HTTP %s: %s"
                           % (e.code, e.read().decode("utf-8")[:300]))
    except Exception as e:  # 超时/连接等
        raise RuntimeError("Seedream image_edit 请求失败: %s" % e)

    # 解析返回（兼容 b64 / url 两种）
    b64 = None
    url_out = None
    if isinstance(resp, dict):
        arr = resp.get("data") or []
        if arr and isinstance(arr[0], dict):
            b64 = arr[0].get("b64_json")
            url_out = arr[0].get("url")
    if b64:
        with open(out_image, "wb") as f:
            f.write(base64.b64decode(b64))
        return out_image
    if url_out:
        try:
            r2 = urllib.request.urlopen(url_out, timeout=120,
                                        context=ssl.create_default_context())
            with open(out_image, "wb") as f:
                f.write(r2.read())
            return out_image
        except Exception as e:
            raise RuntimeError("Seedream 返回图片 URL 但下载失败: %s" % e)
    raise RuntimeError("Seedream image_edit 未返回图片（响应: %s）"
                       % json.dumps(resp, ensure_ascii=False)[:300])


def guide():
    """面向小白的绑定向导：一步一步说清怎么拿到自己的 Key。

    封装成 SKILL 后，使用者点开这里就能自助完成绑定，无需看文档。
    """
    print("""
╔══════════════════════════════════════════════════════════════════╗
║         火山方舟（Seedream）出图引擎 —— 自助绑定向导             ║
╚══════════════════════════════════════════════════════════════════╝

【为什么要绑定】
  本技能默认走"零配置"通道就能出图（装机即用，无需任何 Key）。
  但默认通道有两个已知限制：画幅被锁方图、成图带平台水印。
  想要和商业级效果对齐（原生画幅 + 无水印 + 二轮精修），
  接一个你自己的方舟账号即可解锁 —— 这就是"引擎可插拔"。

【怎么拿到自己的 Key】（约 3 分钟）
  1. 浏览器打开   https://console.volcengine.com/ark
  2. 用你的账号登录（没有就注册，实名后可用）
  3. 左侧菜单 → 「API Key 管理」→ 「创建 API Key」
  4. 复制那串 Key（UUID 形式，如 1a2b3c4d-5e6f-...）
  5. 左侧菜单 → 「开通管理」→ 找到 Seedream / 豆包图像 → 开通
     （不开通会报 403 无权限）

【绑定到本技能】（复制一行，把 <你的KEY> 换掉）

  python gate/ark_engine.py --save --api-key <你的KEY>

  如果你用的是第三方中转服务（而非官方方舟），再加 --host：
  python gate/ark_engine.py --save --api-key <你的KEY> --host <服务商接口地址>

【验证】

  python gate/ark_engine.py --check   # 看凭据在不在
  python gate/ark_engine.py --ping    # 真连一次，成功会说 ✅

【安全说明】
  · 你的 Key 只存在你自己的电脑里：~/.workbuddy/ark_config.json
  · 绝不会写进技能包、不会上传、不会分享给其他人
  · 每个使用者绑自己的账号，各用各的额度，互不影响
  · 随时可以删除该文件解绑

【不想绑也能用】
  不绑 = 走默认零配置通道，照样出图，只是画幅和水印差一些。
  涉密客户图请改用本机通道（--privacy secret，图不出网）。
""")


def leak_audit():
    """发布前安全自检：确认技能包内**零凭据残留**。

    上架前必须跑，确保没有任何使用者的 Key 被误打包进去。
    """
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.dirname(here)
    pat = re.compile(r"(api[-_]?key\s*[:=]\s*[\"']?[A-Za-z0-9\-_]{16,}"
                     r"|apikey-\d{8,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                     re.I)
    hits = []
    for root, dirs, files in os.walk(skill_root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for fn in files:
            if not fn.lower().endswith((".py", ".json", ".md", ".txt", ".bat")):
                continue
            fp = os.path.join(root, fn)
            if os.path.abspath(fp) == os.path.abspath(__file__):
                continue                       # 本文件含检测规则字符串，跳过
            try:
                txt = open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for m in pat.finditer(txt):
                s = m.group(0)
                if "你的KEY" in s or "your" in s.lower() or "<" in s:
                    continue
                hits.append((os.path.relpath(fp, skill_root), s[:40]))
    print("【技能包凭据泄漏自检】")
    print("  扫描目录:", skill_root)
    if hits:
        print("  ❌ 发现疑似凭据 %d 处，禁止上架：" % len(hits))
        for f, s in hits:
            print("     -", f, "→", s)
        return False
    print("  ✅ 未发现凭据残留，可安全上架")
    print("  （使用者凭据只存 ~/.workbuddy/ark_config.json，与技能包物理隔离）")
    return True


def main():
    ap = argparse.ArgumentParser(description="火山方舟（Seedream）出图适配器")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--account", default=None, help="火山方舟账号 ID")
    ap.add_argument("--host", default=None, help="接口地址（用中转服务时指定）")
    ap.add_argument("--model", default=None, help="模型名（默认 doubao-seedream-4-0-250828）")
    ap.add_argument("--provider", default=None, choices=list(PROVIDERS), help="服务商预设")
    ap.add_argument("--save", action="store_true", help="把凭据安全落盘到 ~/.workbuddy/ark_config.json")
    ap.add_argument("--check", action="store_true", help="只检查凭据")
    ap.add_argument("--ping", action="store_true", help="真实连通性测试")
    ap.add_argument("--guide", action="store_true", help="小白版自助绑定向导")
    ap.add_argument("--audit", action="store_true", help="发布前自检：技能包内是否残留凭据")
    ap.add_argument("--probe", action="store_true", help="巡检账号下 Seedream 模型开通状态")
    ap.add_argument("--list-models", action="store_true", help="列出账号可见的模型目录（可配 --keyword 筛选）")
    ap.add_argument("--keyword", default=None, help="配合 --list-models 做关键字筛选，如 seedream")
    args = ap.parse_args()

    if args.guide:
        guide()
        return

    if args.list_models:
        list_models(args.api_key, args.keyword)
        return

    if args.probe:
        probe_models(args.api_key)
        return

    if args.audit:
        sys.exit(0 if leak_audit() else 1)

    if args.save:
        if not args.api_key:
            raise SystemExit("❌ --save 需要同时提供 --api-key。不知道去哪拿？先跑 --guide")
        host = args.host
        if not host and args.provider and PROVIDERS[args.provider]["host"]:
            host = PROVIDERS[args.provider]["host"]
        p = save_credential(args.api_key, args.account, host, args.model, args.provider)
        print("✅ 凭据已落盘：", p, "（权限 600，不在技能目录内）")
        check(args.api_key, args.account)
        return

    if args.ping:
        key, acct, src = load_credential(args.api_key, args.account)
        if not key:
            raise SystemExit("❌ 无凭据，无法测试。先 --save，或跑 --guide 看怎么绑定。")
        print("【连通性测试】来源:", src)
        sys.exit(0 if ping(key, args.host, args.model) else 1)

    check(args.api_key, args.account)


if __name__ == "__main__":
    main()
