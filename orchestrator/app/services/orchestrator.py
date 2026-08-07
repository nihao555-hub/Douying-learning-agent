"""
核心编排服务
完整流程：添加博主 → 爬取视频列表 → 下载视频 → 提取音频 → 语音转文字 → AI解析总结 → 生成综合大文档
"""
import os
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import async_session
from app.core.logger import logger
from app.core.config import settings
from app.models.models import Blogger, Video
from app.services.douyin_client import get_douyin_client
from app.services.asr_service import get_asr_service
from app.services.gemini_client import get_gemini_client
from app.services.knowledge_base import get_knowledge_base


class Orchestrator:
    """编排器"""
    
    def __init__(self):
        self.douyin = get_douyin_client()
        self.asr = get_asr_service()
        self.gemini = get_gemini_client()
        self.kb = get_knowledge_base()
        
        self.audio_dir = Path(settings.AUDIO_STORAGE_PATH)
        self.transcript_dir = Path(settings.TRANSCRIPT_STORAGE_PATH)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
    
    async def add_blogger(self, db: AsyncSession, url: str) -> Optional[Blogger]:
        """添加博主并开始处理"""
        try:
            # 保存原始URL
            self._original_url = url
            
            # 获取用户信息
            user_info = await self.douyin.get_user_info(url)
            if not user_info:
                logger.error(f"无法获取博主信息: {url}")
                return None
            
            # 检查是否已存在（如果是单个视频，用视频ID作为标识）
            sec_uid = user_info.get("sec_user_id", "")
            if sec_uid:
                result = await db.execute(
                    select(Blogger).where(Blogger.sec_user_id == sec_uid)
                )
            else:
                result = await db.execute(
                    select(Blogger).where(Blogger.nickname == user_info.get("nickname", ""))
                )
            existing = result.scalar_one_or_none()
            if existing:
                logger.info(f"博主已存在: {existing.nickname}")
                return existing
            
            # 创建博主记录
            blogger = Blogger(
                sec_user_id=sec_uid,
                unique_id=user_info.get("unique_id", ""),
                nickname=user_info.get("nickname", "未知博主"),
                avatar_url=user_info.get("avatar_url", ""),
                signature=user_info.get("signature", ""),
                follower_count=user_info.get("follower_count", 0),
                aweme_count=user_info.get("aweme_count", 0),
                status="crawling",
                started_at=datetime.utcnow()
            )
            db.add(blogger)
            await db.commit()
            await db.refresh(blogger)
            
            logger.info(f"博主添加成功: {blogger.nickname}, ID: {blogger.id}")
            
            # 异步开始处理，传递原始URL
            asyncio.create_task(self.process_blogger(db, blogger.id, url))
            
            return blogger
            
        except Exception as e:
            logger.error(f"添加博主异常: {e}", exc_info=True)
            return None
    
    async def process_blogger(self, db: AsyncSession, blogger_id: int, source_url: str = "") -> bool:
        """完整处理博主 - 使用独立数据库session，适合后台任务运行"""
        # 创建独立的数据库session，避免依赖API请求的session（请求结束后会关闭）
        async with async_session() as own_db:
            return await self._process_blogger_impl(own_db, blogger_id, source_url)
    
    async def _process_blogger_impl(self, db: AsyncSession, blogger_id: int, source_url: str = "") -> bool:
        """完整处理博主实现"""
        try:
            result = await db.execute(
                select(Blogger).where(Blogger.id == blogger_id)
            )
            blogger = result.scalar_one_or_none()
            if not blogger:
                return False
            
            logger.info(f"========== 开始处理博主: {blogger.nickname} ==========")
            
            # 1. 爬取视频列表（带实时进度回调）
            blogger.status = "crawling"
            blogger.current_stage = "正在爬取视频列表..."
            blogger.current_video_index = 0
            blogger.total_videos = 0
            blogger.progress = 0
            blogger.started_at = datetime.utcnow()
            await db.commit()
            
            # 构造用户主页URL
            user_url = source_url
            if blogger.sec_user_id and "/user/" not in user_url and "/video/" not in user_url:
                user_url = f"https://www.douyin.com/user/{blogger.sec_user_id}"
            
            # 爬取进度回调：实时更新数据库中的阶段和数量（使用独立session避免冲突）
            async def on_crawl_progress(count: int, stage_text: str):
                try:
                    async with async_session() as progress_db:
                        result = await progress_db.execute(
                            select(Blogger).where(Blogger.id == blogger_id)
                        )
                        b = result.scalar_one_or_none()
                        if b:
                            b.current_stage = stage_text
                            b.total_videos = count
                            b.progress = min(int(count / max(count + 1, 10) * 20), 19) if count > 0 else 1
                            await progress_db.commit()
                            logger.info(f"[进度更新] {stage_text}")
                except Exception as e:
                    logger.debug(f"更新爬取进度失败: {e}")
            
            videos_info = await self.douyin.get_user_videos(
                user_url,
                max_videos=0,
                known_sec_user_id=blogger.sec_user_id or "",
                progress_callback=on_crawl_progress
            )
            
            if not videos_info:
                logger.warning("未获取到视频列表，尝试作为单个视频处理")
                blogger.status = "failed"
                blogger.current_stage = "爬取失败"
                blogger.error_message = "无法获取视频列表，可能是反爬限制。请尝试直接分享视频链接。"
                await db.commit()
                return False
            
            logger.info(f"爬取到 {len(videos_info)} 个视频")
            blogger.total_videos = len(videos_info)
            blogger.current_stage = f"准备处理 {len(videos_info)} 个视频..."
            blogger.progress = 20
            await db.commit()
            
            # 2. 逐个处理视频
            video_objects = []
            total_videos = len(videos_info)
            for i, v_info in enumerate(videos_info):
                video_num = i + 1
                short_title = v_info['title'][:40]
                logger.info(f"--- 处理视频 {video_num}/{total_videos}: {short_title}... ---")
                
                blogger.current_video_index = video_num
                blogger.current_stage = f"[{video_num}/{total_videos}] 下载视频: {short_title}..."
                blogger.status = "downloading"
                blogger.progress = int(20 + (video_num - 1) / max(total_videos, 1) * 70)
                await db.commit()
                
                video = Video(
                    blogger_id=blogger.id,
                    aweme_id=v_info["aweme_id"],
                    title=v_info["title"],
                    desc=v_info.get("desc", ""),
                    cover_url=v_info.get("cover_url", ""),
                    duration=v_info.get("duration", 0),
                    digg_count=v_info.get("digg_count", 0),
                    comment_count=v_info.get("comment_count", 0),
                    share_count=v_info.get("share_count", 0),
                    collect_count=v_info.get("collect_count", 0),
                    create_time=v_info.get("create_time"),
                    video_url=v_info.get("video_url", v_info.get("webpage_url", "")),
                    status="pending"
                )
                db.add(video)
                await db.commit()
                await db.refresh(video)
                
                # 处理单个视频（带重试机制，最多3次）
                success = False
                for attempt in range(1, 4):
                    if attempt > 1:
                        logger.info(f"  ↩️ 重试第{attempt}次: {video.title[:30]}...")
                        blogger.current_stage = f"[{video_num}/{total_videos}] 重试({attempt}/3): {video.title[:30]}..."
                        await db.commit()
                        await asyncio.sleep(2)
                    
                    success = await self._process_single_video(db, video, blogger, video_num, total_videos)
                    if success:
                        break
                    elif attempt < 3:
                        logger.warning(f"  视频处理失败，准备第{attempt+1}次重试: {video.title[:30]}...")
                
                blogger.processed_videos = video_num
                blogger.progress = int(20 + video_num / max(total_videos, 1) * 70)
                await db.commit()
                
                if success:
                    video_objects.append(video)
                else:
                    logger.error(f"  视频经过3次重试仍失败: {video.title[:30]}...")
            
            # 3. 生成综合大文档
            blogger.status = "summarizing"
            blogger.current_stage = "正在生成综合知识文档..."
            blogger.progress = 90
            await db.commit()
            
            logger.info("========== 生成综合大文档 ==========")
            await self._generate_master_doc(db, blogger, video_objects)
            
            blogger.status = "completed"
            blogger.current_stage = f"处理完成！共分析 {len(video_objects)} 个视频"
            blogger.progress = 100
            blogger.completed_at = datetime.utcnow()
            await db.commit()
            
            logger.info(f"========== 博主处理完成: {blogger.nickname} ==========")
            return True
            
        except Exception as e:
            logger.error(f"处理博主异常: {e}", exc_info=True)
            try:
                result = await db.execute(
                    select(Blogger).where(Blogger.id == blogger_id)
                )
                blogger = result.scalar_one_or_none()
                if blogger:
                    blogger.status = "failed"
                    blogger.error_message = str(e)
                    await db.commit()
            except:
                pass
            return False
    
    async def _process_single_video(self, db: AsyncSession, video: Video, blogger: Blogger = None, video_num: int = 0, total: int = 0) -> bool:
        """处理单个视频：下载 → 提取音频 → ASR → AI总结（含重试时的状态重置）"""
        try:
            def update_stage(stage_text):
                """更新当前处理阶段"""
                if blogger and video_num and total:
                    blogger.current_stage = f"[{video_num}/{total}] {stage_text}"
            
            # 重置视频状态（重试时清理上次失败的标记）
            video.status = "downloading"
            video.error_message = None
            update_stage(f"下载视频: {video.title[:35]}...")
            await db.commit()
            
            # 1. 下载视频
            video_path = None
            if video.local_video_path:
                # 已下载过的直接复用
                from pathlib import Path
                if Path(video.local_video_path).exists():
                    video_path = video.local_video_path
                    logger.info(f"视频已缓存: {video.aweme_id}")
            
            if not video_path:
                video_path = await self.douyin.download_video(
                    video.video_url,
                    video.aweme_id
                )
            
            if video_path:
                video.local_video_path = video_path
                await db.commit()
            else:
                logger.warning(f"视频下载失败，尝试使用描述文本: {video.title}")
            
            # 2. 提取音频并ASR转文字
            transcript = ""
            if video_path:
                video.status = "transcribing"
                update_stage("提取音频并语音转文字...")
                await db.commit()
                
                audio_path = await self._extract_audio(video_path, video.aweme_id)
                
                if audio_path:
                    video.local_audio_path = audio_path
                    await db.commit()
                    
                    update_stage("正在语音识别...")
                    await db.commit()
                    transcript = await self.asr.transcribe(audio_path)
                
                if not transcript and video.desc:
                    transcript = video.desc
            else:
                transcript = video.desc or video.title
            
            if not transcript:
                logger.warning(f"视频无文字内容: {video.title}")
                video.status = "failed"
                video.error_message = "无法获取文字内容（下载失败且无描述）"
                await db.commit()
                return False
            
            video.transcript = transcript
            await db.commit()
            
            transcript_path = self.transcript_dir / f"{video.aweme_id}.txt"
            transcript_path.write_text(transcript, encoding='utf-8')
            
            # 3. AI深度解析总结
            video.status = "summarizing"
            update_stage("AI 分析总结内容...")
            await db.commit()
            
            analysis = await self.gemini.analyze_video(video.title, transcript)
            
            if not analysis:
                video.status = "failed"
                video.error_message = "AI总结返回空结果"
                await db.commit()
                return False
            
            # 保存详细解析和摘要（详细解析在前，摘要在后）
            detailed = analysis.get("detailed_analysis", "")
            summary = analysis.get("summary", "")
            # 合并：详细解析 + 简短摘要，摘要放最后
            video.summary = f"{detailed}\n\n---\n\n**摘要**：{summary}" if detailed and summary else (detailed or summary)
            
            key_points = analysis.get("key_points", [])
            if isinstance(key_points, str):
                import json
                try:
                    key_points = json.loads(key_points)
                except:
                    key_points = [key_points]
            video.key_points = key_points if isinstance(key_points, list) else []
            
            topics = analysis.get("topics", [])
            if isinstance(topics, str):
                import json
                try:
                    topics = json.loads(topics)
                except:
                    topics = [topics]
            video.topics = topics if isinstance(topics, list) else []
            
            takeaways = analysis.get("takeaways", "")
            if isinstance(takeaways, list):
                takeaways = "\n".join([f"- {item}" for item in takeaways])
            video.takeaways = str(takeaways) if takeaways else ""
            
            video.status = "summarized"
            
            try:
                await self.kb.add_video_document(
                    blogger_id=video.blogger_id,
                    video_id=video.id,
                    title=video.title,
                    content=transcript,
                    summary=video.summary
                )
            except Exception as e:
                logger.warning(f"添加到知识库失败: {e}")
            
            await db.commit()
            logger.info(f"视频处理完成: {video.title[:30]}")
            return True
            
        except Exception as e:
            logger.error(f"处理视频异常: {e}", exc_info=True)
            video.status = "failed"
            video.error_message = str(e)[:500]
            await db.commit()
            return False
    
    async def _extract_audio(self, video_path: str, aweme_id: str) -> Optional[str]:
        """使用ffmpeg从视频中提取音频"""
        try:
            audio_path = self.audio_dir / f"{aweme_id}.wav"
            
            if audio_path.exists() and audio_path.stat().st_size > 1000:
                return str(audio_path)
            
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-y",
                str(audio_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and audio_path.exists():
                logger.info(f"音频提取完成: {audio_path}")
                return str(audio_path)
            else:
                logger.warning(f"音频提取失败: {stderr.decode('utf-8', errors='ignore')[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"提取音频异常: {e}")
            return None
    
    async def _generate_master_doc(self, db: AsyncSession, blogger: Blogger, videos: List[Video]):
        """生成综合大文档 - 融合所有视频内容"""
        try:
            # 从数据库重新查询所有已总结的视频（确保包含重试后成功的）
            result = await db.execute(
                select(Video).where(
                    Video.blogger_id == blogger.id,
                    Video.status == "summarized"
                )
            )
            all_summarized = result.scalars().all()
            
            video_summaries = []
            for v in all_summarized:
                if v.summary:
                    video_summaries.append({
                        "title": v.title,
                        "summary": v.summary[:2000],  # 限制每个视频输入长度，确保所有视频都能传入
                        "key_points": v.key_points or [],
                        "topics": v.topics or []
                    })
            
            if not video_summaries:
                logger.warning("没有已总结的视频，跳过综合文档生成")
                return
            
            logger.info(f"综合大文档融合 {len(video_summaries)} 个视频内容")
            
            # 调用AI生成综合大文档
            result = await self.gemini.generate_master_doc(
                blogger_name=blogger.nickname,
                blogger_signature=blogger.signature or "暂无简介",
                video_summaries=video_summaries
            )
            
            if result:
                blogger.master_summary = result.get("master_doc", "")
                blogger.master_topics = result.get("core_topics", [])
                blogger.master_keywords = result.get("key_insights", [])
                logger.info(f"综合大文档生成完成，长度: {len(blogger.master_summary)} 字")
            else:
                logger.warning("综合大文档生成失败")
                
        except Exception as e:
            logger.error(f"生成综合大文档异常: {e}", exc_info=True)


_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
