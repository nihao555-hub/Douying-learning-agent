"""
数据模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Blogger(Base):
    """博主信息"""
    __tablename__ = "bloggers"
    
    id = Column(Integer, primary_key=True, index=True)
    sec_user_id = Column(String(200), unique=True, index=True, comment="抖音sec_user_id")
    unique_id = Column(String(200), comment="抖音号/unique_id")
    nickname = Column(String(200), comment="昵称")
    avatar_url = Column(String(500), comment="头像URL")
    signature = Column(Text, comment="简介")
    follower_count = Column(Integer, default=0, comment="粉丝数")
    aweme_count = Column(Integer, default=0, comment="作品数")
    total_favorited = Column(Integer, default=0, comment="总获赞数")
    status = Column(String(20), default="pending", comment="状态: pending/crawling/downloading/transcribing/summarizing/completed/failed")
    total_videos = Column(Integer, default=0, comment="爬取视频数")
    processed_videos = Column(Integer, default=0, comment="已处理视频数")
    summarized_videos = Column(Integer, default=0, comment="已总结视频数")
    progress = Column(Float, default=0, comment="进度 0-100")
    current_stage = Column(String(200), default="", comment="当前处理阶段描述")
    current_video_index = Column(Integer, default=0, comment="当前处理第几个视频")
    master_summary = Column(Text, comment="综合大文档：所有视频的整体知识体系总结")
    master_topics = Column(JSON, comment="博主核心主题分类")
    master_keywords = Column(JSON, comment="博主核心关键词")
    started_at = Column(DateTime, comment="开始处理时间")
    completed_at = Column(DateTime, comment="完成时间")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    videos = relationship("Video", back_populates="blogger", cascade="all, delete-orphan")


class Video(Base):
    """视频信息"""
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    blogger_id = Column(Integer, ForeignKey("bloggers.id"), index=True)
    aweme_id = Column(String(100), unique=True, index=True, comment="视频ID")
    title = Column(String(500), comment="视频标题/描述")
    desc = Column(Text, comment="视频完整描述")
    cover_url = Column(String(500), comment="封面URL")
    duration = Column(Integer, default=0, comment="视频时长(秒)")
    digg_count = Column(Integer, default=0, comment="点赞数")
    comment_count = Column(Integer, default=0, comment="评论数")
    share_count = Column(Integer, default=0, comment="分享数")
    collect_count = Column(Integer, default=0, comment="收藏数")
    play_count = Column(Integer, default=0, comment="播放数")
    create_time = Column(DateTime, comment="发布时间")
    video_url = Column(String(1000), comment="视频直链")
    local_video_path = Column(String(500), comment="本地视频路径")
    local_audio_path = Column(String(500), comment="本地音频路径")
    transcript = Column(Text, comment="语音转文字全文(可含时间戳)")
    transcript_segments = Column(JSON, comment="ASR分段 [{start,end,text}]")
    frame_notes = Column(JSON, comment="关键帧OCR/画面笔记")
    knowledge_cards = Column(JSON, comment="知识原子卡片列表")
    quality_report = Column(JSON, comment="完整学习验收报告")
    summary = Column(Text, comment="AI完整深度解析（含详细分析+短摘要）")
    key_points = Column(JSON, comment="核心要点列表")
    topics = Column(JSON, comment="视频涉及主题")
    takeaways = Column(Text, comment="金句/可操作建议")
    dify_document_id = Column(String(200), comment="Dify文档ID")
    status = Column(String(20), default="pending", comment="状态: pending/downloaded/transcribed/summarized/failed")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    blogger = relationship("Blogger", back_populates="videos")


class Task(Base):
    """任务记录"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), comment="任务类型")
    blogger_id = Column(Integer, index=True, comment="博主ID")
    status = Column(String(20), default="pending", comment="状态")
    progress = Column(Float, default=0, comment="进度")
    result = Column(JSON, comment="结果")
    error_message = Column(Text, comment="错误信息")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    created_at = Column(DateTime, default=datetime.utcnow)
