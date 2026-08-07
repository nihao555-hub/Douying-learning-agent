"""
编排服务主入口
同时托管 dashboard 前端静态资源，便于通过同一公网隧道访问。
"""
from pathlib import Path
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import websockets

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
NOVNC_ROOT = Path("/usr/local/novnc/noVNC-1.2.0")

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
    # 永久 Cookie：从 data/secrets 加载，重启不丢失
    try:
        from app.services.cookie_store import bootstrap_cookie_on_startup
        bootstrap_cookie_on_startup()
    except Exception as e:
        logger.warning(f"加载永久 Cookie 失败: {e}")
    logger.info(f"ASR 引擎: {settings.ASR_ENGINE} ({settings.WHISPER_MODEL_SIZE})")
    if DASHBOARD_DIST.exists():
        logger.info(f"前端静态资源: {DASHBOARD_DIST}")
    else:
        logger.warning(f"前端 dist 不存在: {DASHBOARD_DIST}")
    # 恢复被重启打断的任务，避免长期「处理中 / 成功 0」
    try:
        from app.services.orchestrator import get_orchestrator

        async def _delayed_recover():
            await asyncio.sleep(3)
            await get_orchestrator().recover_interrupted_jobs()

        asyncio.create_task(_delayed_recover())
    except Exception as e:
        logger.warning(f"启动恢复任务失败: {e}")
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


@app.websocket("/novnc/websockify")
async def novnc_websocket_proxy(websocket: WebSocket):
    """把同源 noVNC WebSocket 代理到隔离登录窗口，避免额外公网隧道。"""
    requested = websocket.headers.get("sec-websocket-protocol", "")
    protocols = [p.strip() for p in requested.split(",") if p.strip()]
    selected = "binary" if "binary" in protocols else (protocols[0] if protocols else None)
    await websocket.accept(subprotocol=selected)

    try:
        async with websockets.connect(
            "ws://127.0.0.1:26059",
            subprotocols=["binary"],
            max_size=None,
            open_timeout=5,
        ) as upstream:
            async def client_to_upstream():
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    payload = message.get("bytes")
                    if payload is None:
                        payload = message.get("text")
                    if payload is not None:
                        await upstream.send(payload)

            async def upstream_to_client():
                async for payload in upstream:
                    if isinstance(payload, bytes):
                        await websocket.send_bytes(payload)
                    else:
                        await websocket.send_text(payload)

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                try:
                    task.result()
                except (WebSocketDisconnect, RuntimeError):
                    pass
    except (OSError, WebSocketDisconnect):
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass


if NOVNC_ROOT.exists():
    app.mount("/novnc", StaticFiles(directory=str(NOVNC_ROOT)), name="novnc")


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
    blocked_prefixes = ("api/", "docs", "openapi.json", "redoc", "assets/", "novnc/")
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
