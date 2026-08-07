"""
知识库问答 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel, Field

from app.models.models import Blogger
from app.core.database import get_db
from app.services.knowledge_base import get_knowledge_base as get_kb_service
from app.services.gemini_client import get_gemini_client
from app.core.logger import logger

router = APIRouter(prefix="/api/knowledge", tags=["知识库问答"])


class QueryRequest(BaseModel):
    blogger_id: int = Field(..., description="博主ID")
    query: str = Field(..., description="问题")
    top_k: int = Field(5, description="检索数量")


class SearchResult(BaseModel):
    content: str
    metadata: dict = {}
    score: float = 0.0


class AnswerResponse(BaseModel):
    answer: str
    sources: List[SearchResult] = []
    blogger_name: str = ""


@router.post("/search")
async def search_knowledge(req: QueryRequest, db: AsyncSession = Depends(get_db)):
    """检索知识库"""
    # 验证博主存在
    result = await db.execute(
        select(Blogger).where(Blogger.id == req.blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    kb_service = get_kb_service()
    results = kb_service.search(
        blogger_id=req.blogger_id,
        query=req.query,
        top_k=req.top_k
    )
    
    return {
        "blogger_id": req.blogger_id,
        "blogger_name": blogger.nickname,
        "query": req.query,
        "results": results
    }


@router.post("/ask", response_model=AnswerResponse)
async def ask_question(req: QueryRequest, db: AsyncSession = Depends(get_db)):
    """RAG 问答"""
    # 验证博主存在
    result = await db.execute(
        select(Blogger).where(Blogger.id == req.blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    # 1. 检索相关内容
    kb_service = get_kb_service()
    search_results = kb_service.search(
        blogger_id=req.blogger_id,
        query=req.query,
        top_k=req.top_k
    )
    
    if not search_results:
        return AnswerResponse(
            answer="知识库中暂无相关内容，请先等待视频处理完成。",
            sources=[],
            blogger_name=blogger.nickname
        )
    
    # 2. 用 Gemini 生成回答
    contexts = [r["content"] for r in search_results]
    gemini_client = get_gemini_client()
    
    answer = await gemini_client.rag_answer(
        query=req.query,
        contexts=contexts,
        blogger_name=blogger.nickname
    )
    
    if not answer:
        return AnswerResponse(
            answer="抱歉，AI 回答生成失败，请稍后重试。",
            sources=search_results,
            blogger_name=blogger.nickname
        )
    
    return AnswerResponse(
        answer=answer,
        sources=search_results,
        blogger_name=blogger.nickname
    )


@router.get("/stats/{blogger_id}")
async def get_kb_stats(blogger_id: int, db: AsyncSession = Depends(get_db)):
    """获取知识库统计"""
    result = await db.execute(
        select(Blogger).where(Blogger.id == blogger_id)
    )
    blogger = result.scalar_one_or_none()
    
    if not blogger:
        raise HTTPException(status_code=404, detail="博主不存在")
    
    kb_service = get_kb_service()
    stats = kb_service.get_stats(blogger_id)
    stats["blogger_name"] = blogger.nickname
    
    return stats
