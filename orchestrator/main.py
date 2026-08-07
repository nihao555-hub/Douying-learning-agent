"""
编排服务主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db
from app.core.logger import logger
from app.api import bloggers, system, knowledge

import os
os.makedirs(settings.VIDEO_STORAGE_PATH, exist_ok=True)
os.makedirs(settings.AUDIO_STORAGE_PATH, exist_ok=True)
os.makedirs(settings.TRANSCRIPT_STORAGE_PATH, exist_ok=True)
os.makedirs(settings.KB_STORAGE_PATH, exist_ok=True)

app = FastAPI(
    title="抖音博主学习 Agent - 编排服务",
    description="连接抖音爬虫、语音识别和 AI 知识库的编排服务（基于 yt-dlp 140k+ stars 开源项目）",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(bloggers.router)
app.include_router(system.router)
app.include_router(knowledge.router)


@app.on_event("startup")
async def startup():
    logger.info("编排服务启动中...")
    await init_db()
    logger.info("数据库初始化完成")
    logger.info(f"ASR 引擎: {settings.ASR_ENGINE} ({settings.WHISPER_MODEL_SIZE})")
    logger.info("编排服务启动完成")


@app.get("/")
async def root():
    return {
        "name": "抖音博主学习 Agent - 编排服务",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
        "crawler": "yt-dlp (140k+ stars on GitHub)"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.ORCHESTRATOR_PORT,
        reload=True
    )
