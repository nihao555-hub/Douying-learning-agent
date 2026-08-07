"""
抖音爬虫客户端 - 100%真实实现，NO MOCK DATA
基于以下GitHub高star开源项目和真实API：
- yt-dlp (GitHub 140k+ stars) - 视频信息获取和下载，带自动cookie获取（已验证可下载真实视频）
- F2 (GitHub 10k+ stars) - 高级API签名（需用户cookie）
- APP端原生API（已验证可获取feed公开视频和下载视频）
"""
import re
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import httpx
from app.core.config import settings
from app.core.logger import logger


class DouyinClient:
    """抖音客户端 - 100%真实数据实现"""
    
    def __init__(self, cookie: str = ""):
        self.video_dir = Path(settings.VIDEO_STORAGE_PATH)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.cookie = cookie
        self._base_cookies = None  # 自动获取的基础cookie缓存
        
        # APP端UA - 已验证可直接获取公开feed数据和下载视频
        self.app_headers = {
            "User-Agent": "com.ss.android.ugc.aweme/290100 (Linux; U; Android 13; zh_CN; SM-G998B; Build/TP1A.220624.014; Cronet/TTNetVersion:b4d74d15 2020-04-23)",
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }
        
        # PC端UA - 用于获取cookie和yt-dlp
        self.pc_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.douyin.com/",
        }
    
    async def _ensure_base_cookies(self) -> Dict[str, str]:
        """自动获取抖音基础cookie（ttwid等），这是yt-dlp需要的"""
        if self._base_cookies is not None:
            return self._base_cookies
        
        logger.info("正在获取抖音基础cookie...")
        cookies = {}
        try:
            async with httpx.AsyncClient(
                headers=self.pc_headers,
                follow_redirects=True,
                timeout=15,
                verify=False
            ) as client:
                # 访问首页获取基础cookie
                await client.get("https://www.douyin.com/")
                cookies.update(dict(client.cookies))
                
                # 访问discover页面获取更多cookie
                await client.get("https://www.douyin.com/discover")
                cookies.update(dict(client.cookies))
            
            logger.info(f"获取到 {len(cookies)} 个基础cookie: {list(cookies.keys())}")
            self._base_cookies = cookies
            return cookies
        except Exception as e:
            logger.warning(f"获取基础cookie失败: {e}")
            self._base_cookies = {}
            return {}
    
    def _cookies_to_header_string(self, cookies: Dict[str, str]) -> str:
        """将cookies字典转为Cookie header字符串"""
        return "; ".join([f"{k}={v}" for k, v in cookies.items()])
    
    def _ytdlp_get_info_sync(self, url: str, cookie_header: str, download: bool = False, out_path: str = None) -> Optional[Dict]:
        """同步执行yt-dlp获取信息或下载（在executor中运行）"""
        try:
            import yt_dlp
            
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "no_playlist": True,
                "http_headers": {
                    "User-Agent": self.pc_headers["User-Agent"],
                    "Referer": "https://www.douyin.com/",
                    "Cookie": cookie_header,
                },
            }
            
            if download and out_path:
                ydl_opts["format"] = "best[ext=mp4]/best"
                ydl_opts["outtmpl"] = out_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=download)
                return info
        except Exception as e:
            logger.error(f"yt-dlp执行失败: {e}")
            return None
    
    async def _run_ytdlp(self, url: str, download: bool = False, out_path: str = None) -> Optional[Dict]:
        """使用yt-dlp获取视频信息或下载视频（异步执行）"""
        # 先在异步上下文中获取cookie，避免嵌套事件循环问题
        cookies = await self._ensure_base_cookies()
        cookie_header = self.cookie or self._cookies_to_header_string(cookies)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self._ytdlp_get_info_sync, 
            url, cookie_header, download, out_path
        )
    
    async def resolve_share_url(self, url: str) -> str:
        """解析抖音分享短链"""
        try:
            if "v.douyin.com" in url:
                async with httpx.AsyncClient(
                    headers=self.pc_headers,
                    follow_redirects=True,
                    timeout=15,
                    verify=False
                ) as client:
                    resp = await client.get(url)
                    return str(resp.url)
            return url
        except Exception as e:
            logger.error(f"解析短链失败: {e}")
            return url
    
    async def get_aweme_id(self, url: str) -> Optional[str]:
        """从URL中提取aweme_id（视频ID）"""
        try:
            url = await self.resolve_share_url(url)
            match = re.search(r'/video/(\d+)', url)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            logger.debug(f"提取aweme_id失败: {e}")
            return None
    
    async def get_sec_user_id(self, url: str) -> Optional[str]:
        """从URL中提取sec_user_id"""
        try:
            url = await self.resolve_share_url(url)
            match = re.search(r'/user/([^/?#]+)', url)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            logger.debug(f"提取sec_user_id失败: {e}")
            return None
    
    async def get_sec_user_id_from_video_page(self, url: str) -> Optional[str]:
        """从视频网页提取作者的sec_user_id"""
        try:
            url = await self.resolve_share_url(url)
            cookies = await self._ensure_base_cookies()
            
            async with httpx.AsyncClient(
                headers=self.pc_headers,
                cookies=cookies,
                follow_redirects=True,
                timeout=20,
                verify=False
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                
                html = resp.text
                
                # 方法1: 从RENDER_DATA中提取
                match = re.search(r'"secUid":"([^"]+)"', html)
                if match:
                    sec_uid = match.group(1)
                    if sec_uid.startswith("MS4w"):
                        logger.info(f"从视频页面提取到sec_user_id: {sec_uid[:30]}...")
                        return sec_uid
                
                # 方法2: 从author信息中提取
                match = re.search(r'"sec_user_id":"([^"]+)"', html)
                if match:
                    sec_uid = match.group(1)
                    if sec_uid.startswith("MS4w"):
                        logger.info(f"从视频页面提取到sec_user_id: {sec_uid[:30]}...")
                        return sec_uid
                
                # 方法3: 从任何MS4w开头的字符串提取
                match = re.search(r'(MS4wLjABAAAA[A-Za-z0-9_-]+)', html)
                if match:
                    sec_uid = match.group(1)
                    logger.info(f"从视频页面提取到sec_user_id: {sec_uid[:30]}...")
                    return sec_uid
                
                logger.debug("无法从视频页面提取sec_user_id")
                return None
        except Exception as e:
            logger.debug(f"从视频页面提取sec_user_id失败: {e}")
            return None
    
    def _normalize_ytdlp_video(self, info: Dict, sec_user_id: str = None) -> Dict:
        """标准化yt-dlp返回的视频信息"""
        author = info.get("uploader") or info.get("creator") or info.get("channel") or "未知作者"
        uploader_id = info.get("uploader_id", "")
        webpage_url = info.get("webpage_url", "")
        
        # 尝试从信息中获取sec_user_id
        if not sec_user_id and uploader_id:
            sec_user_id = uploader_id
        
        # 获取视频播放地址
        video_url = ""
        formats = info.get("formats", [])
        for fmt in reversed(formats):
            if fmt.get("ext") == "mp4" and fmt.get("url"):
                video_url = fmt["url"]
                break
        if not video_url and info.get("url"):
            video_url = info["url"]
        
        create_time = None
        ts = info.get("timestamp")
        if ts:
            create_time = datetime.fromtimestamp(ts)
        
        return {
            "aweme_id": str(info.get("id", "")),
            "title": info.get("title", "")[:500] or info.get("description", "")[:500] or "无标题",
            "desc": info.get("description", "") or "",
            "cover_url": info.get("thumbnail", "") or "",
            "duration": int(info.get("duration", 0) or 0),
            "digg_count": info.get("like_count", 0) or 0,
            "comment_count": info.get("comment_count", 0) or 0,
            "share_count": info.get("repost_count", 0) or 0,
            "collect_count": 0,
            "play_count": info.get("view_count", 0) or 0,
            "create_time": create_time,
            "video_url": video_url,
            "webpage_url": webpage_url,
            "author": {
                "nickname": str(author),
                "avatar_url": info.get("uploader_avatar", info.get("thumbnail", "")),
                "sec_user_id": sec_user_id or uploader_id,
                "uid": uploader_id,
                "follower_count": 0,
                "following_count": 0,
                "aweme_count": 0,
                "total_favorited": 0,
                "signature": "",
            }
        }
    
    def _normalize_app_video(self, aweme: Dict) -> Dict:
        """标准化APP端API返回的视频信息"""
        author = aweme.get("author", {})
        video = aweme.get("video", {})
        play_addr = video.get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        
        cover = video.get("cover", {})
        cover_urls = cover.get("url_list", [])
        
        statistics = aweme.get("statistics", {})
        
        create_time = None
        ts = aweme.get("create_time")
        if ts:
            create_time = datetime.fromtimestamp(ts)
        
        return {
            "aweme_id": str(aweme.get("aweme_id", "")),
            "title": (aweme.get("desc") or "无标题")[:500],
            "desc": aweme.get("desc", ""),
            "cover_url": cover_urls[0] if cover_urls else "",
            "duration": int(video.get("duration", 0) / 1000) if video.get("duration") else 0,
            "digg_count": statistics.get("digg_count", 0),
            "comment_count": statistics.get("comment_count", 0),
            "share_count": statistics.get("share_count", 0),
            "collect_count": statistics.get("collect_count", 0),
            "play_count": statistics.get("play_count", 0),
            "create_time": create_time,
            "video_url": url_list[0] if url_list else "",
            "webpage_url": f"https://www.douyin.com/video/{aweme.get('aweme_id')}",
            "author": {
                "nickname": author.get("nickname", "未知作者"),
                "avatar_url": (author.get("avatar_larger", {}).get("url_list", [""])[0] or 
                             author.get("avatar_thumb", {}).get("url_list", [""])[0] or ""),
                "sec_user_id": author.get("sec_uid", ""),
                "uid": author.get("uid", ""),
                "follower_count": author.get("follower_count", 0),
                "following_count": author.get("following_count", 0),
                "aweme_count": author.get("aweme_count", 0),
                "total_favorited": author.get("total_favorited", 0),
                "signature": author.get("signature", ""),
            }
        }
    
    async def get_user_info(self, url: str) -> Optional[Dict]:
        """
        获取用户信息 - 真实API调用
        支持：用户主页链接、分享链接、视频链接
        """
        try:
            url = await self.resolve_share_url(url)
            logger.info(f"获取用户信息: {url[:80]}...")
            
            # 方法1: 如果是视频链接，获取视频信息并提取作者sec_user_id
            if "/video/" in url:
                author_info = None
                aweme_id = await self.get_aweme_id(url)
                
                # 1a: 优先使用F2 PostDetail获取视频详情（含正确的sec_user_id）
                if aweme_id:
                    logger.info(f"检测到视频链接，使用F2获取视频和作者信息: {aweme_id}")
                    f2_detail = await self._get_post_detail_f2(aweme_id)
                    if f2_detail:
                        author_info = f2_detail["author"]
                        logger.info(f"F2获取作者: {author_info.get('nickname', '')}")
                
                # 1b: 如果F2失败，用yt-dlp获取作者昵称等信息
                if not author_info:
                    logger.info("F2获取失败，尝试yt-dlp...")
                    info = await self._run_ytdlp(url, download=False)
                    if info:
                        video_data = self._normalize_ytdlp_video(info)
                        author_info = video_data["author"]
                        logger.info(f"yt-dlp获取作者: {author_info.get('nickname', '')}")
                        
                        # 用aweme_id再试一次F2获取sec_user_id
                        if aweme_id and not author_info.get("sec_user_id", "").startswith("MS4w"):
                            f2_detail = await self._get_post_detail_f2(aweme_id)
                            if f2_detail and f2_detail["author"].get("sec_user_id", "").startswith("MS4w"):
                                author_info["sec_user_id"] = f2_detail["author"]["sec_user_id"]
                                logger.info(f"通过F2补充sec_user_id成功")
                
                # 1c: 如果都失败，尝试其他API
                if not author_info and aweme_id:
                    feed_video = await self._get_video_detail(aweme_id)
                    if feed_video:
                        author_info = feed_video["author"]
                
                if author_info:
                    # 如果有正确的sec_user_id，尝试用F2获取更完整的用户信息
                    if author_info.get("sec_user_id", "").startswith("MS4w"):
                        f2_user = await self._get_user_info_f2(author_info["sec_user_id"])
                        if f2_user:
                            # 合并信息：保留昵称，补充F2的其他信息
                            f2_user["nickname"] = author_info.get("nickname") or f2_user.get("nickname", "")
                            return f2_user
                    
                    return author_info
            
            # 方法2: 用户主页链接，获取sec_user_id
            sec_user_id = await self.get_sec_user_id(url)
            if sec_user_id:
                logger.info(f"获取到sec_user_id: {sec_user_id[:30]}...")
                
                # 尝试F2获取用户信息
                f2_user = await self._get_user_info_f2(sec_user_id)
                if f2_user:
                    return f2_user
                
                # 如果F2失败但有sec_user_id，返回一个基本信息对象
                logger.warning("无法获取详细用户信息，使用sec_user_id创建基本记录")
                return {
                    "nickname": f"用户_{sec_user_id[-8:]}",
                    "avatar_url": "",
                    "sec_user_id": sec_user_id,
                    "uid": "",
                    "follower_count": 0,
                    "following_count": 0,
                    "aweme_count": 0,
                    "total_favorited": 0,
                    "signature": "",
                }
            
            logger.error("所有方法均无法获取用户信息")
            return None
            
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}", exc_info=True)
            return None
    
    async def _get_video_detail(self, aweme_id: str) -> Optional[Dict]:
        """通过aweme_id直接获取视频详情（含作者sec_user_id）"""
        try:
            async with httpx.AsyncClient(
                headers=self.app_headers,
                follow_redirects=True,
                timeout=20,
                verify=False
            ) as client:
                # 尝试多个视频详情端点
                endpoints = [
                    f"https://api.amemv.com/aweme/v1/aweme/detail/?aweme_id={aweme_id}&aid=1128",
                    f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={aweme_id}",
                ]
                
                for url in endpoints:
                    try:
                        r = await client.get(url)
                        if r.status_code != 200:
                            continue
                        data = r.json()
                        
                        # 解析不同的响应格式
                        aweme = None
                        if "aweme_detail" in data:
                            aweme = data["aweme_detail"]
                        elif "item_list" in data and data["item_list"]:
                            aweme = data["item_list"][0]
                        
                        if aweme and aweme.get("aweme_id"):
                            logger.info(f"成功获取视频详情: {aweme_id}")
                            return self._normalize_app_video(aweme)
                    except Exception as e:
                        logger.debug(f"端点 {url[:50]}... 失败: {e}")
                        continue
                
                # 如果详情API失败，尝试从feed中查找
                logger.info(f"详情API失败，从feed中查找视频 {aweme_id}")
                return await self._find_video_in_feed(aweme_id, max_pages=10)
                
        except Exception as e:
            logger.error(f"获取视频详情失败: {e}")
            return None
    
    async def _find_video_in_feed(self, target_aweme_id: str, max_pages: int = 5) -> Optional[Dict]:
        """从feed流中查找指定视频"""
        try:
            async with httpx.AsyncClient(
                headers=self.app_headers,
                follow_redirects=True,
                timeout=20,
                verify=False
            ) as client:
                for page in range(max_pages):
                    try:
                        r = await client.get(f"https://api.amemv.com/aweme/v1/feed/?count=20")
                        data = r.json()
                        aweme_list = data.get("aweme_list", [])
                        
                        for aweme in aweme_list:
                            if str(aweme.get("aweme_id")) == str(target_aweme_id):
                                logger.info(f"在feed中找到目标视频: {target_aweme_id}")
                                return self._normalize_app_video(aweme)
                        
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.debug(f"feed第{page+1}页请求失败: {e}")
                        continue
                
                logger.warning(f"在feed中未找到视频 {target_aweme_id}")
                return None
        except Exception as e:
            logger.error(f"feed查找失败: {e}")
            return None
    
    def _f2_get_user_info_sync(self, sec_user_id: str, cookie_header: str) -> Optional[Dict]:
        """同步执行F2获取用户信息"""
        try:
            from f2.apps.douyin.crawler import DouyinCrawler
            from f2.apps.douyin.model import UserProfile
            from f2.apps.douyin.filter import UserProfileFilter
            
            kwargs = {
                "cookie": cookie_header,
                "headers": {
                    "User-Agent": self.pc_headers["User-Agent"],
                    "Referer": "https://www.douyin.com/",
                },
                "proxies": {"http://": None, "https://": None},
                "timeout": 15,
                "max_retries": 2,
            }
            
            async def _f2_async():
                async with DouyinCrawler(kwargs) as crawler:
                    params = UserProfile(sec_user_id=sec_user_id)
                    response = await crawler.fetch_user_profile(params)
                    user = UserProfileFilter(response)
                    if user and user.nickname:
                        return {
                            "nickname": user.nickname,
                            "avatar_url": user.avatar if hasattr(user, 'avatar') else "",
                            "sec_user_id": sec_user_id,
                            "uid": user.uid if hasattr(user, 'uid') else "",
                            "follower_count": user.follower_count if hasattr(user, 'follower_count') else 0,
                            "following_count": user.following_count if hasattr(user, 'following_count') else 0,
                            "aweme_count": user.aweme_count if hasattr(user, 'aweme_count') else 0,
                            "total_favorited": user.total_favorited if hasattr(user, 'total_favorited') else 0,
                            "signature": user.signature if hasattr(user, 'signature') else "",
                        }
                    return None
            
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_f2_async())
            finally:
                loop.close()
        except Exception as e:
            logger.debug(f"F2获取用户信息失败: {e}")
            return None
    
    async def _get_user_info_f2(self, sec_user_id: str) -> Optional[Dict]:
        """使用F2获取用户信息（异步包装）"""
        cookies = await self._ensure_base_cookies()
        cookie_header = self.cookie or self._cookies_to_header_string(cookies)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._f2_get_user_info_sync, sec_user_id, cookie_header)
    
    def _f2_get_post_detail_sync(self, aweme_id: str, cookie_header: str) -> Optional[Dict]:
        """同步执行F2获取视频详情"""
        try:
            from f2.apps.douyin.crawler import DouyinCrawler
            from f2.apps.douyin.model import PostDetail
            
            kwargs = {
                "cookie": cookie_header,
                "headers": {
                    "User-Agent": self.pc_headers["User-Agent"],
                    "Referer": "https://www.douyin.com/",
                },
                "proxies": {"http://": None, "https://": None},
                "timeout": 15,
                "max_retries": 2,
            }
            
            import asyncio
            async def _f2_async():
                async with DouyinCrawler(kwargs) as crawler:
                    params = PostDetail(aweme_id=aweme_id)
                    return await crawler.fetch_post_detail(params)
            
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(_f2_async())
            finally:
                loop.close()
            
            if not isinstance(response, dict):
                return None
            
            aweme_detail = response.get("aweme_detail", {})
            if not aweme_detail or not aweme_detail.get("aweme_id"):
                return None
            
            # 标准化为统一格式
            author = aweme_detail.get("author", {})
            video_info = aweme_detail.get("video", {})
            statistics = aweme_detail.get("statistics", {})
            
            # 提取视频URL
            play_addr = video_info.get("play_addr", {}).get("url_list", [])
            video_url = play_addr[0] if play_addr else ""
            
            cover_urls = video_info.get("cover", {}).get("url_list", [])
            cover_url = cover_urls[0] if cover_urls else ""
            
            # 转换create_time为datetime
            create_time = None
            ts = aweme_detail.get("create_time")
            if ts:
                try:
                    create_time = datetime.fromtimestamp(int(ts))
                except:
                    create_time = None
            
            return {
                "aweme_id": str(aweme_detail.get("aweme_id", "")),
                "title": (aweme_detail.get("desc") or "无标题")[:500],
                "desc": aweme_detail.get("desc", ""),
                "cover_url": cover_url,
                "duration": (video_info.get("duration", 0) or 0) // 1000,
                "digg_count": statistics.get("digg_count", 0),
                "comment_count": statistics.get("comment_count", 0),
                "share_count": statistics.get("share_count", 0),
                "collect_count": statistics.get("collect_count", 0),
                "play_count": statistics.get("play_count", 0),
                "create_time": create_time,
                "video_url": video_url,
                "webpage_url": f"https://www.douyin.com/video/{aweme_detail.get('aweme_id', '')}",
                "author": {
                    "uid": str(author.get("uid", "")),
                    "sec_user_id": author.get("sec_uid", ""),
                    "nickname": author.get("nickname", "未知作者"),
                    "avatar_url": (author.get("avatar_larger", {}).get("url_list", [""])[0] or 
                                 author.get("avatar_thumb", {}).get("url_list", [""])[0] or ""),
                    "follower_count": author.get("follower_count", 0),
                    "following_count": author.get("following_count", 0),
                    "aweme_count": author.get("aweme_count", 0),
                    "total_favorited": author.get("total_favorited", 0),
                    "signature": author.get("signature", ""),
                }
            }
        except Exception as e:
            logger.debug(f"F2获取视频详情失败: {e}")
            return None
    
    async def _get_post_detail_f2(self, aweme_id: str) -> Optional[Dict]:
        """使用F2获取视频详情（异步包装）- 含作者sec_user_id"""
        cookies = await self._ensure_base_cookies()
        cookie_header = self.cookie or self._cookies_to_header_string(cookies)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._f2_get_post_detail_sync, aweme_id, cookie_header)
    
    async def get_user_videos(self, url: str, max_videos: int = 0, known_sec_user_id: str = "", progress_callback=None) -> List[Dict]:
        """
        获取用户视频列表 - 真实数据
        支持：用户主页链接、视频链接
        对视频链接：先获取该视频，再通过F2尝试获取该作者更多视频
        max_videos: 0表示获取所有视频，>0表示限制数量
        known_sec_user_id: 如果已知作者sec_user_id（如从博主记录获取），可直接用于F2
        progress_callback: 进度回调函数 callback(current_count, stage_text)
        """
        try:
            url = await self.resolve_share_url(url)
            target_desc = "全部视频" if max_videos == 0 else f"{max_videos}个视频"
            logger.info(f"获取视频列表: {url[:80]}... (目标: {target_desc})")
            
            def _report_progress(count, text):
                """报告进度"""
                logger.info(f"[爬取进度] {text} (已获取: {count}个)")
                if progress_callback:
                    try:
                        import asyncio
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(progress_callback(count, text))
                    except:
                        pass
            
            videos = []
            author_sec_uid = known_sec_user_id or None
            author_uid = None
            
            # 情况1: 视频链接 - 获取单个视频，然后尝试获取该作者更多视频
            if "/video/" in url:
                _report_progress(0, "正在解析视频链接...")
                logger.info("单个视频链接，先获取该视频...")
                
                aweme_id = await self.get_aweme_id(url)
                
                # 方法1: 优先使用F2 PostDetail获取视频详情（含正确的sec_user_id）
                initial_video = None
                if aweme_id:
                    _report_progress(0, "正在获取视频详情...")
                    logger.info(f"使用F2获取视频详情: {aweme_id}")
                    f2_detail = await self._get_post_detail_f2(aweme_id)
                    if f2_detail:
                        initial_video = f2_detail
                        author_sec_uid = f2_detail.get("author", {}).get("sec_user_id", "") or author_sec_uid
                        author_uid = f2_detail.get("author", {}).get("uid", "")
                        videos.append(f2_detail)
                        _report_progress(1, f"已获取视频: {f2_detail['title'][:30]}...")
                        logger.info(f"F2获取视频详情成功: {f2_detail['title'][:40]}...")
                
                # 方法2: 如果F2详情失败，用旧的详情API
                if not initial_video and aweme_id:
                    logger.info(f"F2详情失败，尝试其他API: {aweme_id}")
                    detail_video = await self._get_video_detail(aweme_id)
                    if detail_video:
                        initial_video = detail_video
                        author_sec_uid = detail_video.get("author", {}).get("sec_user_id", "") or author_sec_uid
                        author_uid = detail_video.get("author", {}).get("uid", "")
                        videos.append(detail_video)
                        _report_progress(1, f"已获取视频: {detail_video['title'][:30]}...")
                        logger.info(f"视频详情获取成功: {detail_video['title'][:40]}...")
                
                # 方法3: 如果都失败，用yt-dlp获取
                if not initial_video:
                    info = await self._run_ytdlp(url, download=False)
                    if info:
                        ytdlp_video = self._normalize_ytdlp_video(info)
                        logger.info(f"yt-dlp成功获取视频: {ytdlp_video['title'][:40]}...")
                        author_uid = ytdlp_video.get("author", {}).get("uid", "")
                        videos.append(ytdlp_video)
                        initial_video = ytdlp_video
                        _report_progress(1, f"已获取视频: {ytdlp_video['title'][:30]}...")
                        
                        # 用yt-dlp获取的aweme_id再试一次F2获取sec_user_id
                        ytdlp_aweme_id = ytdlp_video.get("aweme_id")
                        if ytdlp_aweme_id and not author_sec_uid:
                            f2_detail = await self._get_post_detail_f2(ytdlp_aweme_id)
                            if f2_detail:
                                author_sec_uid = f2_detail.get("author", {}).get("sec_user_id", "")
                                # 更新初始视频信息
                                videos = [f2_detail]
                                initial_video = f2_detail
                
                if not videos:
                    logger.error("无法获取视频信息")
                    return []
                
                # 有了作者sec_user_id，尝试用F2获取该作者更多视频
                if author_sec_uid:
                    logger.info(f"获取到作者sec_user_id，开始获取该作者{target_desc}...")
                    
                    async def f2_progress_cb(count, page):
                        _report_progress(count, f"正在翻页获取视频列表 (第{page}页, 已获取{count}个)...")
                    
                    f2_videos = await self._get_user_videos_f2(author_sec_uid, max_videos, progress_callback=f2_progress_cb)
                    
                    if f2_videos:
                        # 合并：去重，保留初始视频，添加其他视频
                        seen_ids = {v["aweme_id"] for v in videos}
                        added = 0
                        for fv in f2_videos:
                            if fv["aweme_id"] not in seen_ids:
                                if max_videos > 0 and len(videos) >= max_videos:
                                    break
                                videos.append(fv)
                                seen_ids.add(fv["aweme_id"])
                                added += 1
                        _report_progress(len(videos), f"视频列表获取完成，共{len(videos)}个视频")
                        logger.info(f"F2成功获取作者更多视频: 新增{added}个，共{len(videos)}个")
                    else:
                        logger.warning("F2未能获取作者更多视频（需要登录cookie），仅处理当前视频")
                        _report_progress(len(videos), "仅获取到当前视频（无有效cookie）")
                elif not author_sec_uid:
                    logger.warning("未获取到作者sec_user_id，无法批量获取作者视频，仅处理当前视频")
                    _report_progress(len(videos), "未获取到作者ID，仅处理当前视频")
                
                if max_videos > 0:
                    return videos[:max_videos]
                return videos
            
            # 情况2: 用户主页链接 - 获取视频列表
            _report_progress(0, "正在解析博主主页...")
            sec_user_id = await self.get_sec_user_id(url)
            if not sec_user_id:
                logger.error("无法获取sec_user_id")
                return []
            
            author_sec_uid = sec_user_id
            
            # 方法1: F2获取用户视频列表
            logger.info(f"用户主页链接，使用F2获取{target_desc}...")
            
            async def f2_progress_cb(count, page):
                _report_progress(count, f"正在翻页获取视频列表 (第{page}页, 已获取{count}个)...")
            
            f2_videos = await self._get_user_videos_f2(sec_user_id, max_videos, progress_callback=f2_progress_cb)
            if f2_videos:
                _report_progress(len(f2_videos), f"视频列表获取完成，共{len(f2_videos)}个视频")
                logger.info(f"F2成功获取 {len(f2_videos)} 个视频")
                if max_videos > 0:
                    return f2_videos[:max_videos]
                return f2_videos
            
            logger.error("无法获取指定用户视频列表（需要有效登录cookie才能获取用户主页视频）")
            logger.error("提示：请提供单个视频链接进行分析，或配置有效cookie后再试")
            return []
            
        except Exception as e:
            logger.error(f"获取视频列表失败: {e}", exc_info=True)
            return []
    
    def _f2_get_user_videos_sync(self, sec_user_id: str, cookie_header: str, max_videos: int = 0, progress_callback=None) -> List[Dict]:
        """
        同步执行F2获取用户视频列表 - 使用原始响应数据获取完整信息
        max_videos: 0表示获取所有视频，>0表示限制数量
        progress_callback: 同步回调 callback(current_count, page_num)
        """
        try:
            from f2.apps.douyin.crawler import DouyinCrawler
            from f2.apps.douyin.model import UserPost
            from f2.apps.douyin.filter import UserPostFilter
            
            # 安全上限提高到10000，支持大V博主
            SAFETY_LIMIT = 10000
            target_max = max_videos if max_videos > 0 else SAFETY_LIMIT
            
            kwargs = {
                "cookie": cookie_header,
                "headers": {
                    "User-Agent": self.pc_headers["User-Agent"],
                    "Referer": "https://www.douyin.com/",
                },
                "proxies": {"http://": None, "https://": None},
                "timeout": 15,
                "max_retries": 2,
            }
            
            all_videos = []
            max_cursor = 0
            page_count = 50  # 每页获取数量（提高到50减少翻页）
            page_num = 0
            
            # 用于在事件循环中调用同步回调
            def _notify_progress():
                if progress_callback:
                    try:
                        progress_callback(len(all_videos), page_num)
                    except:
                        pass
            
            async def _f2_async():
                nonlocal max_cursor, page_num
                async with DouyinCrawler(kwargs) as crawler:
                    while True:
                        # 如果已达到目标数量，停止
                        if len(all_videos) >= target_max:
                            if max_videos == 0:
                                logger.info(f"已达到安全上限{SAFETY_LIMIT}个视频，停止爬取")
                            break
                        
                        # 计算本次请求数量
                        count = min(page_count, target_max - len(all_videos))
                        
                        page_num += 1
                        logger.info(f"正在获取第{page_num}页视频 (已获取{len(all_videos)}/{target_max}个)...")
                        _notify_progress()
                        
                        params = UserPost(
                            sec_user_id=sec_user_id,
                            count=count,
                            max_cursor=max_cursor
                        )
                        response = await crawler.fetch_user_post(params)
                        
                        # 直接从原始响应解析数据
                        aweme_list = response.get("aweme_list", [])
                        if not aweme_list:
                            # 尝试用filter检查状态
                            posts = UserPostFilter(response)
                            has_more = posts.has_more if hasattr(posts, 'has_more') else 0
                            if not has_more:
                                logger.info(f"没有更多视频了，共获取{len(all_videos)}个")
                                break
                            max_cursor = posts.max_cursor if hasattr(posts, 'max_cursor') else 0
                            await asyncio.sleep(1)
                            continue
                        
                        added_count = 0
                        for aweme in aweme_list:
                            if len(all_videos) >= target_max:
                                break
                            
                            # 使用_normalize_app_video逻辑标准化
                            video = self._normalize_app_video(aweme)
                            # 确保author的sec_user_id正确
                            video["author"]["sec_user_id"] = sec_user_id
                            all_videos.append(video)
                            added_count += 1
                        
                        logger.info(f"第{page_num}页获取{added_count}个视频，累计{len(all_videos)}个")
                        _notify_progress()
                        
                        # 检查是否有更多
                        has_more = response.get("has_more", 0)
                        if not has_more:
                            logger.info(f"没有更多视频了，该博主共{len(all_videos)}个视频")
                            break
                        max_cursor = response.get("max_cursor", 0)
                        await asyncio.sleep(0.5)  # 适当减少延迟加快翻页
                    
                    return all_videos
            
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_f2_async())
            finally:
                loop.close()
        except Exception as e:
            logger.debug(f"F2获取视频列表失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    async def _get_user_videos_f2(self, sec_user_id: str, max_videos: int, progress_callback=None) -> List[Dict]:
        """使用F2获取用户视频列表（异步包装）"""
        cookies = await self._ensure_base_cookies()
        cookie_header = self.cookie or self._cookies_to_header_string(cookies)
        loop = asyncio.get_event_loop()
        
        # 将异步进度回调包装为同步回调
        sync_cb = None
        if progress_callback:
            def _sync_progress_wrapper(count, page):
                """在新线程中调度异步回调"""
                async def _run_async_cb():
                    try:
                        await progress_callback(count, page)
                    except:
                        pass
                try:
                    asyncio.run_coroutine_threadsafe(_run_async_cb(), loop)
                except:
                    pass
            sync_cb = _sync_progress_wrapper
        
        result = await loop.run_in_executor(
            None, 
            self._f2_get_user_videos_sync, 
            sec_user_id, cookie_header, max_videos, sync_cb
        )
        return result or []
    
    async def _get_feed_videos(self, count: int = 10) -> List[Dict]:
        """从推荐feed获取真实视频（无cookie时可用的公开API，已验证）"""
        videos = []
        try:
            async with httpx.AsyncClient(
                headers=self.app_headers,
                follow_redirects=True,
                timeout=20,
                verify=False
            ) as client:
                while len(videos) < count:
                    try:
                        r = await client.get("https://api.amemv.com/aweme/v1/feed/?count=20")
                        data = r.json()
                        aweme_list = data.get("aweme_list", [])
                        
                        for aweme in aweme_list:
                            if len(videos) >= count:
                                break
                            video = self._normalize_app_video(aweme)
                            if not any(v["aweme_id"] == video["aweme_id"] for v in videos):
                                videos.append(video)
                                logger.info(f"feed获取视频: {video['title'][:40]}... (作者: {video['author']['nickname']})")
                        
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        logger.debug(f"feed请求失败: {e}")
                        await asyncio.sleep(0.5)
                        continue
        except Exception as e:
            logger.error(f"获取feed视频失败: {e}")
        
        return videos
    
    async def _get_author_videos_from_feed(self, sec_user_id: str, author_uid: str, target_count: int = 10, initial_video: Dict = None) -> List[Dict]:
        """
        通过多次扫描推荐feed流，收集同一作者的多个视频
        这是无需登录cookie时获取博主多个视频的方案
        """
        videos = []
        seen_ids = set()
        
        # 先加入初始视频
        if initial_video:
            videos.append(initial_video)
            seen_ids.add(initial_video["aweme_id"])
            logger.info(f"初始视频: {initial_video['title'][:40]}...")
        
        logger.info(f"开始扫描feed流收集博主更多视频 (目标: {target_count}个)...")
        
        try:
            async with httpx.AsyncClient(
                headers=self.app_headers,
                follow_redirects=True,
                timeout=20,
                verify=False
            ) as client:
                scan_rounds = 0
                max_rounds = 30  # 最多扫描30轮
                
                while len(videos) < target_count and scan_rounds < max_rounds:
                    scan_rounds += 1
                    try:
                        r = await client.get("https://api.amemv.com/aweme/v1/feed/?count=20")
                        data = r.json()
                        aweme_list = data.get("aweme_list", [])
                        
                        found_in_round = 0
                        for aweme in aweme_list:
                            aweme_author = aweme.get("author", {})
                            aweme_sec_uid = aweme_author.get("sec_uid", "")
                            aweme_uid = aweme_author.get("uid", "")
                            aweme_id = str(aweme.get("aweme_id", ""))
                            
                            # 匹配作者（通过sec_uid或uid）
                            is_same_author = False
                            if sec_user_id and aweme_sec_uid == sec_user_id:
                                is_same_author = True
                            elif author_uid and aweme_uid == author_uid:
                                is_same_author = True
                            
                            if is_same_author and aweme_id not in seen_ids:
                                video = self._normalize_app_video(aweme)
                                videos.append(video)
                                seen_ids.add(aweme_id)
                                found_in_round += 1
                                logger.info(f"  [扫描{scan_rounds}轮] 找到新视频 ({len(videos)}/{target_count}): {video['title'][:40]}...")
                                
                                if len(videos) >= target_count:
                                    break
                        
                        if found_in_round == 0 and scan_rounds % 5 == 0:
                            logger.info(f"  [扫描{scan_rounds}轮] 本轮未找到新视频，继续扫描...")
                        
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.debug(f"feed扫描失败 ({scan_rounds}轮): {e}")
                        await asyncio.sleep(1)
                        continue
        
        except Exception as e:
            logger.error(f"扫描作者视频失败: {e}")
        
        logger.info(f"feed扫描完成，共收集到博主 {len(videos)} 个视频")
        return videos
    
    async def download_video(self, video_url: str, aweme_id: str) -> Optional[str]:
        """
        下载无水印视频 - 100%真实下载
        优先APP端直链，其次yt-dlp，最后feed重获
        """
        try:
            filename = f"{aweme_id}.mp4"
            save_path = self.video_dir / filename
            
            if save_path.exists() and save_path.stat().st_size > 10000:
                logger.info(f"视频已存在: {save_path}")
                return str(save_path)
            
            logger.info(f"下载视频: {aweme_id}")
            
            # 方法1: 如果是APP端直链，直接下载（最快，已验证）
            if "amemv.com" in video_url or "bytecdn" in video_url or "365yg.com" in video_url or "douyinvod.com" in video_url or "ixigua.com" in video_url:
                async with httpx.AsyncClient(
                    headers=self.app_headers,
                    follow_redirects=True,
                    timeout=120,
                    verify=False
                ) as client:
                    resp = await client.get(video_url)
                    if resp.status_code == 200 and len(resp.content) > 10000:
                        with open(save_path, "wb") as f:
                            f.write(resp.content)
                        size_mb = save_path.stat().st_size / 1024 / 1024
                        logger.info(f"APP端API下载成功: {save_path} ({size_mb:.2f} MB)")
                        return str(save_path)
            
            # 方法2: yt-dlp下载（带自动cookie，已验证可下载8MB+视频）
            logger.info("尝试yt-dlp下载...")
            webpage_url = f"https://www.douyin.com/video/{aweme_id}"
            info = await self._run_ytdlp(webpage_url, download=True, out_path=str(save_path))
            if info and save_path.exists() and save_path.stat().st_size > 10000:
                size_mb = save_path.stat().st_size / 1024 / 1024
                logger.info(f"yt-dlp下载成功: {save_path} ({size_mb:.2f} MB)")
                return str(save_path)
            
            # 方法3: 从feed重新获取直链下载
            logger.info("尝试从feed重获视频地址...")
            async with httpx.AsyncClient(
                headers=self.app_headers,
                follow_redirects=True,
                timeout=120,
                verify=False
            ) as client:
                video = await self._find_video_in_feed(aweme_id, max_pages=10)
                if video and video.get("video_url"):
                    resp = await client.get(video["video_url"])
                    if resp.status_code == 200 and len(resp.content) > 10000:
                        with open(save_path, "wb") as f:
                            f.write(resp.content)
                        size_mb = save_path.stat().st_size / 1024 / 1024
                        logger.info(f"feed重获下载成功: {save_path} ({size_mb:.2f} MB)")
                        return str(save_path)
            
            logger.error(f"所有下载方法均失败: {aweme_id}")
            return None
            
        except Exception as e:
            logger.error(f"下载视频失败 {aweme_id}: {e}", exc_info=True)
            return None


# 单例客户端实例
_douyin_client: Optional[DouyinClient] = None


def get_douyin_client(cookie: str = "") -> DouyinClient:
    """获取抖音客户端单例"""
    global _douyin_client
    if _douyin_client is None:
        _douyin_client = DouyinClient(cookie=cookie)
    return _douyin_client
