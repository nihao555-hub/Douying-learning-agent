"""
编排服务主入口
同时托管 dashboard 前端静态资源，便于通过同一公网隧道访问。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.logger import logger
from app.api import bloggers, system, knowledge

import os

os.makedirs(settings.VIDEO_STORAGE_PATH, exist_ok=True)
os.makedirs(settings.AUDIO_STORAGE_PATH, exist_ok=True)
os.makedirs(settings.TRANSCRIPT_STORAGE_PATH, exist_ok=True)
os.makedirs(settings.KB_STORAGE_PATH, exist_ok=True)

DASHBOARD_DIST = Path(__file__).resolve().parents[1] / "dashboard" / "dist"

app = FastAPI(
    title="抖音博主学习 Agent - 编排服务",
    description="连接抖音爬虫、语音识别和 AI 知识库的编排服务（基于 yt-dlp 140k+ stars 开源项目）",
    version="2.0.0",
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
    if DASHBOARD_DIST.exists():
        logger.info(f"前端静态资源: {DASHBOARD_DIST}")
    else:
        logger.warning(f"前端 dist 不存在: {DASHBOARD_DIST}")
    logger.info("编排服务启动完成")


@app.get("/api")
@app.get("/api/")
async def api_root():
    return {
        "name": "抖音博主学习 Agent - 编排服务",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
        "crawler": "yt-dlp (140k+ stars on GitHub)",
        "frontend": "/",
    }


# 前端静态资源（与 /api 同域，避免跨域/Vercel 依赖）
if (DASHBOARD_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DASHBOARD_DIST / "assets")), name="assets")


@app.get("/")
async def spa_index():
    index = DASHBOARD_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "name": "抖音博主学习 Agent - 编排服务",
            "version": "2.0.0",
            "status": "running",
            "docs": "/docs",
            "warning": "dashboard/dist 未构建，仅 API 可用",
        }
    )


@app.get("/favicon.svg")
async def favicon():
    path = DASHBOARD_DIST / "favicon.svg"
    if path.exists():
        return FileResponse(path)
    return JSONResponse({"detail": "not found"}, status_code=404)


@app.get("/icons.svg")
async def icons():
    path = DASHBOARD_DIST / "icons.svg"
    if path.exists():
        return FileResponse(path)
    return JSONResponse({"detail": "not found"}, status_code=404)


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """SPA 路由回退；不拦截 API/文档。"""
    blocked_prefixes = ("api/", "docs", "openapi.json", "redoc", "assets/")
    if full_path.startswith(blocked_prefixes) or full_path in {
        "docs",
        "openapi.json",
        "redoc",
        "favicon.svg",
        "icons.svg",
    }:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # 尝试返回 dist 下真实文件
    candidate = DASHBOARD_DIST / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)

    index = DASHBOARD_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.ORCHESTRATOR_PORT,
        reload=True,
    )
