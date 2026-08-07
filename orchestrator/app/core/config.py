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
    
    # 存储路径
    VIDEO_STORAGE_PATH: str = "./data/videos"
    AUDIO_STORAGE_PATH: str = "./data/audios"
    TRANSCRIPT_STORAGE_PATH: str = "./data/transcripts"
    
    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/orchestrator.db"
    
    # Gemini API 配置
    GEMINI_API_BASE_URL: str = "https://grsai.dakka.com.cn"
    GEMINI_API_KEY: str = "sk-70f67a051b1848f094cf270410772c81"
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    
    # 知识库配置
    KB_STORAGE_PATH: str = "./data/knowledge_base"
    
    # 任务配置
    MAX_CONCURRENT_DOWNLOADS: int = 3
    MAX_CONCURRENT_TRANSCRIBE: int = 2
    REQUEST_INTERVAL: int = 2
    MAX_VIDEOS_PER_BLOGGER: int = 0
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
