"""
Dify API 客户端
对接 Dify (130k+ star) - 开源 LLM 应用开发平台
GitHub: https://github.com/langgenius/dify
"""
import httpx
from typing import List, Dict, Optional
from app.core.config import settings
from app.core.logger import logger


class DifyClient:
    """Dify API 客户端"""
    
    def __init__(self):
        self.base_url = settings.DIFY_API_BASE_URL.rstrip("/")
        self.api_key = settings.DIFY_API_KEY
        self.dataset_id = settings.DIFY_DATASET_ID
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=120.0
        )
    
    async def close(self):
        await self.client.aclose()
    
    # ========== 知识库相关 API ==========
    
    async def create_document_by_text(
        self,
        name: str,
        text: str,
        dataset_id: str = None,
        metadata: Dict = None
    ) -> Optional[Dict]:
        """
        通过文本创建文档（添加到知识库）
        API: POST /v1/datasets/{dataset_id}/document/create_by_text
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            logger.warning("未配置 DIFY_DATASET_ID")
            return None
        
        try:
            url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create_by_text"
            
            payload = {
                "name": name,
                "text": text,
                "indexing_technique": "high_quality",
                "process_rule": {
                    "rules": {
                        "pre_processing_rules": [
                            {"id": "remove_extra_spaces", "enabled": True},
                            {"id": "remove_urls_emails", "enabled": False}
                        ],
                        "segmentation": {
                            "separator": "。",
                            "max_tokens": 500
                        }
                    },
                    "mode": "custom"
                }
            }
            
            if metadata:
                payload["metadata"] = metadata
            
            response = await self.client.post(url, json=payload)
            data = response.json()
            
            if "document" in data:
                logger.info(f"文档创建成功: {name}")
                return data
            else:
                logger.warning(f"文档创建失败: {data.get('message', '未知错误')}")
                return None
                
        except Exception as e:
            logger.error(f"创建文档异常: {e}")
            return None
    
    async def create_document_by_file(
        self,
        file_path: str,
        dataset_id: str = None,
        metadata: Dict = None
    ) -> Optional[Dict]:
        """
        通过文件创建文档
        API: POST /v1/datasets/{dataset_id}/document/create_by_file
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            return None
        
        try:
            import os
            filename = os.path.basename(file_path)
            
            url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create_by_file"
            
            with open(file_path, "rb") as f:
                files = {"file": (filename, f)}
                data = {
                    "indexing_technique": "high_quality",
                    "process_rule": '{"mode":"custom","rules":{"pre_processing_rules":[{"id":"remove_extra_spaces","enabled":true}],"segmentation":{"separator":"。","max_tokens":500}}}'
                }
                
                response = await self.client.post(url, files=files, data=data)
                result = response.json()
                
                if "document" in result:
                    logger.info(f"文件文档创建成功: {filename}")
                    return result
                else:
                    logger.warning(f"文件文档创建失败: {result.get('message')}")
                    return None
                    
        except Exception as e:
            logger.error(f"创建文件文档异常: {e}")
            return None
    
    async def update_document(
        self,
        document_id: str,
        name: str = None,
        text: str = None,
        dataset_id: str = None
    ) -> Optional[Dict]:
        """
        更新文档
        API: POST /v1/datasets/{dataset_id}/documents/{document_id}/update_by_text
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            return None
        
        try:
            url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}/update_by_text"
            
            payload = {}
            if name:
                payload["name"] = name
            if text:
                payload["text"] = text
            
            response = await self.client.post(url, json=payload)
            return response.json()
            
        except Exception as e:
            logger.error(f"更新文档异常: {e}")
            return None
    
    async def delete_document(self, document_id: str, dataset_id: str = None) -> bool:
        """
        删除文档
        API: DELETE /v1/datasets/{dataset_id}/documents/{document_id}
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            return False
        
        try:
            url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
            response = await self.client.delete(url)
            
            if response.status_code == 200:
                return True
            return False
            
        except Exception as e:
            logger.error(f"删除文档异常: {e}")
            return False
    
    async def list_documents(
        self,
        dataset_id: str = None,
        page: int = 1,
        limit: int = 25,
        keyword: str = ""
    ) -> Optional[Dict]:
        """
        获取文档列表
        API: GET /v1/datasets/{dataset_id}/documents
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            return None
        
        try:
            url = f"{self.base_url}/v1/datasets/{dataset_id}/documents"
            params = {"page": page, "limit": limit, "keyword": keyword}
            
            response = await self.client.get(url, params=params)
            return response.json()
            
        except Exception as e:
            logger.error(f"获取文档列表异常: {e}")
            return None
    
    # ========== 对话相关 API ==========
    
    async def chat_message(
        self,
        query: str,
        user_id: str = "default-user",
        conversation_id: str = None,
        inputs: Dict = None,
        response_mode: str = "streaming"
    ) -> Optional[Dict]:
        """
        发送对话消息
        API: POST /v1/chat-messages
        """
        try:
            url = f"{self.base_url}/v1/chat-messages"
            
            payload = {
                "inputs": inputs or {},
                "query": query,
                "response_mode": response_mode,
                "conversation_id": conversation_id or "",
                "user": user_id,
            }
            
            response = await self.client.post(url, json=payload)
            
            if response_mode == "blocking":
                return response.json()
            else:
                # 流式响应，返回原始响应
                return response
                
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return None
    
    # ========== 知识库检索 API ==========
    
    async def retrieve(
        self,
        query: str,
        dataset_id: str = None,
        retrieval_setting: Dict = None
    ) -> Optional[Dict]:
        """
        检索知识库
        API: POST /v1/datasets/{dataset_id}/retrieve
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            return None
        
        try:
            url = f"{self.base_url}/v1/datasets/{dataset_id}/retrieve"
            
            payload = {
                "query": query,
                "retrieval_setting": retrieval_setting or {
                    "top_k": 5,
                    "score_threshold": 0.5
                }
            }
            
            response = await self.client.post(url, json=payload)
            return response.json()
            
        except Exception as e:
            logger.error(f"检索知识库异常: {e}")
            return None
    
    # ========== 数据集管理 API ==========
    
    async def create_dataset(self, name: str) -> Optional[Dict]:
        """
        创建知识库
        API: POST /v1/datasets
        """
        try:
            url = f"{self.base_url}/v1/datasets"
            payload = {"name": name, "permission": "only_me"}
            
            response = await self.client.post(url, json=payload)
            data = response.json()
            
            if "id" in data:
                logger.info(f"知识库创建成功: {name}")
                return data
            return None
            
        except Exception as e:
            logger.error(f"创建知识库异常: {e}")
            return None
    
    async def list_datasets(self, page: int = 1, limit: int = 25) -> Optional[Dict]:
        """
        获取知识库列表
        API: GET /v1/datasets
        """
        try:
            url = f"{self.base_url}/v1/datasets"
            params = {"page": page, "limit": limit}
            
            response = await self.client.get(url, params=params)
            return response.json()
            
        except Exception as e:
            logger.error(f"获取知识库列表异常: {e}")
            return None
    
    async def get_dataset_stats(self, dataset_id: str = None) -> Optional[Dict]:
        """
        获取知识库统计
        """
        dataset_id = dataset_id or self.dataset_id
        if not dataset_id:
            return None
        
        try:
            # 获取文档列表来统计
            result = await self.list_documents(dataset_id=dataset_id, limit=1)
            if result:
                return {
                    "total": result.get("total", 0),
                    "page": result.get("page", 1),
                    "limit": result.get("limit", 25)
                }
            return None
            
        except Exception as e:
            logger.error(f"获取知识库统计异常: {e}")
            return None


# 单例
_client: Optional[DifyClient] = None


def get_dify_client() -> DifyClient:
    global _client
    if _client is None:
        _client = DifyClient()
    return _client
