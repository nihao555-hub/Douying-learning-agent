"""
本地向量知识库服务
使用 ChromaDB 作为轻量级向量数据库
使用简单的内置embedding，避免下载大模型
"""
import os
import hashlib
from typing import List, Dict, Optional
from app.core.config import settings
from app.core.logger import logger

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None


class SimpleEmbedding:
    """简单的词袋embedding，无需下载模型"""
    
    def __init__(self, dim: int = 384):
        self.dim = dim
    
    def __call__(self, input: List[str]) -> List[List[float]]:
        results = []
        for text in input:
            # 使用简单的hash-based embedding
            if np is None:
                vector = [0.0] * self.dim
                words = text.replace('\n', ' ').split()
                for i, word in enumerate(words[:200]):
                    h = int(hashlib.md5(word.encode('utf-8')).hexdigest(), 16)
                    idx = h % self.dim
                    vector[idx] += 1.0 / (i + 1)
                norm = sum(x * x for x in vector) ** 0.5
                if norm > 0:
                    vector = [x / norm for x in vector]
                results.append(vector)
                continue
            vector = np.zeros(self.dim, dtype=np.float32)
            words = text.replace('\n', ' ').split()
            for i, word in enumerate(words[:200]):
                h = int(hashlib.md5(word.encode('utf-8')).hexdigest(), 16)
                idx = h % self.dim
                vector[idx] += 1.0 / (i + 1)
            # 归一化
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm
            results.append(vector.tolist())
        return results


class KnowledgeBaseService:
    """本地向量知识库服务（ChromaDB 不可用时降级为空实现，不阻塞主流程）"""
    
    def __init__(self):
        self.persist_dir = os.path.join(settings.KB_STORAGE_PATH, "chroma")
        os.makedirs(self.persist_dir, exist_ok=True)
        self.embedding_fn = SimpleEmbedding()
        self.client = None
        self.available = False
        
        if chromadb is None:
            logger.warning("ChromaDB 未安装，知识库检索降级为不可用（不影响爬取/解析主流程）")
            return
        
        try:
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            self.available = True
            logger.info(f"向量知识库初始化完成，存储路径: {self.persist_dir}")
        except Exception as e:
            logger.warning(f"向量知识库初始化失败，已降级: {e}")
    
    def _get_collection(self, blogger_id: int):
        """获取或创建博主对应的 collection"""
        if not self.available or self.client is None:
            return None
        collection_name = f"blogger_{blogger_id}"
        try:
            collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_fn
            )
        except Exception:
            collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_fn,
                metadata={"blogger_id": blogger_id}
            )
        return collection
    
    async def add_video_document(
        self,
        blogger_id: int,
        video_id: int,
        title: str,
        content: str,
        summary: str = ""
    ) -> bool:
        """添加视频文档（异步包装）"""
        if not self.available:
            return True
        import asyncio
        full_content = f"# {title}\n\n## 摘要\n{summary}\n\n## 全文\n{content}" if summary else content
        aweme_id = f"video_{video_id}"
        try:
            return await asyncio.to_thread(
                self.add_document,
                blogger_id,
                video_id,
                aweme_id,
                title,
                full_content
            )
        except Exception as e:
            logger.warning(f"添加文档失败（不影响主流程）: {e}")
            return True  # 返回True不阻塞主流程
    
    def add_document(
        self,
        blogger_id: int,
        video_id: int,
        aweme_id: str,
        title: str,
        content: str,
        metadata: Dict = None
    ) -> bool:
        if not self.available:
            return True
        try:
            collection = self._get_collection(blogger_id)
            if collection is None:
                return True
            paragraphs = self._split_text(content, max_length=500)
            
            if not paragraphs:
                return True
            
            ids = []
            documents = []
            metadatas = []
            
            for i, para in enumerate(paragraphs):
                doc_id = f"{aweme_id}_{i}"
                ids.append(doc_id)
                documents.append(para)
                
                meta = {
                    "video_id": video_id,
                    "aweme_id": aweme_id,
                    "title": title,
                    "paragraph_index": i,
                    "source": "douyin"
                }
                if metadata:
                    meta.update(metadata)
                metadatas.append(meta)
            
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            
            logger.info(f"文档添加成功: {aweme_id}，共 {len(paragraphs)} 个段落")
            return True
            
        except Exception as e:
            logger.warning(f"添加文档失败（不影响主流程）: {e}")
            return True
    
    def search(
        self,
        blogger_id: int,
        query: str,
        top_k: int = 5
    ) -> List[Dict]:
        if not self.available:
            return []
        try:
            collection = self._get_collection(blogger_id)
            if collection is None:
                return []
            
            results = collection.query(
                query_texts=[query],
                n_results=top_k
            )
            
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            
            search_results = []
            for i, doc in enumerate(documents):
                search_results.append({
                    "content": doc,
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "score": 1.0 - distances[i] if i < len(distances) else 0.0
                })
            
            return search_results
            
        except Exception as e:
            logger.warning(f"检索失败: {e}")
            return []
    
    def delete_by_video(self, blogger_id: int, aweme_id: str) -> bool:
        try:
            collection = self._get_collection(blogger_id)
            collection.delete(where={"aweme_id": aweme_id})
            return True
        except Exception as e:
            logger.warning(f"删除文档失败: {e}")
            return True
    
    def get_stats(self, blogger_id: int) -> Dict:
        try:
            collection = self._get_collection(blogger_id)
            count = collection.count()
            return {
                "blogger_id": blogger_id,
                "total_chunks": count,
                "collection_name": f"blogger_{blogger_id}"
            }
        except Exception as e:
            logger.warning(f"获取统计失败: {e}")
            return {"blogger_id": blogger_id, "total_chunks": 0}
    
    def _split_text(self, text: str, max_length: int = 500) -> List[str]:
        if not text:
            return []
        
        import re
        sentences = re.split(r'[。！？.!?\n]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return [text[:max_length]]
        
        paragraphs = []
        current = ""
        
        for sent in sentences:
            if len(current) + len(sent) + 1 <= max_length:
                if current:
                    current += "。" + sent
                else:
                    current = sent
            else:
                if current:
                    paragraphs.append(current)
                current = sent
        
        if current:
            paragraphs.append(current)
        
        return paragraphs


_service: Optional[KnowledgeBaseService] = None


def get_knowledge_base() -> KnowledgeBaseService:
    global _service
    if _service is None:
        _service = KnowledgeBaseService()
    return _service

get_kb_service = get_knowledge_base
