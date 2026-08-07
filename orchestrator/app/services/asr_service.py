"""
语音识别服务
优先使用 faster-whisper，返回带时间戳分段；不可用则降级。
"""
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SSL_VERIFICATION'] = '1'
from pathlib import Path
from typing import Optional, Dict, List
from app.core.config import settings
from app.core.logger import logger


class ASRService:
    """语音识别服务"""
    
    def __init__(self):
        self.model = None
        self.model_size = settings.WHISPER_MODEL_SIZE
        self.device = settings.WHISPER_DEVICE
        self.compute_type = settings.WHISPER_COMPUTE_TYPE
        self.language = settings.WHISPER_LANGUAGE
        self.available = False
        self._init_model()
    
    def _init_model(self):
        """初始化faster-whisper模型"""
        try:
            from faster_whisper import WhisperModel
            logger.info(f"正在加载 faster-whisper 模型: {self.model_size}")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )
            self.available = True
            logger.info("faster-whisper 模型加载成功")
        except Exception as e:
            logger.warning(f"faster-whisper 初始化失败: {e}")
            logger.warning("将使用备用方案：直接使用视频描述文本")
            self.available = False
    
    async def transcribe(self, audio_path: str) -> str:
        """兼容旧接口：只返回纯文本"""
        result = await self.transcribe_with_timestamps(audio_path)
        return result.get("text", "")
    
    async def transcribe_with_timestamps(self, audio_path: str) -> Dict:
        """
        带时间戳转写
        返回: {text, segments:[{start,end,text}], language}
        """
        if not self.available or not self.model:
            logger.warning("ASR不可用，返回空文本（将使用视频描述）")
            return {"text": "", "segments": [], "language": self.language}
        
        try:
            logger.info(f"开始语音识别(带时间戳): {audio_path}")
            import asyncio
            
            def _run():
                segments_iter, info = self.model.transcribe(
                    audio_path,
                    language=self.language,
                    beam_size=5,
                    vad_filter=True,
                    word_timestamps=False,
                )
                segments = []
                texts = []
                for seg in segments_iter:
                    item = {
                        "start": round(float(seg.start or 0), 2),
                        "end": round(float(seg.end or 0), 2),
                        "text": (seg.text or "").strip(),
                    }
                    if item["text"]:
                        segments.append(item)
                        texts.append(item["text"])
                return {
                    "text": " ".join(texts),
                    "segments": segments,
                    "language": getattr(info, "language", self.language),
                }
            
            result = await asyncio.to_thread(_run)
            logger.info(
                f"语音识别完成: {len(result.get('text',''))} 字, "
                f"{len(result.get('segments') or [])} 段"
            )
            return result
        except Exception as e:
            logger.error(f"语音识别失败: {e}")
            return {"text": "", "segments": [], "language": self.language}


_service: Optional[ASRService] = None


def get_asr_service() -> ASRService:
    global _service
    if _service is None:
        _service = ASRService()
    return _service
