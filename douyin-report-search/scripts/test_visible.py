#!/usr/bin/env python3
"""快速测试 - 打开浏览器看是否可见"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            executable_path=r"C:\Users\53185\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe",
            args=["--start-maximized","--disable-blink-features=AutomationControlled","--no-sandbox"],
        )
        page = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await page.new_page()
        await page.goto("https://www.douyin.com/search/尼日利亚?type=general", wait_until="commit", timeout=30000)
        print("浏览器已打开！请查看窗口。60秒后自动关闭...")
        await asyncio.sleep(60)
        await browser.close()
        print("测试完成")

asyncio.run(main())
