"""
配置管理
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""
    
    # 服务配置
    ORCHESTRATOR_PORT: int = 8000
    
    # 抖音爬虫 API
    DOUYIN_API_BASE_URL: str = "http://localhost:5000"
    # 抖音登录 Cookie（必需才能翻页获取博主全部视频；未登录 API 硬限制约 40-44 条）
    DOUYIN_COOKIE: str = ""
    
    # Dify 配置
    DIFY_API_BASE_URL: str = "http://localhost:8080"
    DIFY_API_KEY: str = ""
    DIFY_DATASET_ID: str = ""
    
    # 语音识别
    ASR_ENGINE: str = "faster-whisper"
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_LANGUAGE: str = "zh"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    # 本地 faster-whisper 模型目录（优先于在线下载）
    WHISPER_MODEL_PATH: str = "./data/models/faster-whisper-base"
    
    # 存储路径
    VIDEO_STORAGE_PATH: str = "./data/videos"
    AUDIO_STORAGE_PATH: str = "./data/audios"
    TRANSCRIPT_STORAGE_PATH: str = "./data/transcripts"
    
    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/orchestrator.db"
    
    # Gemini API 配置（密钥仅服务端环境变量，禁止硬编码进仓库/前端）
    GEMINI_API_BASE_URL: str = "https://grsai.dakka.com.cn"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    
    # 知识库配置
    KB_STORAGE_PATH: str = "./data/knowledge_base"
    
    # 任务配置
    MAX_CONCURRENT_DOWNLOADS: int = 3
    MAX_CONCURRENT_TRANSCRIBE: int = 2
    # 视频处理总并发上限（下载+ASR+AI解析流水线）
    MAX_CONCURRENT_VIDEOS: int = 1000
    REQUEST_INTERVAL: int = 2
    # 视频完整学习流水线（切片，不抽帧）
    VIDEO_CHUNK_CHARS: int = 8000
    VIDEO_SLICE_SECONDS: int = 120
    MAX_VIDEOS_PER_BLOGGER: int = 0
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
