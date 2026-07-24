#!/usr/bin/env python3
"""
从抖音直播间页面获取直播流地址（FLV/m3u8）
"""
import asyncio
import re
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def get_stream_url(room_id: str) -> dict:
    """
    获取抖音直播间流地址。
    返回: {"flv": [...], "hls": [...]} 
    """
    # 方法1：从直播间页面解析
    url = f"https://live.douyin.com/{room_id}"
    
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://live.douyin.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(url, headers=headers)
        html = resp.text
    
    # 尝试从 HTML 中提取 stream 信息
    # 抖音会把流信息放在 window.__INITIAL_STATE__ 或类似全局变量里
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
        r'"roomInfo":\s*({.*?})',
        r'"streamUrl":\s*({.*?})',
        r'"liveCoreSDK":\s*({.*?})',
    ]
    
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                print(f"Found data with pattern: {pat[:30]}")
                print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
                return data
            except:
                pass
    
    # 方法2：直接使用抖音的 API（需要知道 cookie）
    # 这是更可靠的方法
    print("[Info] HTML 解析未找到流地址，尝试 API 方式...")
    
    # 抖音直播流 API（需要 ttwid cookie）
    # 实际项目中需要从 WebSocket 握手或页面中获取
    print(f"[Info] HTML 长度: {len(html)}")
    print(f"[Info] 页面标题: {html[html.find('<title'):html.find('</title>')+8] if '<title' in html else 'N/A'}")
    
    # 输出部分 HTML 用于调试
    # 查找包含 "flv" 或 "m3u8" 的部分
    flv_match = re.search(r'https?://[^"\'\\s]+\\.flv', html)
    hls_match = re.search(r'https?://[^"\'\\s]+\\.m3u8', html)
    
    if flv_match:
        print(f"[Found] FLV: {flv_match.group(0)}")
    if hls_match:
        print(f"[Found] HLS: {hls_match.group(0)}")
    
    if not flv_match and not hls_match:
        print("[Info] 页面中未找到直接的流地址（抖音已加密，需要通过 API 获取）")
        print("[Info] 需要在采集器里通过 WebSocket 获取流地址，或使用抖音开放 API")
    
    return {}


if __name__ == "__main__":
    room_id = sys.argv[1] if len(sys.argv) > 1 else "7659205935478393651"
    asyncio.run(get_stream_url(room_id))
