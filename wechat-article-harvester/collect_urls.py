#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat_mp_collect.py — 本机一键采集公众号「已发表内容」全部文章 URL
=====================================================================
用途: 自动翻页/滚动抽取你公众号后台「已发表内容」里所有公开文章链接,
      去重后写入 urls.txt, 然后贴给二货跑 import_urls + 镜像资料库。

前置(只需一次):
  1) 安装 agent-browser:
       npm install -g agent-browser
       agent-browser install
  2) 用你的号扫码登录并保存会话(必须在你本机跑, 沙箱跑不了):
       agent-browser --headed --profile ~/.wechat-harvest open "https://mp.weixin.qq.com/"
       # 弹出的浏览器里扫码/账号登录
       agent-browser --profile ~/.wechat-harvest auth save wechat-mp

使用:
  python3 collect_urls.py
  # 可选环境变量:
  #   WB_PROFILE=~/.wechat-harvest   登录会话目录
  #   WB_OUT=urls.txt                输出文件
  #   WB_MAX_PAGES=200               最大翻页数(防失控)
  #   WB_LIST_URL=...                自定义列表页(一般不用改)

产出: urls.txt (每行一个去重后的文章 URL)
"""
import subprocess, re, sys, time, os

PROFILE = os.path.expanduser(os.environ.get("WB_PROFILE", "~/.wechat-harvest"))
OUT = os.environ.get("WB_OUT", "urls.txt")
MAX_PAGES = int(os.environ.get("WB_MAX_PAGES", "200"))
LIST_URL = os.environ.get(
    "WB_LIST_URL",
    "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&action=list&lang=zh_CN&count=10",
)
# 下一页/加载更多 候选文案(按出现概率排序)
NEXT_CANDIDATES = ["加载更多", "查看更多", "下一页", "Next", "next", "下一頁"]
URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/s\?[^\s\"'<>]*?__biz=[^\s\"'<>]+")


def ab(args):
    cmd = ["agent-browser", "--profile", PROFILE] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(f"[warn] {' '.join(cmd)} -> {r.stderr.strip()[:200]}\n")
    return r.stdout


def extract_urls():
    html = ab(["get", "html"])
    return set(URL_RE.findall(html))


def click_next():
    for cand in NEXT_CANDIDATES:
        r = subprocess.run(
            ["agent-browser", "--profile", PROFILE, "find", "text", cand, "click"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return True
    return False


def scroll_down():
    ab(["scroll", "down", "3000"])
    return True


def advance():
    # 先试分页/加载更多按钮, 再试滚动(应对无限滚动)
    return click_next() or scroll_down()


def main():
    all_urls = set()
    print(f"[*] 打开列表页: {LIST_URL}")
    ab(["open", LIST_URL])
    time.sleep(3)
    consecutive_no_new = 0
    for page in range(1, MAX_PAGES + 1):
        urls = extract_urls()
        new = urls - all_urls
        all_urls |= urls
        print(f"[page {page:>3}] 本页 {len(urls):>4} 链接, 新增 {len(new):>4}, 累计 {len(all_urls):>5}")
        if new:
            consecutive_no_new = 0
        else:
            consecutive_no_new += 1
        if consecutive_no_new >= 2:
            print("[*] 连续两页无新增 -> 采集结束")
            break
        if not advance():
            if not new:
                print("[*] 找不到下一页/加载更多, 且本页无新增 -> 结束")
                break
        time.sleep(2.5)
    # 收尾
    subprocess.run(["agent-browser", "--profile", PROFILE, "close"], capture_output=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for u in sorted(all_urls):
            f.write(u + "\n")
    print(f"\n[done] 共采集 {len(all_urls)} 个去重 URL -> {OUT}")
    if not all_urls:
        print("[!] 未采到任何 URL。请确认: 1) 已 `auth save wechat-mp` 登录; 2) 浏览器里能打开「已发表内容」。")


if __name__ == "__main__":
    main()
