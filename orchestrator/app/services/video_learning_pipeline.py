"""
视频完整学习流水线（六层）
1) 完整素材  2) 带时间戳 ASR  3) 关键帧多模态补全
4) 结构化深度解析  5) 知识原子化卡片  6) 验收门禁
大视频：按时间窗分段解析，再综合合成
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logger import logger


class VideoLearningPipeline:
    """单视频完整知识学习流水线"""

    def __init__(self, asr, gemini, frames_dir: str = "./data/frames"):
        self.asr = asr
        self.gemini = gemini
        self.frames_dir = Path(frames_dir)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        # 大视频分段：默认每段最多约 8 分钟口播文本 / 或按字数切
        self.chunk_chars = int(getattr(settings, "VIDEO_CHUNK_CHARS", 6000) or 6000)
        self.max_frames = int(getattr(settings, "VIDEO_MAX_FRAMES", 8) or 8)
        self.frame_interval = int(getattr(settings, "VIDEO_FRAME_INTERVAL", 8) or 8)

    async def extract_keyframes(self, video_path: str, aweme_id: str, duration: int = 0) -> List[Dict]:
        """用 ffmpeg 抽取关键帧（按间隔），返回 [{path, timestamp, b64}]"""
        out_dir = self.frames_dir / aweme_id
        out_dir.mkdir(parents=True, exist_ok=True)
        # 清理旧帧
        for old in out_dir.glob("frame_*.jpg"):
            try:
                old.unlink()
            except Exception:
                pass

        # 估算间隔：优先固定间隔，过长视频自动加大间隔，控制总帧数
        interval = max(3, self.frame_interval)
        if duration and duration > 0:
            interval = max(interval, int(math.ceil(duration / max(self.max_frames, 1))))

        pattern = str(out_dir / "frame_%03d.jpg")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-q:v", "5",
            "-frames:v", str(self.max_frames),
            pattern,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"抽帧失败: {stderr.decode('utf-8', errors='ignore')[:200]}")
                return []
        except Exception as e:
            logger.warning(f"抽帧异常: {e}")
            return []

        frames = []
        for i, fp in enumerate(sorted(out_dir.glob("frame_*.jpg"))[: self.max_frames]):
            try:
                raw = fp.read_bytes()
                # 限制单帧大小，过大则跳过（避免 API 超时）
                if len(raw) > 1_200_000:
                    continue
                b64 = base64.b64encode(raw).decode("ascii")
                ts = i * interval
                frames.append({
                    "path": str(fp),
                    "timestamp": ts,
                    "timestamp_label": self._fmt_ts(ts),
                    "b64": b64,
                    "mime": "image/jpeg",
                })
            except Exception as e:
                logger.debug(f"读取帧失败 {fp}: {e}")
        logger.info(f"抽取关键帧 {len(frames)} 张 (interval={interval}s)")
        return frames

    @staticmethod
    def _fmt_ts(seconds: float) -> str:
        s = int(max(0, seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    async def transcribe_timestamped(self, audio_path: str) -> Dict:
        """带时间戳 ASR；不可用时返回空 segments"""
        if hasattr(self.asr, "transcribe_with_timestamps"):
            return await self.asr.transcribe_with_timestamps(audio_path)
        text = await self.asr.transcribe(audio_path)
        return {
            "text": text or "",
            "segments": [{"start": 0, "end": 0, "text": text}] if text else [],
            "language": getattr(settings, "WHISPER_LANGUAGE", "zh"),
        }

    def build_timed_transcript(self, asr_result: Dict) -> str:
        parts = []
        for seg in asr_result.get("segments") or []:
            start = float(seg.get("start") or 0)
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            parts.append(f"[{self._fmt_ts(start)}] {text}")
        if parts:
            return "\n".join(parts)
        return (asr_result.get("text") or "").strip()

    def chunk_transcript(self, timed_transcript: str) -> List[Dict]:
        """大视频：按字符窗切段，尽量在时间戳行边界切开"""
        text = timed_transcript or ""
        if len(text) <= self.chunk_chars:
            return [{"index": 0, "text": text}]

        lines = text.splitlines()
        chunks, buf, idx = [], [], 0
        size = 0
        for line in lines:
            if size + len(line) + 1 > self.chunk_chars and buf:
                chunks.append({"index": idx, "text": "\n".join(buf)})
                idx += 1
                buf, size = [], 0
            buf.append(line)
            size += len(line) + 1
        if buf:
            chunks.append({"index": idx, "text": "\n".join(buf)})
        logger.info(f"大视频文稿切分为 {len(chunks)} 段")
        return chunks

    async def analyze_frames_vision(self, frames: List[Dict], title: str) -> List[Dict]:
        """多模态：把关键帧交给视觉模型做 OCR + 画面描述"""
        notes = []
        if not frames:
            return notes
        # 控制调用次数：最多 4 批，每批最多 2 帧，避免超时
        batch_size = 2
        selected = frames[:: max(1, len(frames) // min(len(frames), 6))][:6]
        for i in range(0, len(selected), batch_size):
            batch = selected[i : i + batch_size]
            try:
                note = await self.gemini.analyze_keyframes(title=title, frames=batch)
                if note:
                    notes.extend(note if isinstance(note, list) else [note])
            except Exception as e:
                logger.warning(f"关键帧视觉分析失败: {e}")
        return notes

    async def learn_video(
        self,
        *,
        title: str,
        desc: str,
        video_path: Optional[str],
        audio_path: Optional[str],
        duration: int = 0,
        aweme_id: str = "",
    ) -> Dict:
        """
        执行完整六层学习，返回：
        {
          timed_transcript, asr_segments, frame_notes,
          analysis, knowledge_cards, quality
        }
        """
        result = {
            "timed_transcript": "",
            "asr_segments": [],
            "frame_notes": [],
            "analysis": None,
            "knowledge_cards": [],
            "quality": {},
            "source_materials": {
                "has_video": bool(video_path),
                "has_audio": bool(audio_path),
                "has_desc": bool(desc),
            },
        }

        # --- Layer 2: 带时间戳 ASR ---
        asr_result = {"text": "", "segments": []}
        if audio_path:
            asr_result = await self.transcribe_timestamped(audio_path)
        timed = self.build_timed_transcript(asr_result)
        if not timed and desc:
            timed = f"[00:00] {desc}"
        if not timed and title:
            timed = f"[00:00] {title}"
        result["timed_transcript"] = timed
        result["asr_segments"] = asr_result.get("segments") or []

        # --- Layer 3: 关键帧多模态 ---
        frame_notes = []
        if video_path and Path(video_path).exists():
            frames = await self.extract_keyframes(video_path, aweme_id or "unknown", duration=duration)
            frame_notes = await self.analyze_frames_vision(frames, title=title)
        result["frame_notes"] = frame_notes

        vision_text = self._format_frame_notes(frame_notes)

        # --- Layer 4: 结构化深度解析（大视频分段） ---
        chunks = self.chunk_transcript(timed)
        chunk_analyses = []
        if len(chunks) == 1:
            analysis = await self.gemini.analyze_video_complete(
                title=title,
                timed_transcript=chunks[0]["text"],
                vision_notes=vision_text,
                desc=desc or "",
            )
            chunk_analyses.append(analysis)
        else:
            for ch in chunks:
                part = await self.gemini.analyze_video_complete(
                    title=f"{title}（分段 {ch['index'] + 1}/{len(chunks)}）",
                    timed_transcript=ch["text"],
                    vision_notes=vision_text if ch["index"] == 0 else "",
                    desc=desc or "",
                    partial=True,
                )
                if part:
                    chunk_analyses.append(part)
            analysis = await self.gemini.synthesize_chunk_analyses(
                title=title,
                chunk_analyses=chunk_analyses,
                vision_notes=vision_text,
            )

        result["analysis"] = analysis or {}

        # --- Layer 5: 知识原子化卡片 ---
        cards = []
        if analysis:
            cards = analysis.get("knowledge_cards") or []
            if not cards:
                cards = await self.gemini.extract_knowledge_cards(
                    title=title,
                    timed_transcript=timed,
                    analysis=analysis,
                    vision_notes=vision_text,
                ) or []
        result["knowledge_cards"] = cards if isinstance(cards, list) else []

        # --- Layer 6: 验收门禁 ---
        result["quality"] = self.evaluate_quality(
            timed_transcript=timed,
            segments=result["asr_segments"],
            analysis=result["analysis"] or {},
            cards=result["knowledge_cards"],
            frame_notes=frame_notes,
            has_video=bool(video_path),
            has_audio=bool(audio_path),
            duration=duration,
        )
        return result

    @staticmethod
    def _format_frame_notes(notes: List[Dict]) -> str:
        if not notes:
            return ""
        lines = []
        for n in notes:
            ts = n.get("timestamp_label") or n.get("timestamp") or "?"
            ocr = n.get("ocr_text") or ""
            desc = n.get("description") or n.get("scene") or ""
            knowledge = n.get("on_screen_knowledge") or ""
            lines.append(f"- [{ts}] 画面: {desc}")
            if ocr:
                lines.append(f"  OCR: {ocr}")
            if knowledge:
                lines.append(f"  屏上知识: {knowledge}")
        return "\n".join(lines)

    def evaluate_quality(
        self,
        *,
        timed_transcript: str,
        segments: List[Dict],
        analysis: Dict,
        cards: List[Dict],
        frame_notes: List[Dict],
        has_video: bool,
        has_audio: bool,
        duration: int,
    ) -> Dict:
        """验收：覆盖率/完整性打分（启发式，可解释）"""
        issues = []
        score = 100

        detailed = (analysis.get("detailed_analysis") or "") if analysis else ""
        transcript_len = len(timed_transcript or "")
        has_ts = bool(re.search(r"\[\d{1,2}:\d{2}\]", timed_transcript or ""))
        seg_n = len(segments or [])

        # 素材
        if not has_video:
            score -= 15
            issues.append("缺少本地视频文件")
        if not has_audio:
            score -= 15
            issues.append("缺少音频/ASR 源")

        # 转写
        if transcript_len < 80:
            score -= 25
            issues.append("转写过短，可能未覆盖口播")
        elif transcript_len < 300:
            score -= 10
            issues.append("转写偏短")
        if not has_ts:
            score -= 10
            issues.append("缺少时间戳转写")
        if duration and duration > 60 and seg_n < 3:
            score -= 10
            issues.append("长视频分段过少")

        # 多模态
        if has_video and not frame_notes:
            score -= 10
            issues.append("未获得关键帧视觉/OCR 补全")

        # 解析深度
        if len(detailed) < 800:
            score -= 20
            issues.append("深度解析过短（疑似摘要）")
        elif len(detailed) < 1500:
            score -= 8
            issues.append("深度解析偏短")

        # 知识卡片
        if len(cards) < 3:
            score -= 10
            issues.append("知识卡片不足（<3）")

        # 覆盖率估算：解析字数 / 文稿字数（粗估）
        coverage = 0.0
        if transcript_len > 0:
            coverage = min(1.5, len(detailed) / max(transcript_len, 1))
        # 文稿很短时用解析绝对长度判断
        coverage_ok = (transcript_len >= 200 and coverage >= 0.9) or (
            transcript_len < 200 and len(detailed) >= 1200
        )
        if not coverage_ok:
            score -= 10
            issues.append("解析对文稿覆盖可能不足")

        score = max(0, min(100, score))
        passed = score >= 70 and len(detailed) >= 800 and len(cards) >= 3

        return {
            "score": score,
            "passed": passed,
            "coverage_ratio": round(coverage, 3),
            "transcript_chars": transcript_len,
            "analysis_chars": len(detailed),
            "segments": seg_n,
            "frames_analyzed": len(frame_notes or []),
            "knowledge_cards": len(cards or []),
            "has_timestamps": has_ts,
            "issues": issues,
            "checklist": {
                "can_answer_what": len(detailed) >= 500,
                "can_answer_how": bool(analysis.get("takeaways")) or ("步骤" in detailed),
                "can_answer_why": ("为什么" in detailed) or ("原因" in detailed) or ("因为" in detailed),
                "has_boundaries": ("边界" in detailed) or ("局限" in detailed) or ("适用" in detailed),
                "cards_with_timestamp": sum(1 for c in (cards or []) if c.get("timestamp") or c.get("time_range")),
            },
        }


_pipeline = None


def get_video_learning_pipeline(asr=None, gemini=None):
    global _pipeline
    if _pipeline is None:
        if asr is None or gemini is None:
            from app.services.asr_service import get_asr_service
            from app.services.gemini_client import get_gemini_client
            asr = asr or get_asr_service()
            gemini = gemini or get_gemini_client()
        frames = str(Path(getattr(settings, "VIDEO_STORAGE_PATH", "./data/videos")).parent / "frames")
        _pipeline = VideoLearningPipeline(asr=asr, gemini=gemini, frames_dir=frames)
    return _pipeline
