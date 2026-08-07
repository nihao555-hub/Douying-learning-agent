"""
系统状态 API - 检查各服务连接状态 / 质量检测
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.douyin_client import get_douyin_client
from app.services.douyin_login_session import get_douyin_login_session
from app.services.dify_client import get_dify_client
from app.services.quality_audit import run_quality_audit
from app.core.config import settings
from pathlib import Path

router = APIRouter(prefix="/api/system", tags=["系统状态"])


class DouyinLoginStatusRequest(BaseModel):
    session_token: str


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
    
    # ASR 模型：检查本地模型文件是否就绪
    model_path = getattr(settings, "WHISPER_MODEL_PATH", "") or "./data/models/faster-whisper-base"
    model_ok = Path(model_path).exists() and (Path(model_path) / "model.bin").exists()
    status["asr_model"] = (
        f"{settings.ASR_ENGINE} ({settings.WHISPER_MODEL_SIZE}) - "
        + ("ready" if model_ok else "model_missing")
    )
    
    return status


@router.get("/config")
async def get_config():
    """获取当前配置（严格脱敏：绝不返回任何密钥/Cookie）"""
    return {
        "douyin_api_url": settings.DOUYIN_API_BASE_URL,
        "dify_api_url": settings.DIFY_API_BASE_URL,
        "dify_configured": bool(settings.DIFY_API_KEY and settings.DIFY_DATASET_ID),
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "gemini_model": settings.GEMINI_MODEL,
        "douyin_cookie_configured": bool(getattr(settings, "DOUYIN_COOKIE", "")),
        "asr_engine": settings.ASR_ENGINE,
        "whisper_model": settings.WHISPER_MODEL_SIZE,
        "whisper_device": settings.WHISPER_DEVICE,
        "max_videos_per_blogger": settings.MAX_VIDEOS_PER_BLOGGER,
        "max_concurrent_videos": getattr(settings, "MAX_CONCURRENT_VIDEOS", 1000),
        "max_pipeline_workers": getattr(settings, "MAX_PIPELINE_WORKERS", 20),
        "video_slice_seconds": getattr(settings, "VIDEO_SLICE_SECONDS", 120),
        "full_video_pipeline": True,
        "no_frame_extraction": True,
    }


@router.post("/douyin-login/start")
async def start_douyin_login():
    """
    启动隔离的抖音登录浏览器。
    登录窗口 10 分钟后失效；Cookie 明文永不返回前端。
    """
    try:
        return await get_douyin_login_session().start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"登录窗口启动失败: {str(exc)[:300]}")


@router.post("/douyin-login/status")
async def douyin_login_status(req: DouyinLoginStatusRequest):
    """检测登录并在服务端自动捕获 Cookie（响应仅含脱敏状态）。"""
    try:
        return await get_douyin_login_session().status(req.session_token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"登录状态检测失败: {str(exc)[:300]}")


@router.post("/douyin-login/stop")
async def stop_douyin_login(req: DouyinLoginStatusRequest):
    """关闭当前登录窗口。"""
    session = get_douyin_login_session()
    if not session.token or req.session_token != session.token:
        raise HTTPException(status_code=403, detail="登录会话无效")
    await session.stop()
    return {"stopped": True}


@router.get("/quality-audit")
async def quality_audit(
    blogger_id: Optional[int] = Query(None, description="仅审计指定博主；默认全部"),
    persist: bool = Query(False, description="是否把重算后的验收写入数据库"),
    db: AsyncSession = Depends(get_db),
):
    """
    完整质量检测：
    - 基础设施（Gemini / Whisper / ffmpeg / 并发配置 / Cookie）
    - 抓取覆盖（crawled vs aweme_count）
    - 素材完整性（完整视频/音频）
    - 学习验收重算（切片 ASR 流水线，无抽帧；口播稀少单独计分）
    - 综合文档
    """
    return await run_quality_audit(db, blogger_id=blogger_id, persist_reeval=persist)
