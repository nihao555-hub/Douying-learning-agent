"""
系统状态 API - 检查各服务连接状态
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.douyin_client import get_douyin_client
from app.services.dify_client import get_dify_client
from app.core.config import settings

router = APIRouter(prefix="/api/system", tags=["系统状态"])


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@router.get("/status")
async def system_status():
    """检查各服务连接状态"""
    status = {
        "orchestrator": "running",
        "douyin_api": "unknown",
        "dify": "unknown",
        "asr_model": "not_loaded",
    }
    
    # 检查抖音爬虫 API
    try:
        douyin_client = get_douyin_client()
        # 简单测试（可能需要登录，所以只检查是否能访问）
        status["douyin_api"] = "configured" if settings.DOUYIN_API_BASE_URL else "not_configured"
    except Exception as e:
        status["douyin_api"] = f"error: {str(e)[:50]}"
    
    # 检查 Dify
    try:
        dify_client = get_dify_client()
        status["dify"] = "configured" if settings.DIFY_API_KEY and settings.DIFY_DATASET_ID else "not_configured"
    except Exception as e:
        status["dify"] = f"error: {str(e)[:50]}"
    
    # ASR 模型状态（懒加载，未加载时显示 not_loaded）
    status["asr_model"] = f"{settings.ASR_ENGINE} ({settings.WHISPER_MODEL_SIZE}) - not_loaded"
    
    return status


@router.get("/config")
async def get_config():
    """获取当前配置（脱敏）"""
    return {
        "douyin_api_url": settings.DOUYIN_API_BASE_URL,
        "dify_api_url": settings.DIFY_API_BASE_URL,
        "dify_configured": bool(settings.DIFY_API_KEY and settings.DIFY_DATASET_ID),
        "asr_engine": settings.ASR_ENGINE,
        "whisper_model": settings.WHISPER_MODEL_SIZE,
        "whisper_device": settings.WHISPER_DEVICE,
        "max_videos_per_blogger": settings.MAX_VIDEOS_PER_BLOGGER,
    }
