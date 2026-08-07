"""
语音识别服务
优先使用 faster-whisper，如果不可用则提供备用方案
"""
import os
# 设置HuggingFace镜像端点（解决SSL下载失败问题）
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SSL_VERIFICATION'] = '1'
from pathlib import Path
from typing import Optional
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
        """
        转录音频文件为文字
        
        Args:
            audio_path: 音频文件路径
        
        Returns:
            转录文本
        """
        if not self.available or not self.model:
            logger.warning("ASR不可用，返回空文本（将使用视频描述）")
            return ""
        
        try:
            logger.info(f"开始语音识别: {audio_path}")
            
            # 使用 asyncio.to_thread 避免阻塞事件循环
            import asyncio
            segments, info = await asyncio.to_thread(
                self.model.transcribe,
                audio_path,
                language=self.language,
                beam_size=5,
                vad_filter=True
            )
            
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())
            
            full_text = " ".join(text_parts)
            logger.info(f"语音识别完成，文本长度: {len(full_text)} 字符")
            
            return full_text
            
        except Exception as e:
            logger.error(f"语音识别失败: {e}")
            return ""


_service: Optional[ASRService] = None


def get_asr_service() -> ASRService:
    global _service
    if _service is None:
        _service = ASRService()
    return _service
