#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_article.py —— 公众号文章图文本地化（层2）

输入: agent-browser 渲染后保存的 HTML 文件(推荐) 或 文章 URL(curl 不可靠后备)
输出: <outdir>/article.md (标题/作者/时间/正文) + <outdir>/images/imgN.jpg (下载的图)

⚠️ 为什么需浏览器渲染: 微信文章 #js_content 正文与 data-src 图靠 JS 注入/懒加载，
   纯 curl 常拿到无正文的壳页。请先用 agent-browser 渲染并存 HTML 再喂本脚本。
"""
import sys, os, re, subprocess

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def load_html(src):
    if src.startswith("http://") or src.startswith("https://"):
        print("[warn] 用 curl 直接抓公众号不可靠(微信反爬常返回壳页)，推荐喂 agent-browser 渲染后的 HTML 文件", file=sys.stderr)
        r = subprocess.run(["curl", "-s", "-m", "30", "-A", UA, src], capture_output=True, text=True)
        return r.stdout
    return open(src, encoding="utf-8", errors="ignore").read()


def clean_text(h):
    h = re.sub(r'<br\s*/?>', '\n', h)
    h = re.sub(r'</p>', '\n', h)
    h = re.sub(r'<[^>]+>', '', h)
    return h.strip()


def main():
    if len(sys.argv) < 2:
        print("usage: fetch_article.py <rendered.html | url> [outdir]")
        sys.exit(1)
    src = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/wechat_demo"
    os.makedirs(outdir, exist_ok=True)
    imgdir = os.path.join(outdir, "images")
    os.makedirs(imgdir, exist_ok=True)

    html = load_html(src)
    print(f"HTML bytes: {len(html)}")

    m = re.search(r'<h1[^>]*class="rich_media_title"[^>]*>(.*?)</h1>', html, re.S)
    title = re.sub(r'<.*?>', '', m.group(1)).strip() if m else ""
    if not title:
        m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        title = m.group(1) if m else "untitled"

    m = re.search(r'id="js_name"[^>]*>(.*?)</a>', html, re.S)
    author = re.sub(r'<.*?>', '', m.group(1)).strip() if m else ""
    m = re.search(r'id="publish_time"[^>]*>([^<]*)<', html)
    publish = m.group(1).strip() if m else ""

    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)<script', html, re.S)
    if not m:
        m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', html, re.S)
    body = m.group(1) if m else html
    if not m:
        print("[warn] 未找到 #js_content，可能拿到壳页（纯 curl 常见）。请用 agent-browser 渲染后存 HTML 再跑。", file=sys.stderr)

    # 图: data-src/src 真实值优先，再全页兜底；只留文中图，排除头像/ CSS
    imgs = re.findall(r'(?:data-src|src)="(https://mmbiz\.qpic\.cn/sz_mmbiz_(?:jpg|png|gif|jpeg)/[^"\' ),]+)"', body)
    imgs += re.findall(r'https://mmbiz\.qpic\.cn/sz_mmbiz_(?:jpg|png|gif|jpeg)/[^"\' ),]+', body)
    imgs = [u for u in imgs if "qlogo" not in u and "mmbizappmsg" not in u]
    imgs = list(dict.fromkeys(imgs))

    def repl_img(match):
        ds = re.search(r'(?:data-src|src)="([^"]*mmbiz[^"]*)"', match.group(0))
        if not ds or ds.group(1) not in imgs:
            return ""
        i = imgs.index(ds.group(1))
        return f"\n![图{i+1}](images/img{i+1}.jpg)\n"

    body2 = re.sub(r'<img[^>]*>', repl_img, body, flags=re.S)
    body2 = clean_text(body2)

    for i, u in enumerate(imgs):
        subprocess.run(["curl", "-s", "-m", "25", "-A", UA,
                        "-e", "https://mp.weixin.qq.com/", u,
                        "-o", os.path.join(imgdir, f"img{i+1}.jpg")])

    md = f"# {title}\n\n"
    if author:
        md += f"> 作者: {author}\n"
    if publish:
        md += f"> 发布时间: {publish}\n"
    md += f"> 来源: {src}\n\n---\n\n" + body2 + "\n"

    mdpath = os.path.join(outdir, "article.md")
    open(mdpath, "w", encoding="utf-8").write(md)
    print(f"标题: {title}")
    print(f"作者: {author} | 时间: {publish}")
    print(f"图片: {len(imgs)} 张 -> {imgdir}")
    print(f"MD: {mdpath}")


if __name__ == "__main__":
    main()
