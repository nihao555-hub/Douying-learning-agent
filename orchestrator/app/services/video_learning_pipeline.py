"""
视频完整学习流水线（不要抽帧）
1) 下载完整视频素材
2) 完整音频提取；大视频按时间切片做完整 ASR（带时间戳）并拼接
3) 结构化深度解析（大文稿再按字数分段综合）
4) 知识原子化卡片
5) 验收门禁

说明：不把整段超大视频一次性塞给 LLM；但对学习者而言覆盖「完整视频口播内容」。
"""
from __future__ import annotations

import asyncio
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings
from app.core.logger import logger


class VideoLearningPipeline:
    """单视频完整知识学习流水线（切片，不抽帧）"""

    def __init__(self, asr, gemini, slices_dir: str = "./data/slices"):
        self.asr = asr
        self.gemini = gemini
        self.slices_dir = Path(slices_dir)
        self.slices_dir.mkdir(parents=True, exist_ok=True)
        # 文稿送给 LLM 时的切段字数
        self.chunk_chars = int(getattr(settings, "VIDEO_CHUNK_CHARS", 8000) or 8000)
        # 大视频/音频时间切片长度（秒），用于完整 ASR
        self.slice_seconds = int(getattr(settings, "VIDEO_SLICE_SECONDS", 120) or 120)

    @staticmethod
    def _fmt_ts(seconds: float) -> str:
        s = int(max(0, seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    async def _probe_duration(self, media_path: str) -> float:
        """用 ffprobe 获取时长（秒）"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            media_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, _ = await proc.communicate()
            return float((out or b"0").decode().strip() or 0)
        except Exception:
            return 0.0

    async def slice_audio_for_asr(self, audio_path: str, aweme_id: str, duration: float = 0) -> List[Dict]:
        """
        将完整音频按时间切片，返回 [{path, start, end}]。
        短音频不切片，直接返回原文件。
        """
        if not audio_path or not Path(audio_path).exists():
            return []

        dur = duration or await self._probe_duration(audio_path)
        if dur <= 0:
            return [{"path": audio_path, "start": 0.0, "end": 0.0}]

        # 不超过一片则不切
        if dur <= self.slice_seconds * 1.2:
            return [{"path": audio_path, "start": 0.0, "end": dur}]

        out_dir = self.slices_dir / aweme_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("slice_*.wav"):
            try:
                old.unlink()
            except Exception:
                pass

        slices = []
        n = int(math.ceil(dur / self.slice_seconds))
        logger.info(f"大视频音频切片: duration={dur:.1f}s -> {n} 片 (每片{self.slice_seconds}s)")

        for i in range(n):
            start = i * self.slice_seconds
            length = min(self.slice_seconds, max(0.0, dur - start))
            if length < 0.5:
                break
            out = out_dir / f"slice_{i:03d}.wav"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-t", str(length),
                "-i", audio_path,
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(out),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0 or not out.exists():
                logger.warning(f"切片失败 #{i}: {stderr.decode('utf-8', errors='ignore')[:160]}")
                continue
            slices.append({"path": str(out), "start": float(start), "end": float(start + length)})

        return slices or [{"path": audio_path, "start": 0.0, "end": dur}]

    async def transcribe_full_video(self, audio_path: str, aweme_id: str, duration: int = 0) -> Dict:
        """
        完整视频 ASR：大视频先切片，逐片转写后按时间偏移合并。
        """
        empty = {"text": "", "segments": [], "language": getattr(settings, "WHISPER_LANGUAGE", "zh")}
        if not audio_path:
            return empty

        slices = await self.slice_audio_for_asr(audio_path, aweme_id or "unknown", duration=float(duration or 0))
        all_segments: List[Dict] = []
        texts: List[str] = []

        for idx, sl in enumerate(slices):
            offset = float(sl.get("start") or 0)
            if hasattr(self.asr, "transcribe_with_timestamps"):
                part = await self.asr.transcribe_with_timestamps(sl["path"])
            else:
                t = await self.asr.transcribe(sl["path"])
                part = {"text": t or "", "segments": [{"start": 0, "end": 0, "text": t}] if t else []}

            segs = part.get("segments") or []
            if not segs and part.get("text"):
                segs = [{"start": 0, "end": 0, "text": part["text"]}]

            for seg in segs:
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                item = {
                    "start": round(float(seg.get("start") or 0) + offset, 2),
                    "end": round(float(seg.get("end") or 0) + offset, 2),
                    "text": text,
                }
                all_segments.append(item)
                texts.append(text)

            logger.info(
                f"ASR 切片 {idx + 1}/{len(slices)} 完成: +{len(segs)} 段, offset={offset:.1f}s"
            )

        return {
            "text": " ".join(texts),
            "segments": all_segments,
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
        """大文稿按字符窗切段，供 LLM 深度解析（仍覆盖完整内容）"""
        text = timed_transcript or ""
        if len(text) <= self.chunk_chars:
            return [{"index": 0, "text": text}]

        lines = text.splitlines()
        chunks, buf, idx, size = [], [], 0, 0
        for line in lines:
            if size + len(line) + 1 > self.chunk_chars and buf:
                chunks.append({"index": idx, "text": "\n".join(buf)})
                idx += 1
                buf, size = [], 0
            buf.append(line)
            size += len(line) + 1
        if buf:
            chunks.append({"index": idx, "text": "\n".join(buf)})
        logger.info(f"完整文稿按字数分为 {len(chunks)} 段给 LLM")
        return chunks

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
        完整学习（无抽帧）：
        完整素材 → 切片完整 ASR → 深度解析 → 知识卡片 → 验收
        """
        result = {
            "timed_transcript": "",
            "asr_segments": [],
            "frame_notes": [],  # 兼容字段，固定为空（已取消抽帧）
            "analysis": None,
            "knowledge_cards": [],
            "quality": {},
            "source_materials": {
                "has_video": bool(video_path and Path(str(video_path)).exists()),
                "has_audio": bool(audio_path and Path(str(audio_path)).exists()),
                "has_desc": bool(desc),
            },
        }

        # 完整 ASR（大视频切片）
        asr_result = {"text": "", "segments": []}
        if audio_path and Path(audio_path).exists():
            asr_result = await self.transcribe_full_video(
                audio_path=audio_path,
                aweme_id=aweme_id or "unknown",
                duration=duration,
            )

        timed = self.build_timed_transcript(asr_result)
        if not timed and desc:
            timed = f"[00:00] {desc}"
        if not timed and title:
            timed = f"[00:00] {title}"

        result["timed_transcript"] = timed
        result["asr_segments"] = asr_result.get("segments") or []

        # 结构化深度解析（覆盖完整文稿；过长则分段再综合）
        chunks = self.chunk_transcript(timed)
        if len(chunks) == 1:
            analysis = await self.gemini.analyze_video_complete(
                title=title,
                timed_transcript=chunks[0]["text"],
                vision_notes="",  # 不使用抽帧
                desc=desc or "",
            )
        else:
            chunk_analyses = []
            for ch in chunks:
                part = await self.gemini.analyze_video_complete(
                    title=f"{title}（完整视频分段 {ch['index'] + 1}/{len(chunks)}）",
                    timed_transcript=ch["text"],
                    vision_notes="",
                    desc=desc or "",
                    partial=True,
                )
                if part:
                    chunk_analyses.append(part)
            analysis = await self.gemini.synthesize_chunk_analyses(
                title=title,
                chunk_analyses=chunk_analyses,
                vision_notes="",
            )

        result["analysis"] = analysis or {}

        cards = []
        if analysis:
            cards = analysis.get("knowledge_cards") or []
            if not cards:
                cards = await self.gemini.extract_knowledge_cards(
                    title=title,
                    timed_transcript=timed,
                    analysis=analysis,
                    vision_notes="",
                ) or []
        cards = cards if isinstance(cards, list) else []
        result["knowledge_cards"] = self._ensure_min_cards(
            cards=cards,
            analysis=result["analysis"] or {},
            title=title,
            timed_transcript=timed,
        )

        result["quality"] = self.evaluate_quality(
            timed_transcript=timed,
            segments=result["asr_segments"],
            analysis=result["analysis"] or {},
            cards=result["knowledge_cards"],
            has_video=result["source_materials"]["has_video"],
            has_audio=result["source_materials"]["has_audio"],
            duration=duration,
        )
        return result

    def _ensure_min_cards(
        self,
        *,
        cards: List[Dict],
        analysis: Dict,
        title: str,
        timed_transcript: str,
        min_cards: int = 3,
    ) -> List[Dict]:
        """卡片不足时用要点/主题/金句兜底，保证验收可检索原子数。"""
        out: List[Dict] = []
        seen = set()
        for c in cards or []:
            if not isinstance(c, dict):
                continue
            key = (str(c.get("title") or "").strip(), str(c.get("content") or "").strip()[:80])
            if not key[0] and not key[1]:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(c)

        def _add(card_type: str, card_title: str, content: str, source: str = "desc"):
            t = (card_title or "").strip()[:80]
            body = (content or "").strip()
            if not t or not body:
                return
            key = (t, body[:80])
            if key in seen:
                return
            seen.add(key)
            out.append(
                {
                    "type": card_type,
                    "title": t,
                    "content": body[:500],
                    "timestamp": "00:00",
                    "time_range": "00:00-00:00",
                    "source": source,
                }
            )

        if len(out) < min_cards:
            for kp in analysis.get("key_points") or []:
                if isinstance(kp, dict):
                    _add(
                        "concept",
                        str(kp.get("title") or kp.get("name") or "要点"),
                        str(kp.get("content") or kp),
                    )
                else:
                    text = str(kp).strip()
                    _add("concept", text[:40] or "要点", text)
                if len(out) >= max(min_cards, 5):
                    break

        if len(out) < min_cards:
            for topic in analysis.get("topics") or []:
                _add("concept", f"主题：{topic}", f"视频围绕「{topic}」展开，可用于分类检索。")
                if len(out) >= min_cards:
                    break

        if len(out) < min_cards:
            takeaways = analysis.get("takeaways") or ""
            if isinstance(takeaways, list):
                lines = [str(x).strip("- •\t ") for x in takeaways if str(x).strip()]
            else:
                lines = [
                    ln.strip("- •\t ")
                    for ln in str(takeaways).splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                ]
            for i, line in enumerate(lines):
                _add("quote", f"可执行建议 {i + 1}", line)
                if len(out) >= min_cards:
                    break

        if len(out) < min_cards and title:
            _add("case", "视频主题", f"标题：{title}\n文稿摘要：{(timed_transcript or '')[:200]}")
        if len(out) < min_cards:
            detailed = (analysis.get("detailed_analysis") or "")[:300]
            if detailed:
                _add("concept", "深度解析摘要", detailed)

        return out

    def evaluate_quality(
        self,
        *,
        timed_transcript: str,
        segments: List[Dict],
        analysis: Dict,
        cards: List[Dict],
        has_video: bool,
        has_audio: bool,
        duration: int,
    ) -> Dict:
        issues = []
        score = 100
        detailed = (analysis.get("detailed_analysis") or "") if analysis else ""
        transcript_len = len(timed_transcript or "")
        has_ts = bool(re.search(r"\[\d{1,2}:\d{2}\]", timed_transcript or ""))
        seg_n = len(segments or [])

        # 口播稀少：短视频 + 转写很短，但已有完整音视频（萌宠/BGM 常见）
        speech_sparse = bool(
            has_audio
            and has_video
            and transcript_len < 80
            and (not duration or duration <= 90)
        )

        if not has_video:
            score -= 20
            issues.append("缺少完整本地视频文件")
        if not has_audio:
            score -= 15
            issues.append("缺少完整音频")

        if speech_sparse:
            issues.append("口播稀少（萌宠/BGM类），按无口播模式验收")
            # 无口播时转写短不重罚，但要求更深解析与更多卡片补齐
            if len(detailed) < 1200:
                score -= 12
                issues.append("无口播模式下深度解析偏短（需≥1200字）")
            if len(cards) < 3:
                score -= 12
                issues.append("无口播模式下知识卡片不足（<3）")
        else:
            if transcript_len < 80:
                score -= 25
                issues.append("完整转写过短（可能无口播或 ASR 失败）")
            elif transcript_len < 300:
                score -= 8
                issues.append("转写偏短")

            if not has_ts and transcript_len >= 80:
                score -= 8
                issues.append("缺少时间戳转写")

            if duration and duration > 90 and seg_n < 3 and transcript_len >= 80:
                score -= 8
                issues.append("长视频 ASR 分段过少")

            if len(detailed) < 800:
                score -= 20
                issues.append("深度解析过短（疑似摘要）")
            elif len(detailed) < 1500:
                score -= 6
                issues.append("深度解析偏短")

            if len(cards) < 3:
                score -= 10
                issues.append("知识卡片不足（<3）")

        coverage = 0.0
        if transcript_len > 0:
            coverage = min(1.5, len(detailed) / max(transcript_len, 1))
        coverage_ok = (transcript_len >= 200 and coverage >= 0.5) or (
            transcript_len < 200 and len(detailed) >= 1200
        )
        if not coverage_ok and not speech_sparse:
            score -= 8
            issues.append("解析对完整文稿覆盖可能不足")
        elif speech_sparse and len(detailed) < 1200:
            # 已在上方扣分
            pass

        score = max(0, min(100, score))
        # 口播稀少：有完整视频 + 深度解析达标即可通过门禁
        if speech_sparse:
            passed = score >= 70 and len(detailed) >= 1200 and has_video and has_audio
        else:
            passed = score >= 70 and len(detailed) >= 800 and has_video

        return {
            "score": score,
            "passed": passed,
            "speech_sparse": speech_sparse,
            "coverage_ratio": round(coverage, 3),
            "transcript_chars": transcript_len,
            "analysis_chars": len(detailed),
            "segments": seg_n,
            "frames_analyzed": 0,
            "knowledge_cards": len(cards or []),
            "has_timestamps": has_ts,
            "full_video_pipeline": True,
            "issues": issues,
            "checklist": {
                "downloaded_full_video": has_video,
                "extracted_full_audio": has_audio,
                "full_asr_done": transcript_len >= 80 or speech_sparse,
                "can_answer_what": len(detailed) >= 500,
                "can_answer_how": bool(analysis.get("takeaways")) or ("步骤" in detailed),
                "can_answer_why": ("为什么" in detailed) or ("原因" in detailed),
                "has_boundaries": ("边界" in detailed) or ("局限" in detailed) or ("适用" in detailed),
                "cards_with_timestamp": sum(
                    1 for c in (cards or []) if c.get("timestamp") or c.get("time_range")
                ),
                "no_frame_extraction": True,
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
        slices = str(Path(getattr(settings, "VIDEO_STORAGE_PATH", "./data/videos")).parent / "slices")
        _pipeline = VideoLearningPipeline(asr=asr, gemini=gemini, slices_dir=slices)
    return _pipeline
