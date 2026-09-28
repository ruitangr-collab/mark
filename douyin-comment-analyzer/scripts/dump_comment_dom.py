#!/usr/bin/env python3
"""诊断脚本：dump 一个真实抖音视频页的评论区 DOM 结构。

用途：common.py 的 DOM 通道需要精确的评论区容器选择器，否则会回落整页 body
把右侧推荐流当评论抓进来（污染第 8 次复现的根因）。本脚本打开一个视频页，
打印所有疑似评论区容器的 tag/class/data-e2e，供人工挑选选择器。

用法：
    python3 dump_comment_dom.py <video_url> [--out /tmp/dom_dump.html]
"""
import sys, time, re, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from DrissionPage import ChromiumPage, ChromiumOptions

PROFILE_DIR = Path(os.path.expanduser('~/.workbuddy/douyin_chrome_profile'))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    url = args[0] if args else None
    if not url:
        print('用法: python3 dump_comment_dom.py <video_url>')
        sys.exit(1)
    vid = re.search(r'/video/(\d{10,})', url)
    vid = vid.group(1) if vid else 'unknown'

    co = ChromiumOptions()
    for a in ['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage',
              '--no-sandbox', '--disable-gpu', '--window-size=1920,1080', '--start-minimized']:
        co.set_argument(a)
    co.set_argument(f'--user-data-dir={PROFILE_DIR}')
    co.headless(False)
    page = ChromiumPage(co)
    page.get(url)
    time.sleep(6)
    page.scroll.down(800)
    time.sleep(3)
    print(f'[url] {page.url}')

    html = page.html
    out = f'/tmp/douyin_dom_{vid}.html'
    open(out, 'w', encoding='utf-8').write(html)
    print(f'[html] 已保存整页 -> {out}  ({len(html)} bytes)')

    # 1) 所有 data-e2e 属性
    e2e = sorted(set(re.findall(r'data-e2e="([^"]+)"', html)))
    print(f'\n=== data-e2e 属性（共 {len(e2e)}）===')
    for e in e2e:
        if any(k in e.lower() for k in ('comment', 'reply', 'discuss')):
            print(f'  ★ {e}')
    print('  （其余略，完整 html 见上方文件）')

    # 2) 所有含 comment 关键字的 class
    classes = sorted(set(re.findall(r'class="([^"]*[Cc]omment[^"]*)"', html)))
    print(f'\n=== 含 comment 的 class（共 {len(classes)}）===')
    for c in classes[:60]:
        print(f'  {c}')

    # 3) 运行时实测：哪些选择器能拿到文本
    print('\n=== 选择器实测 ===')
    sels = [
        '[data-e2e="comment-list"]', 'div[class*="comment-list"]',
        'div[class*="commentList"]', 'div[class*="CommentList"]',
        'ul[class*="comment"]', '[data-e2e="comment-item"]',
        'div[class*="CommentContainer"]', 'div[class*="comment-container"]',
    ]
    for s in sels:
        try:
            nodes = page(s)
            n = len(nodes) if nodes else 0
            txt = ''
            if n:
                txt = nodes[0].text.replace('\n', ' ⏎ ')[:80]
            print(f'  {s:<45} hits={n}  {txt}')
        except Exception as e:
            print(f'  {s:<45} ERR {type(e).__name__}')

    # 4) 从整页 class 里挖真实容器（运行时再验一轮）
    print('\n=== 从页面 class 反推出的 comment 容器（运行时验证）===')
    cand = set()
    for c in classes:
        for token in c.split():
            if 'omment' in token:
                cand.add(token)
    for token in sorted(cand)[:40]:
        sel = f'div[class*="{token}"]'
        try:
            nodes = page(sel)
            n = len(nodes) if nodes else 0
            if n:
                lines = [l.strip() for l in nodes[0].text.split('\n') if l.strip()]
                print(f'  {token:<45} hits={n} lines={len(lines)}  首行: {lines[0][:50] if lines else ""}')
        except Exception:
            pass


if __name__ == '__main__':
    main()
