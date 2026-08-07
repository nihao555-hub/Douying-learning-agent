#!/usr/bin/env python3
"""测试抖音爬虫 - 获取cookie和视频数据"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
import re
import json
import urllib3
urllib3.disable_warnings()

async def test():
    # PC端UA，更容易拿到完整cookie
    pc_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    async with httpx.AsyncClient(
        headers=pc_headers,
        follow_redirects=True,
        timeout=30,
        verify=False
    ) as client:
        # 第一步：访问抖音首页，获取ttwid
        print("=" * 50)
        print("步骤1: 访问抖音首页获取cookie")
        try:
            r = await client.get("https://www.douyin.com/")
            print(f"状态码: {r.status_code}")
            cookies = dict(client.cookies)
            print(f"Cookies: {list(cookies.keys())}")
            for k, v in cookies.items():
                print(f"  {k} = {v[:50]}...")
        except Exception as e:
            print(f"失败: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # 第二步：尝试从页面中提取RENDER_DATA
        print("\n" + "=" * 50)
        print("步骤2: 从首页提取初始数据")
        render_match = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', r.text)
        if render_match:
            from urllib.parse import unquote
            render_data = json.loads(unquote(render_match.group(1)))
            print(f"RENDER_DATA keys: {list(render_data.keys())[:10]}")
        else:
            print("未找到 RENDER_DATA")
        
        # 第三步：用获取的cookie尝试获取一个视频页面
        # 从热榜找一个视频
        print("\n" + "=" * 50)
        print("步骤3: 获取热榜视频")
        try:
            r = await client.get("https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/")
            data = r.json()
            if data.get("word_list"):
                # 拿第一个热词去搜索视频
                hot_word = data["word_list"][0]["word"]
                print(f"热词: {hot_word}")
                
                # 用搜索API找视频
                search_url = f"https://www.douyin.com/aweme/v1/web/general/search/single/?keyword={hot_word}&count=5&search_source=normal_search&type=1"
                r2 = await client.get(search_url)
                print(f"搜索API状态: {r2.status_code}")
                if r2.status_code == 200:
                    sdata = r2.json()
                    if sdata.get("data"):
                        for item in sdata["data"][:3]:
                            aweme = item.get("aweme_info", {})
                            if aweme:
                                aid = aweme.get("aweme_id", "")
                                desc = aweme.get("desc", "")[:50]
                                author = aweme.get("author", {}).get("nickname", "")
                                print(f"  视频: {aid} - {desc}... (作者: {author})")
        except Exception as e:
            print(f"搜索失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
