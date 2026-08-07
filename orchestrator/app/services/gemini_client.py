"""
Gemini API 客户端
"""
import httpx
import json
from typing import List, Dict, Optional
from app.core.config import settings
from app.core.logger import logger


class GeminiClient:
    """Gemini API 客户端（OpenAI 兼容格式）"""
    
    def __init__(self):
        self.base_url = settings.GEMINI_API_BASE_URL.rstrip("/")
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=180.0
        )
    
    async def close(self):
        await self.client.aclose()
    
    async def chat(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Optional[str]:
        """非流式对话（不限制token输出）"""
        try:
            url = f"{self.base_url}/v1/chat/completions"
            
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": False
            }
            # 不设置max_tokens，让API自动返回最大长度
            
            response = await self.client.post(url, json=payload)
            data = response.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"Gemini API 调用失败: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Gemini API 异常: {e}")
            return None
    
    async def analyze_video(self, title: str, transcript: str) -> Optional[Dict]:
        """
        完整深度解析单个视频内容（不是摘要！）
        
        返回结构：
        {
            "detailed_analysis": "完整深度解析正文（主体，1500-4000字）",
            "summary": "文末短摘要（150-300字）",
            "key_points": ["要点1", "要点2", ...],
            "topics": ["主题1", "主题2", ...],
            "takeaways": "金句和可操作建议",
            "outline": ["大纲1", "大纲2", ...]
        }
        """
        # 保留尽可能完整的文稿，避免截断导致解析变浅
        full_transcript = transcript or ""
        if len(full_transcript) > 50000:
            full_transcript = full_transcript[:50000] + "\n...(文稿过长已截断)"
        
        system_prompt = """你是专业的短视频内容完整深度解析专家。你的任务是产出「完整视频解析」，绝不是短摘要。

【硬性要求】
1. detailed_analysis 是唯一主体，必须是完整深度解析，禁止只写摘要、禁止空泛套话
2. detailed_analysis 长度必须 1500-4000 字（中文），覆盖文稿中几乎所有有效信息点
3. 必须逐段/逐观点展开：引用或转述原文关键表述，再解释含义、原因、适用场景、注意事项
4. 若文稿较短，也要结合标题与上下文做充分阐释，而不是敷衍成几百字摘要
5. summary 只是文末附属短摘要（150-300字），绝不能替代 detailed_analysis
6. 只输出 JSON，不要输出任何其他文字

JSON结构：
{
  "detailed_analysis": "Markdown完整深度解析，必须包含以下章节：\n### 一、内容概述\n（视频讲了什么、目标受众、核心命题）\n### 二、完整内容梳理\n（按文稿逻辑顺序，把视频内容完整重述+解释，不可跳过大段有效信息）\n### 三、核心观点深度剖析\n（每条观点：原文要点 → 深入解释 → 为什么重要 → 实例/推论）\n### 四、背景与上下文\n（行业/知识/剧情背景补充）\n### 五、方法论与实操步骤\n（可执行步骤、技巧、清单）\n### 六、关键细节与隐含信息\n（容易忽略但重要的细节）\n### 七、批判性思考与延伸\n（局限、适用边界、可延伸问题）",
  "key_points": ["核心要点1（30-80字详细描述）", "核心要点2", "...共5-12条"],
  "topics": ["从下列分类选择: 账号定位/内容创作/拍摄技巧/算法流量/粉丝运营/变现方法/个人成长/情感关系/知识科普/影视解说/其他"],
  "takeaways": "金句摘录 + 可直接执行建议，Markdown列表",
  "outline": ["内容大纲条目..."],
  "summary": "文末短摘要，150-300字，概括精华（不能替代detailed_analysis）"
}

全部内容使用中文。"""

        user_prompt = f"""视频标题：{title}

完整视频文字稿（请基于全文做完整解析，不要只提炼摘要）：
{full_transcript}

请输出完整深度解析JSON。再次强调：detailed_analysis 必须详实完整（1500字以上），summary 仅作短摘要放在字段末尾。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        result = await self.chat(messages, temperature=0.3)
        
        if not result:
            return None
        
        # 尝试解析 JSON（处理可能的 markdown 代码块包裹）
        try:
            # 去掉可能的 ```json ... ``` 包裹
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1] if "\n" in result else result[3:]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()
            
            data = json.loads(result)
            # 兜底：确保 detailed_analysis 存在
            if not data.get("detailed_analysis") and data.get("summary"):
                # 若只有 summary，将其视为解析正文
                data["detailed_analysis"] = data["summary"]
            return data
        except json.JSONDecodeError as e:
            logger.error(f"解析视频分析JSON失败: {e}, 内容: {result[:200]}")
            # 返回原始文本作为完整解析正文（而非短摘要）
            return {
                "detailed_analysis": result,
                "summary": result[:300] if len(result) > 300 else result,
                "key_points": [],
                "topics": [],
                "takeaways": "",
                "outline": []
            }
    
    async def generate_master_doc(
        self,
        blogger_name: str,
        blogger_signature: str,
        video_summaries: List[Dict]
    ) -> Optional[Dict]:
        """
        生成博主综合大文档 - 项目精髓！
        
        将所有视频的总结汇总成一份完整的知识体系文档
        
        video_summaries: [{"title": "视频标题", "summary": "总结", "key_points": [...], "topics": [...]}]
        
        返回：
        {
            "master_doc": "Markdown格式的综合大文档",
            "core_topics": [{"name": "主题名", "description": "描述", "videos_count": N}],
            "knowledge_map": "知识体系图谱描述",
            "key_insights": ["核心洞察1", "核心洞察2", ...]
        }
        """
        # 准备所有视频的深度解析 - 动态分配长度，优先保留完整解析而非短摘要
        num_videos = len(video_summaries)
        # 总输入约 80000 字符，尽量多保留每个视频的详细解析
        per_video_limit = min(3500, max(600, 80000 // max(num_videos, 1)))
        
        videos_text = ""
        for i, v in enumerate(video_summaries, 1):
            videos_text += f"\n\n### 视频{i}：{v.get('title', '未知标题')}\n"
            kp = v.get('key_points', [])[:8]
            videos_text += f"**核心要点**：{'; '.join(str(k)[:80] for k in kp)}\n"
            videos_text += f"**完整解析**：{v.get('summary', '')[:per_video_limit]}\n"
        
        system_prompt = f"""你是一个顶级的知识架构师和内容分析师。现在你需要分析抖音博主「{blogger_name}」的所有视频内容，为他构建一份完整、详尽的知识体系大文档。

博主简介：{blogger_signature}

你有 {len(video_summaries)} 个视频的内容摘要需要融合。请确保融合所有{len(video_summaries)}个视频的内容，不要遗漏任何一个。

请输出JSON格式（不要输出任何其他内容，只输出JSON）：

{{
  "master_doc": "Markdown格式的综合大文档，结构如下：\n\n# {blogger_name} 知识体系大全\n\n## 一、博主画像与内容定位\n（分析博主的定位、受众、核心价值主张，300字以上）\n\n## 二、核心知识体系\n（按照主题分类，每个主题下融合多个视频的内容，形成体系化的知识，每个主题300字以上）\n### 2.1 [主题分类1]\n- 核心观点（融合多个视频的视角）\n- 深度分析\n- 方法论与实操\n\n### 2.2 [主题分类2]\n...\n\n## 三、视频内容索引\n（按主题归类列出所有{len(video_summaries)}个视频，每个视频简要说明核心内容，格式：- 视频N：《标题》- 核心内容一句话）\n\n## 四、方法论总结\n（提炼出博主反复强调的核心方法论，系统化呈现，400字以上）\n\n## 五、金句与经典语录\n（收录博主最有价值的观点和金句，至少10条）\n\n## 六、行动指南\n（给学习者的系统性行动建议，分阶段，400字以上）\n\n## 七、内容创作特点\n（分析博主的内容风格、表达特点、成功要素，300字以上）\n\n## 八、综合摘要\n（最后用400字概括这位博主的全部内容精华）\n\n文档要求：\n- 必须融合所有{len(video_summaries)}个视频的内容，不能遗漏任何一个视频\n- 内容详实，有深度，不是简单罗列\n- 每个主题下要融合多个视频的视角\n- 视频内容索引部分必须列出所有{len(video_summaries)}个视频\n- 总长度5000-8000字",
  "core_topics": [
    {{"name": "主题名称", "description": "这个主题讲了什么", "video_count": 涉及视频数}}
  ],
  "knowledge_map": "用文字描述这个博主的知识体系结构",
  "key_insights": ["最有价值的5-8个核心洞察，是博主内容的精华"]
}}"""

        user_prompt = f"以下是该博主所有{len(video_summaries)}个视频的内容摘要，请基于这些内容生成综合知识大文档，确保每个视频都被融合进去：\n{videos_text}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        result = await self.chat(messages, temperature=0.4)
        
        if not result:
            return None
        
        try:
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1] if "\n" in result else result[3:]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()
            
            data = json.loads(result)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"解析综合大文档JSON失败: {e}")
            return {
                "master_doc": result,
                "core_topics": [],
                "knowledge_map": "",
                "key_insights": []
            }
    
    async def rag_answer(self, query: str, contexts: List[str], blogger_name: str = "") -> Optional[str]:
        """RAG 问答"""
        context_text = "\n\n---\n\n".join(contexts)
        
        system_prompt = f"你是一个学习助手，专门帮助用户学习抖音博主的内容。"
        if blogger_name:
            system_prompt += f"当前学习的博主是：{blogger_name}。"
        
        system_prompt += """
请基于提供的参考资料回答用户的问题。
- 如果参考资料中有答案，请结合资料内容回答，回答要详细、有条理
- 如果参考资料中没有相关信息，请如实告知
- 回答要清晰、结构化，可以用列表和小标题
- 可以适当引用原文中的关键表述
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"参考资料：\n\n{context_text}\n\n用户问题：{query}"}
        ]
        
        return await self.chat(messages, temperature=0.7)


_client: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
