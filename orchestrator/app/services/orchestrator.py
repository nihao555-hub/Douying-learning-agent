"""
核心编排服务
完整流程：添加博主 → 爬取视频列表 → 并发下载/转写/AI深度解析 → 生成综合大文档
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
from app.services.video_learning_pipeline import get_video_learning_pipeline


class Orchestrator:
    """编排器"""
    
    def __init__(self):
        self.douyin = get_douyin_client()
        self.asr = get_asr_service()
        self.gemini = get_gemini_client()
        self.kb = get_knowledge_base()
        self.pipeline = get_video_learning_pipeline(self.asr, self.gemini)
        
        self.audio_dir = Path(settings.AUDIO_STORAGE_PATH)
        self.transcript_dir = Path(settings.TRANSCRIPT_STORAGE_PATH)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        
        # 总并发上限（默认 1000）
        self.max_concurrency = max(1, int(getattr(settings, "MAX_CONCURRENT_VIDEOS", 1000) or 1000))
        self._progress_lock = asyncio.Lock()
    
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
    
    async def _update_blogger_progress(
        self,
        blogger_id: int,
        *,
        stage: str = None,
        status: str = None,
        progress: int = None,
        current_index: int = None,
        processed: int = None,
        total: int = None,
        error_message: str = None,
    ):
        """并发安全地更新博主进度（独立 session + 锁）"""
        async with self._progress_lock:
            try:
                async with async_session() as progress_db:
                    result = await progress_db.execute(
                        select(Blogger).where(Blogger.id == blogger_id)
                    )
                    b = result.scalar_one_or_none()
                    if not b:
                        return
                    if stage is not None:
                        b.current_stage = stage
                    if status is not None:
                        b.status = status
                    if progress is not None:
                        b.progress = progress
                    if current_index is not None:
                        b.current_video_index = current_index
                    if processed is not None:
                        b.processed_videos = processed
                    if total is not None:
                        b.total_videos = total
                    if error_message is not None:
                        b.error_message = error_message
                    await progress_db.commit()
            except Exception as e:
                logger.debug(f"更新博主进度失败: {e}")
    
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
            
            # 爬取进度回调：实时更新数据库中的阶段和数量
            async def on_crawl_progress(count: int, stage_text: str):
                await self._update_blogger_progress(
                    blogger_id,
                    stage=stage_text,
                    total=count,
                    progress=min(int(count / max(count + 1, 10) * 20), 19) if count > 0 else 1,
                )
                logger.info(f"[进度更新] {stage_text}")
            
            max_videos = int(getattr(settings, "MAX_VIDEOS_PER_BLOGGER", 0) or 0)
            videos_info = await self.douyin.get_user_videos(
                user_url,
                max_videos=max_videos,
                known_sec_user_id=blogger.sec_user_id or "",
                progress_callback=on_crawl_progress
            )
            
            if not videos_info:
                logger.warning("未获取到视频列表，尝试作为单个视频处理")
                blogger.status = "failed"
                blogger.current_stage = "爬取失败"
                blogger.error_message = (
                    "无法获取视频列表。若博主作品较多，请配置 DOUYIN_COOKIE（登录态）后重试。"
                )
                await db.commit()
                return False
            
            logger.info(f"爬取到 {len(videos_info)} 个视频")
            expected = blogger.aweme_count or 0
            cookie_configured = bool(getattr(settings, "DOUYIN_COOKIE", "") or "")
            if expected and len(videos_info) < expected:
                warn = (
                    f"未登录截断：仅抓到 {len(videos_info)}/{expected}。"
                    "抖音无 Cookie 时第2页起为空，无法全量；请配置 DOUYIN_COOKIE 后点刷新。"
                )
                logger.warning(warn)
                blogger.error_message = warn
            elif not cookie_configured and len(videos_info) > 0:
                blogger.error_message = (
                    "当前无 DOUYIN_COOKIE：只能抓到未登录可见的部分作品，全量需登录 Cookie。"
                )
            else:
                blogger.error_message = None
            
            blogger.total_videos = len(videos_info)
            stage_prefix = (
                f"⚠️ 仅 {len(videos_info)}/{expected}（需Cookie全量）· "
                if expected and len(videos_info) < expected
                else ""
            )
            blogger.current_stage = (
                f"{stage_prefix}准备并发处理 {len(videos_info)} 个视频 "
                f"(并发={self.max_concurrency})..."
            )
            blogger.progress = 20
            blogger.status = "downloading"
            await db.commit()
            
            # 2. 并发处理视频（Semaphore 限制最大并发）
            total_videos = len(videos_info)
            sem = asyncio.Semaphore(self.max_concurrency)
            completed_count = 0
            success_ids: List[int] = []
            count_lock = asyncio.Lock()
            
            async def process_one(index: int, v_info: dict) -> Optional[int]:
                """处理单个视频，返回成功的 video.id"""
                nonlocal completed_count
                video_num = index + 1
                short_title = (v_info.get("title") or "")[:40]
                
                async with sem:
                    # 每个并发任务使用独立 DB session，避免 SQLite/会话冲突
                    async with async_session() as task_db:
                        try:
                            await self._update_blogger_progress(
                                blogger_id,
                                stage=f"[{video_num}/{total_videos}] 处理中: {short_title}...",
                                status="downloading",
                                current_index=video_num,
                            )
                            
                            video = Video(
                                blogger_id=blogger_id,
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
                            task_db.add(video)
                            await task_db.commit()
                            await task_db.refresh(video)
                            
                            success = False
                            for attempt in range(1, 4):
                                if attempt > 1:
                                    logger.info(f"  ↩️ 重试第{attempt}次: {video.title[:30]}...")
                                    await asyncio.sleep(1.5 * attempt)
                                
                                success = await self._process_single_video(
                                    task_db, video, None, video_num, total_videos
                                )
                                if success:
                                    break
                            
                            async with count_lock:
                                completed_count += 1
                                done = completed_count
                                prog = int(20 + done / max(total_videos, 1) * 70)
                            
                            await self._update_blogger_progress(
                                blogger_id,
                                processed=done,
                                progress=prog,
                                current_index=done,
                                stage=(
                                    f"[{done}/{total_videos}] "
                                    + ("完成: " if success else "失败: ")
                                    + short_title
                                ),
                            )
                            
                            if success:
                                logger.info(f"✓ [{done}/{total_videos}] {short_title}")
                                return video.id
                            
                            logger.error(f"✗ [{done}/{total_videos}] 3次重试仍失败: {short_title}")
                            return None
                        except Exception as e:
                            logger.error(f"并发处理视频异常 {short_title}: {e}", exc_info=True)
                            async with count_lock:
                                completed_count += 1
                            return None
            
            logger.info(
                f"========== 开始并发处理 {total_videos} 个视频 "
                f"(max_concurrency={self.max_concurrency}) =========="
            )
            results = await asyncio.gather(
                *[process_one(i, v) for i, v in enumerate(videos_info)],
                return_exceptions=True,
            )
            
            for r in results:
                if isinstance(r, int):
                    success_ids.append(r)
                elif isinstance(r, Exception):
                    logger.error(f"并发任务异常: {r}")
            
            # 重新加载成功的视频对象供综合文档使用
            video_objects: List[Video] = []
            if success_ids:
                result = await db.execute(
                    select(Video).where(Video.id.in_(success_ids))
                )
                video_objects = list(result.scalars().all())
            
            logger.info(
                f"并发处理完成: 成功 {len(video_objects)}/{total_videos}"
            )
            
            # 3. 生成综合大文档
            blogger = (await db.execute(
                select(Blogger).where(Blogger.id == blogger_id)
            )).scalar_one_or_none()
            if not blogger:
                return False
            
            blogger.status = "summarizing"
            blogger.current_stage = "正在生成综合知识文档..."
            blogger.progress = 90
            blogger.processed_videos = len(video_objects)
            blogger.total_videos = total_videos
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
            except Exception:
                pass
            return False
    
    async def _process_single_video(
        self,
        db: AsyncSession,
        video: Video,
        blogger: Blogger = None,
        video_num: int = 0,
        total: int = 0,
    ) -> bool:
        """
        六层完整学习：
        素材下载 → 音频 → 时间戳ASR → 关键帧多模态 → 结构化深度解析
        → 知识卡片入库 → 验收门禁
        注意：不是把整段大视频直接塞给 LLM；而是 ASR+关键帧后再解析（大视频自动分段）。
        """
        try:
            def update_stage(stage_text):
                if blogger and video_num and total:
                    blogger.current_stage = f"[{video_num}/{total}] {stage_text}"
            
            video.status = "downloading"
            video.error_message = None
            update_stage(f"下载完整素材: {video.title[:35]}...")
            await db.commit()
            
            video_path = None
            if video.local_video_path and Path(video.local_video_path).exists():
                video_path = video.local_video_path
                logger.info(f"视频已缓存: {video.aweme_id}")
            
            if not video_path:
                video_path = await self.douyin.download_video(video.video_url, video.aweme_id)
            
            if video_path:
                video.local_video_path = video_path
                await db.commit()
            else:
                logger.warning(f"视频下载失败，将尽量用描述/分享页文案继续: {video.title}")
            
            audio_path = None
            if video_path:
                video.status = "transcribing"
                update_stage("提取音频...")
                await db.commit()
                audio_path = await self._extract_audio(video_path, video.aweme_id)
                if audio_path:
                    video.local_audio_path = audio_path
                    await db.commit()
            
            video.status = "summarizing"
            update_stage("完整学习：切片ASR/深度解析/知识卡片...")
            await db.commit()
            
            learned = await self.pipeline.learn_video(
                title=video.title or "",
                desc=video.desc or "",
                video_path=video_path,
                audio_path=audio_path,
                duration=int(video.duration or 0),
                aweme_id=video.aweme_id,
            )
            
            timed = learned.get("timed_transcript") or video.desc or video.title or ""
            if not timed:
                video.status = "failed"
                video.error_message = "无法获取可学习文本（无ASR/无描述）"
                await db.commit()
                return False
            
            video.transcript = timed
            video.transcript_segments = learned.get("asr_segments") or []
            video.frame_notes = learned.get("frame_notes") or []
            video.knowledge_cards = learned.get("knowledge_cards") or []
            video.quality_report = learned.get("quality") or {}
            
            transcript_path = self.transcript_dir / f"{video.aweme_id}.txt"
            transcript_path.write_text(timed, encoding="utf-8")
            
            analysis = learned.get("analysis") or {}
            detailed = (analysis.get("detailed_analysis") or "").strip()
            summary = (analysis.get("summary") or "").strip()
            quality = video.quality_report or {}
            
            sparse = "口播稀少；" if quality.get("speech_sparse") else ""
            quality_block = (
                f"\n\n---\n\n**学习验收**：得分 {quality.get('score', 0)} / "
                f"{'通过' if quality.get('passed') else '未通过'}；{sparse}"
                f"转写{quality.get('transcript_chars', 0)}字；"
                f"解析{quality.get('analysis_chars', 0)}字；"
                f"卡片{quality.get('knowledge_cards', 0)}张；"
                f"切片流水线（无抽帧）；"
                f"问题：{', '.join(quality.get('issues') or []) or '无'}"
            )
            
            if detailed and summary:
                video.summary = f"{detailed}\n\n---\n\n**摘要**：{summary}{quality_block}"
            else:
                video.summary = (detailed or summary or timed) + quality_block
            
            key_points = analysis.get("key_points", [])
            if isinstance(key_points, str):
                import json as _json
                try:
                    key_points = _json.loads(key_points)
                except Exception:
                    key_points = [key_points]
            video.key_points = key_points if isinstance(key_points, list) else []
            
            topics = analysis.get("topics", [])
            if isinstance(topics, str):
                import json as _json
                try:
                    topics = _json.loads(topics)
                except Exception:
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
                    content=timed,
                    summary=video.summary,
                )
                if hasattr(self.kb, "add_knowledge_cards"):
                    await self.kb.add_knowledge_cards(
                        blogger_id=video.blogger_id,
                        video_id=video.id,
                        title=video.title,
                        cards=video.knowledge_cards or [],
                    )
            except Exception as e:
                logger.warning(f"添加到知识库失败: {e}")
            
            await db.commit()
            logger.info(
                f"完整学习完成: {video.title[:30]}... "
                f"解析={len(detailed)}字 cards={len(video.knowledge_cards or [])} "
                f"quality={quality.get('score')} passed={quality.get('passed')}"
            )
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
                        # 传入更完整的深度解析，避免综合文档只看到摘要
                        "summary": v.summary[:4000],
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
