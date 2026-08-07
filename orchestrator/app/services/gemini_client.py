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
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """非流式对话（不限制token输出）。支持多模态 content 数组。"""
        try:
            url = f"{self.base_url}/v1/chat/completions"
            
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": False
            }
            
            client = self.client
            if timeout:
                client = httpx.AsyncClient(headers=self.headers, timeout=timeout)
            try:
                response = await client.post(url, json=payload)
                data = response.json()
            finally:
                if timeout:
                    await client.aclose()
            
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"Gemini API 调用失败: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Gemini API 异常: {e}")
            return None
    
    def _parse_json_content(self, result: str) -> Optional[Dict]:
        if not result:
            return None
        try:
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1] if "\n" in result else result[3:]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()
            # 容错：截取首尾大括号
            if not result.startswith("{"):
                l = result.find("{")
                r = result.rfind("}")
                if l >= 0 and r > l:
                    result = result[l : r + 1]
            return json.loads(result)
        except Exception as e:
            logger.error(f"JSON解析失败: {e}, 内容: {(result or '')[:200]}")
            return None

    async def analyze_video(self, title: str, transcript: str) -> Optional[Dict]:
        """兼容旧接口：转调完整解析"""
        return await self.analyze_video_complete(
            title=title,
            timed_transcript=transcript or "",
            vision_notes="",
            desc="",
        )

    async def analyze_video_complete(
        self,
        title: str,
        timed_transcript: str,
        vision_notes: str = "",
        desc: str = "",
        partial: bool = False,
    ) -> Optional[Dict]:
        """
        完整深度解析（六层中的结构化解析）
        输入是「带时间戳完整文稿/描述」，不是直接整段上传大视频文件。
        大视频先完整下载并切片 ASR，再结构化解析；不抽帧。
        """
        full_transcript = timed_transcript or desc or ""
        if len(full_transcript) > 60000:
            full_transcript = full_transcript[:60000] + "\n...(文稿过长已截断)"

        length_req = "800-2000字" if partial else "1500-4000字"
        system_prompt = f"""你是专业的短视频「完整知识学习」解析专家。目标是让学习者看完你的输出后，等于把视频知识学透，而不是只看摘要。

【硬性要求】
1. detailed_analysis 必须是完整深度解析（{length_req}），禁止只写摘要
2. 以「带时间戳完整文稿/描述」为主；无口播时仍需基于标题、描述与内容语境做深度结构化解析
3. 有时间戳则引用，如 [01:23]
4. 必须产出 knowledge_cards（知识原子卡片）至少 5 张，尽量带 timestamp
5. 只输出 JSON（不要抽帧、不要依赖画面截图）

JSON结构：
{{
  "detailed_analysis": "Markdown完整解析，含：\\n### 一、内容概述\\n### 二、完整内容梳理（按时间线）\\n### 三、核心观点深度剖析\\n### 四、方法论与实操步骤\\n### 五、术语表\\n### 六、前提假设与适用边界\\n### 七、创作手法/表达技巧\\n### 八、金句与可执行动作\\n### 九、批判性思考",
  "key_points": ["要点..."],
  "topics": ["主题分类"],
  "takeaways": "金句+可执行建议 Markdown 列表",
  "outline": ["大纲"],
  "knowledge_cards": [
    {{
      "type": "concept|step|formula|case|pitfall|quote",
      "title": "卡片标题",
      "content": "卡片正文",
      "timestamp": "mm:ss",
      "time_range": "mm:ss-mm:ss",
      "source": "speech|desc|both"
    }}
  ],
  "summary": "150-300字短摘要（附属，不能替代 detailed_analysis）"
}}"""

        user_prompt = f"""视频标题：{title}

视频描述：{desc or '无'}

带时间戳完整文稿（口播稀少时可主要依据标题与描述）：
{full_transcript or '（无口播文稿）'}

补充说明：{vision_notes or '无抽帧；请基于文稿与描述完成完整学习解析。'}

请输出完整知识学习 JSON。"""

        result = await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
        )
        data = self._parse_json_content(result or "")
        if data:
            if not data.get("detailed_analysis") and data.get("summary"):
                data["detailed_analysis"] = data["summary"]
            if not isinstance(data.get("knowledge_cards"), list):
                data["knowledge_cards"] = []
            return data
        if result:
            return {
                "detailed_analysis": result,
                "summary": result[:300],
                "key_points": [],
                "topics": [],
                "takeaways": "",
                "outline": [],
                "knowledge_cards": [],
            }
        return None

    async def synthesize_chunk_analyses(
        self,
        title: str,
        chunk_analyses: List[Dict],
        vision_notes: str = "",
    ) -> Optional[Dict]:
        """大视频：把分段解析综合成最终完整解析"""
        if not chunk_analyses:
            return None
        if len(chunk_analyses) == 1:
            return chunk_analyses[0]

        parts = []
        all_cards = []
        for i, ch in enumerate(chunk_analyses, 1):
            if not ch:
                continue
            parts.append(
                f"## 分段{i}\n{(ch.get('detailed_analysis') or '')[:3500]}\n"
                f"要点: {ch.get('key_points')}\n"
            )
            cards = ch.get("knowledge_cards") or []
            if isinstance(cards, list):
                all_cards.extend(cards)

        system_prompt = """你是知识架构师。请把同一视频的多个分段深度解析，综合成一份无重复、按时间线完整的最终解析 JSON。
保留并去重 knowledge_cards。只输出 JSON，结构与单段解析相同。"""
        user_prompt = f"""视频标题：{title}

画面笔记：
{vision_notes or '无'}

分段解析：
{chr(10).join(parts)[:50000]}

请输出最终综合 JSON。"""
        result = await self.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2,
        )
        data = self._parse_json_content(result or "")
        if data:
            cards = data.get("knowledge_cards") or []
            if not cards:
                data["knowledge_cards"] = all_cards[:40]
            return data
        # 兜底拼接
        merged = "\n\n".join(
            (c.get("detailed_analysis") or "") for c in chunk_analyses if c
        )
        return {
            "detailed_analysis": merged,
            "summary": (chunk_analyses[0] or {}).get("summary", ""),
            "key_points": sum((c.get("key_points") or [] for c in chunk_analyses if c), [])[:12],
            "topics": (chunk_analyses[0] or {}).get("topics") or [],
            "takeaways": "\n".join(
                str((c or {}).get("takeaways") or "") for c in chunk_analyses
            ),
            "outline": sum((c.get("outline") or [] for c in chunk_analyses if c), [])[:20],
            "knowledge_cards": all_cards[:40],
        }

    async def analyze_keyframes(self, title: str, frames: List[Dict]) -> List[Dict]:
        """多模态关键帧分析：OCR + 画面知识。失败则返回空。"""
        if not frames:
            return []
        content = [
            {
                "type": "text",
                "text": (
                    f"视频标题：{title}\n"
                    "请分析下列关键帧。对每一帧输出 OCR 文字、画面描述、屏上知识。"
                    "只输出 JSON 数组："
                    '[{"timestamp_label":"mm:ss","ocr_text":"...","description":"...","on_screen_knowledge":"..."}]'
                ),
            }
        ]
        for fr in frames:
            label = fr.get("timestamp_label") or str(fr.get("timestamp") or "")
            content.append({"type": "text", "text": f"关键帧时间 {label}"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{fr.get('mime', 'image/jpeg')};base64,{fr.get('b64', '')}"
                    },
                }
            )

        result = await self.chat(
            [{"role": "user", "content": content}],
            temperature=0.2,
            timeout=90.0,
        )
        if not result:
            return []
        # 解析数组或对象
        try:
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            l, r = text.find("["), text.rfind("]")
            if l >= 0 and r > l:
                arr = json.loads(text[l : r + 1])
                if isinstance(arr, list):
                    # 回填 timestamp
                    for i, item in enumerate(arr):
                        if not item.get("timestamp_label") and i < len(frames):
                            item["timestamp_label"] = frames[i].get("timestamp_label")
                            item["timestamp"] = frames[i].get("timestamp")
                    return arr
        except Exception as e:
            logger.warning(f"关键帧结果解析失败: {e}")
        # 降级：把原始文本当作一帧描述
        return [{
            "timestamp_label": frames[0].get("timestamp_label"),
            "timestamp": frames[0].get("timestamp"),
            "ocr_text": "",
            "description": (result or "")[:500],
            "on_screen_knowledge": "",
        }]

    async def extract_knowledge_cards(
        self,
        title: str,
        timed_transcript: str,
        analysis: Dict,
        vision_notes: str = "",
    ) -> List[Dict]:
        """单独抽取知识卡片（当主解析未带 cards 时）"""
        system_prompt = """从视频学习材料中抽取可检索知识卡片。只输出 JSON 数组。
每项: {"type":"concept|step|formula|case|pitfall|quote","title":"...","content":"...","timestamp":"mm:ss","time_range":"mm:ss-mm:ss","source":"speech|screen|both"}
至少 5 张，最多 20 张。"""
        user_prompt = f"""标题：{title}

文稿：
{(timed_transcript or '')[:12000]}

解析：
{(analysis.get('detailed_analysis') or '')[:8000]}

画面笔记：
{vision_notes or '无'}
"""
        result = await self.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2,
        )
        if not result:
            return []
        try:
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
            l, r = text.find("["), text.rfind("]")
            if l >= 0 and r > l:
                arr = json.loads(text[l : r + 1])
                return arr if isinstance(arr, list) else []
        except Exception:
            return []
        return []
    
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
