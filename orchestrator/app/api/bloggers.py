"""
博主管理 API
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.models.models import Blogger, Video
from app.core.database import get_db, async_session
from app.services.orchestrator import get_orchestrator
from app.core.logger import logger

router = APIRouter(prefix="/api/bloggers", tags=["博主管理"])
orchestrator = get_orchestrator()


class AddBloggerRequest(BaseModel):
    share_url: str = Field(..., description="抖音博主主页链接或视频分享链接")


class VideoResponse(BaseModel):
    id: int
    aweme_id: str
    title: str
    desc: str = ""
    cover_url: str = ""
    duration: int = 0
    digg_count: int = 0
    comment_count: int = 0
    create_time: Optional[datetime] = None
    status: str = "pending"
    summary: Optional[str] = None
    key_points: Optional[list] = None
    topics: Optional[list] = None
    takeaways: Optional[str] = None
    transcript: Optional[str] = None
    transcript_segments: Optional[list] = None
    frame_notes: Optional[list] = None
    knowledge_cards: Optional[list] = None
    quality_report: Optional[dict] = None
    
    class Config:
        from_attributes = True


class BloggerResponse(BaseModel):
    id: int
    sec_user_id: str = ""
    unique_id: str = ""
    nickname: str
    avatar_url: str = ""
    signature: str = ""
    follower_count: int = 0
    aweme_count: int = 0
    total_favorited: int = 0
    status: str = "pending"
    total_videos: int = 0
    processed_videos: int = 0
    summarized_videos: int = 0
    failed_videos: int = 0
    pending_videos: int = 0
    current_video_index: int = 0
    progress: float = 0
    current_stage: str = ""
    master_summary: Optional[str] = None
    master_topics: Optional[list] = None
    master_keywords: Optional[list] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class BloggerDetailResponse(BloggerResponse):
    videos: List[VideoResponse] = []


async def _attach_video_stats(db: AsyncSession, blogger: Blogger) -> Blogger:
    """用真实视频状态回填成功/失败/待处理计数，避免前端长期看到假进度。"""
    result = await db.execute(select(Video).where(Video.blogger_id == blogger.id))
    videos = list(result.scalars().all())
    summarized = sum(1 for v in videos if v.status == "summarized")
    failed = sum(1 for v in videos if v.status == "failed")
    pending = sum(
        1
        for v in videos
        if v.status in {"pending", "downloading", "transcribing", "summarizing"}
    )
    blogger.summarized_videos = summarized
    blogger.processed_videos = summarized
    blogger.failed_videos = failed
    blogger.pending_videos = pending
    if not blogger.total_videos:
        blogger.total_videos = len(videos)
    return blogger


@router.post("", response_model=BloggerResponse)
async def add_blogger(
    req: AddBloggerRequest,
    db: AsyncSession = Depends(get_db)
):
    """添加博主并开始处理（自动异步处理）"""
    try:
        blogger = await orchestrator.add_blogger(db, req.share_url)
        
        if not blogger:
            raise HTTPException(status_code=400, detail="无法获取博主信息，请检查链接是否正确")
        
        await db.refresh(blogger)
        return await _attach_video_stats(db, blogger)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加博主失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"添加博主失败: {str(e)}")


@router.get("", response_model=List[BloggerResponse])
async def list_bloggers(db: AsyncSession = Depends(get_db)):
    """获取博主列表"""
    result = await db.execute(
        select(Blogger).order_by(Blogger.created_at.desc())
    )
    bloggers = result.scalars().all()
    out = []
    for b in bloggers:
        out.append(await _attach_video_stats(db, b))
    return out


@router.get("/{blogger_id}", response_model=BloggerDetailResponse)
async def get_blogger(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """获取博主详情（含视频列表）"""
    result = await db.execute(
        select(Blogger)
        .options(selectinload(Blogger.videos))
        .where(Blogger.id == blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    await _attach_video_stats(db, blogger)
    return blogger


@router.get("/{blogger_id}/videos", response_model=List[VideoResponse])
async def get_blogger_videos(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """获取博主的所有视频"""
    result = await db.execute(
        select(Video)
        .where(Video.blogger_id == blogger_id)
        .order_by(Video.create_time.desc().nullslast(), Video.id.desc())
    )
    return result.scalars().all()


@router.get("/{blogger_id}/master-doc")
async def get_master_doc(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """获取博主综合大文档"""
    result = await db.execute(
        select(Blogger).where(Blogger.id == blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    return {
        "blogger_id": blogger.id,
        "nickname": blogger.nickname,
        "signature": blogger.signature,
        "master_summary": blogger.master_summary,
        "master_topics": blogger.master_topics or [],
        "master_keywords": blogger.master_keywords or [],
        "total_videos": blogger.total_videos,
        "summarized_videos": blogger.summarized_videos,
        "status": blogger.status,
    }


@router.get("/{blogger_id}/videos/{video_id}", response_model=VideoResponse)
async def get_video_detail(
    blogger_id: int,
    video_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取单个视频详情"""
    result = await db.execute(
        select(Video).where(
            Video.id == video_id,
            Video.blogger_id == blogger_id
        )
    )
    video = result.scalar_one_or_none()
    
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    
    return video


@router.post("/{blogger_id}/refresh")
async def refresh_blogger(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """重新处理博主"""
    result = await db.execute(
        select(Blogger).where(Blogger.id == blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    # 删除旧视频
    vid_result = await db.execute(
        select(Video).where(Video.blogger_id == blogger_id)
    )
    for v in vid_result.scalars().all():
        await db.delete(v)
    
    # 重置状态
    blogger.status = "crawling"
    blogger.progress = 0
    blogger.processed_videos = 0
    blogger.summarized_videos = 0
    blogger.master_summary = None
    blogger.master_topics = None
    blogger.master_keywords = None
    blogger.started_at = datetime.utcnow()
    blogger.completed_at = None
    blogger.error_message = None
    await db.commit()
    await db.refresh(blogger)
    
    # 异步重新处理
    import asyncio
    source_url = f"https://www.douyin.com/user/{blogger.sec_user_id}" if blogger.sec_user_id else ""
    asyncio.create_task(orchestrator.process_blogger(db, blogger_id, source_url))
    
    return {"message": "已开始重新处理", "blogger_id": blogger_id}


@router.post("/{blogger_id}/resume")
async def resume_blogger(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """恢复未完成视频（不删除已成功结果）"""
    result = await db.execute(select(Blogger).where(Blogger.id == blogger_id))
    blogger = result.scalar_one_or_none()
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")

    import asyncio
    asyncio.create_task(orchestrator.resume_unfinished_videos(blogger_id))
    return {
        "message": "已开始恢复未完成视频",
        "blogger_id": blogger_id,
        "hint": "已成功视频会保留，仅重试未完成/失败项",
    }


@router.delete("/{blogger_id}")
async def delete_blogger(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """删除博主"""
    result = await db.execute(
        select(Blogger).where(Blogger.id == blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    await db.delete(blogger)
    await db.commit()
    
    return {"message": "删除成功", "blogger_id": blogger_id}
