"""
系统质量检测：基础设施 / 抓取覆盖 / 素材完整性 / 学习验收 / 公网可达。
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.models import Blogger, Video
from app.services.video_learning_pipeline import get_video_learning_pipeline


def _file_ok(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {"exists": False, "size": 0, "path": None}
    p = Path(path)
    exists = p.exists() and p.is_file()
    return {
        "exists": exists,
        "size": p.stat().st_size if exists else 0,
        "path": str(p),
    }


def _check_ffmpeg() -> Dict[str, Any]:
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    ok = bool(ff and fp)
    versions = {}
    if ff:
        try:
            out = subprocess.check_output([ff, "-version"], text=True, timeout=5)
            versions["ffmpeg"] = out.splitlines()[0] if out else "ok"
        except Exception as e:
            versions["ffmpeg_error"] = str(e)[:120]
            ok = False
    return {"ok": ok, "ffmpeg": ff, "ffprobe": fp, "versions": versions}


def _check_whisper_model() -> Dict[str, Any]:
    candidates = [
        getattr(settings, "WHISPER_MODEL_PATH", "") or "",
        "./data/models/faster-whisper-base",
        str(Path(__file__).resolve().parents[2] / "data" / "models" / "faster-whisper-base"),
    ]
    found = None
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.exists() and (p / "model.bin").exists():
            found = str(p.resolve())
            break
    return {
        "ok": bool(found),
        "path": found,
        "engine": settings.ASR_ENGINE,
        "model_size": settings.WHISPER_MODEL_SIZE,
        "device": settings.WHISPER_DEVICE,
    }


def _infra_checks() -> Dict[str, Any]:
    whisper = _check_whisper_model()
    ffmpeg = _check_ffmpeg()
    gemini_ok = bool(settings.GEMINI_API_KEY)
    cookie_ok = bool(getattr(settings, "DOUYIN_COOKIE", "") or "")
    checks = {
        "gemini_configured": gemini_ok,
        "douyin_cookie_configured": cookie_ok,
        "whisper_model_local": whisper["ok"],
        "ffmpeg_available": ffmpeg["ok"],
        "max_concurrent_videos": int(getattr(settings, "MAX_CONCURRENT_VIDEOS", 1000) or 1000),
        "max_videos_per_blogger": int(settings.MAX_VIDEOS_PER_BLOGGER),
        "video_slice_seconds": int(getattr(settings, "VIDEO_SLICE_SECONDS", 120) or 120),
        "full_video_pipeline": True,
        "no_frame_extraction": True,
    }
    issues = []
    if not gemini_ok:
        issues.append("GEMINI_API_KEY 未配置")
    if not cookie_ok:
        issues.append("DOUYIN_COOKIE 未配置（无登录时列表约 40–44 条硬限制）")
    if not whisper["ok"]:
        issues.append("本地 Whisper 模型缺失")
    if not ffmpeg["ok"]:
        issues.append("ffmpeg/ffprobe 不可用")
    if checks["max_concurrent_videos"] < 1000:
        issues.append(f"MAX_CONCURRENT_VIDEOS={checks['max_concurrent_videos']} < 1000")

    critical_ok = gemini_ok and whisper["ok"] and ffmpeg["ok"]
    return {
        "passed": critical_ok,
        "checks": checks,
        "whisper": whisper,
        "ffmpeg": ffmpeg,
        "issues": issues,
    }


def _re_evaluate_video(video: Video, pipeline) -> Dict[str, Any]:
    """用当前验收规则重算（不重新下载/ASR）。"""
    video_ok = _file_ok(video.local_video_path)
    audio_ok = _file_ok(video.local_audio_path)
    analysis = {
        "detailed_analysis": (video.summary or "").split("\n\n---\n\n**摘要**：")[0]
        if video.summary
        else "",
        "takeaways": video.takeaways or "",
        "summary": "",
        "key_points": video.key_points or [],
        "topics": video.topics or [],
    }
    # 去掉验收尾巴，避免污染字数
    detailed = analysis["detailed_analysis"]
    if "**学习验收**" in detailed:
        detailed = detailed.split("**学习验收**")[0].strip()
        analysis["detailed_analysis"] = detailed

    quality = pipeline.evaluate_quality(
        timed_transcript=video.transcript or "",
        segments=video.transcript_segments or [],
        analysis=analysis,
        cards=video.knowledge_cards or [],
        has_video=video_ok["exists"],
        has_audio=audio_ok["exists"],
        duration=int(video.duration or 0),
    )
    return {
        "video_id": video.id,
        "aweme_id": video.aweme_id,
        "title": (video.title or "")[:80],
        "status": video.status,
        "duration": video.duration,
        "materials": {
            "video": video_ok,
            "audio": audio_ok,
            "transcript_chars": len(video.transcript or ""),
            "summary_chars": len(video.summary or ""),
            "segments": len(video.transcript_segments or []),
            "cards": len(video.knowledge_cards or []),
            "frame_notes": len(video.frame_notes or []),
        },
        "stored_quality": video.quality_report or {},
        "reevaluated_quality": quality,
        "stale_report": bool(
            (video.quality_report or {}).get("frames_analyzed", 0)
            or any(
                "口播" in str(i) and "转写过短" in str(i)
                for i in ((video.quality_report or {}).get("issues") or [])
            )
            and quality.get("speech_sparse")
        ),
    }


async def run_quality_audit(
    db: AsyncSession,
    *,
    blogger_id: Optional[int] = None,
    persist_reeval: bool = False,
) -> Dict[str, Any]:
    """执行完整质量检测并返回结构化报告。"""
    infra = _infra_checks()
    pipeline = get_video_learning_pipeline()

    q = select(Blogger).options(selectinload(Blogger.videos))
    if blogger_id is not None:
        q = q.where(Blogger.id == blogger_id)
    result = await db.execute(q.order_by(Blogger.id.desc()))
    bloggers = result.scalars().unique().all()

    blogger_reports: List[Dict[str, Any]] = []
    totals = {
        "bloggers": 0,
        "videos": 0,
        "videos_passed": 0,
        "videos_failed_gate": 0,
        "materials_complete": 0,
        "crawl_incomplete": 0,
    }

    for b in bloggers:
        videos = list(b.videos or [])
        video_reports = [_re_evaluate_video(v, pipeline) for v in videos]

        if persist_reeval:
            for v, vr in zip(videos, video_reports):
                v.quality_report = vr["reevaluated_quality"]
            await db.commit()

        passed_n = sum(1 for vr in video_reports if vr["reevaluated_quality"].get("passed"))
        materials_n = sum(
            1
            for vr in video_reports
            if vr["materials"]["video"]["exists"] and vr["materials"]["audio"]["exists"]
        )
        aweme_count = int(b.aweme_count or 0)
        crawled = int(b.total_videos or len(videos))
        coverage_ratio = (crawled / aweme_count) if aweme_count > 0 else None
        crawl_ok = True
        crawl_issues = []
        if aweme_count > 0 and crawled < min(aweme_count, 40) and not getattr(
            settings, "DOUYIN_COOKIE", ""
        ):
            # 无 cookie 时至少应接近 40+；demo 限 3 也算覆盖不足
            crawl_ok = False
            crawl_issues.append(
                f"抓取 {crawled}/{aweme_count}，无 Cookie 时通常也只能到约 40–44；当前明显偏少"
            )
        elif aweme_count > 0 and crawled < aweme_count:
            crawl_ok = False
            crawl_issues.append(
                f"抓取未全量：{crawled}/{aweme_count}"
                + ("（需 DOUYIN_COOKIE）" if not getattr(settings, "DOUYIN_COOKIE", "") else "")
            )

        master_ok = bool(b.master_summary) and len(b.master_summary or "") >= 500
        blogger_pass = (
            infra["passed"]
            and materials_n == len(videos)
            and passed_n == len(videos)
            and master_ok
            and (coverage_ratio is None or coverage_ratio >= 0.95 or crawled >= aweme_count)
        )

        # 宽松：若视频均为口播稀少且解析达标，仍可标为“内容受限通过”
        content_limited = all(
            vr["reevaluated_quality"].get("speech_sparse") for vr in video_reports
        ) and len(video_reports) > 0
        soft_pass = (
            infra["passed"]
            and materials_n == len(videos)
            and all(vr["reevaluated_quality"].get("score", 0) >= 70 for vr in video_reports)
            and master_ok
            and content_limited
        )

        report = {
            "blogger_id": b.id,
            "nickname": b.nickname,
            "status": b.status,
            "aweme_count": aweme_count,
            "crawled_videos": crawled,
            "coverage_ratio": round(coverage_ratio, 4) if coverage_ratio is not None else None,
            "crawl_ok": crawl_ok,
            "crawl_issues": crawl_issues,
            "master_doc_chars": len(b.master_summary or ""),
            "master_doc_ok": master_ok,
            "videos_total": len(videos),
            "videos_passed": passed_n,
            "materials_complete": materials_n,
            "content_limited_speech_sparse": content_limited,
            "passed": blogger_pass,
            "soft_passed": soft_pass,
            "videos": video_reports,
        }
        blogger_reports.append(report)

        totals["bloggers"] += 1
        totals["videos"] += len(videos)
        totals["videos_passed"] += passed_n
        totals["videos_failed_gate"] += len(videos) - passed_n
        totals["materials_complete"] += materials_n
        if not crawl_ok:
            totals["crawl_incomplete"] += 1

    overall_issues: List[str] = list(infra["issues"])
    for br in blogger_reports:
        overall_issues.extend(br.get("crawl_issues") or [])
        if not br["master_doc_ok"]:
            overall_issues.append(f"博主 {br['nickname']} 综合文档缺失或过短")
        for vr in br["videos"]:
            q = vr["reevaluated_quality"]
            if not q.get("passed"):
                overall_issues.append(
                    f"视频#{vr['video_id']} 验收未通过 score={q.get('score')} "
                    f"issues={','.join(q.get('issues') or [])}"
                )

    # 去重保序
    seen = set()
    deduped = []
    for i in overall_issues:
        if i not in seen:
            seen.add(i)
            deduped.append(i)

    hard_pass = (
        infra["passed"]
        and totals["videos"] > 0
        and totals["videos_passed"] == totals["videos"]
        and totals["crawl_incomplete"] == 0
        and all(br["master_doc_ok"] for br in blogger_reports)
    )
    soft_pass = (
        infra["passed"]
        and totals["videos"] > 0
        and all(br.get("soft_passed") or br.get("passed") for br in blogger_reports)
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_passed": hard_pass,
        "overall_soft_passed": soft_pass and not hard_pass,
        "verdict": (
            "PASS"
            if hard_pass
            else ("SOFT_PASS_SPEECH_SPARSE" if soft_pass else "FAIL")
        ),
        "totals": totals,
        "infrastructure": infra,
        "bloggers": blogger_reports,
        "issues": deduped,
        "recommendations": _recommendations(infra, blogger_reports, hard_pass, soft_pass),
    }


def _recommendations(
    infra: Dict, blogger_reports: List[Dict], hard_pass: bool, soft_pass: bool
) -> List[str]:
    recs = []
    if not infra["checks"].get("douyin_cookie_configured"):
        recs.append("配置 DOUYIN_COOKIE 后重新抓取，才能逼近 aweme_count 全量。")
    if any(br.get("content_limited_speech_sparse") for br in blogger_reports):
        recs.append(
            "当前样本多为萌宠短视频、口播极稀；验收已按无口播模式计分。"
            "建议再测一条口播/教程类博主验证 ASR→深度解析链路。"
        )
    for br in blogger_reports:
        if br["crawled_videos"] < 10 and (br["aweme_count"] or 0) > 10:
            recs.append(
                f"「{br['nickname']}」仅处理了 {br['crawled_videos']} 条，"
                "请确认是否人为限流或 Cookie/翻页失败。"
            )
        for vr in br["videos"]:
            cards = vr["materials"]["cards"]
            if cards < 3:
                recs.append(f"视频#{vr['video_id']} 知识卡片仅 {cards} 张，建议强化卡片抽取提示。")
    if hard_pass:
        recs.append("硬验收全部通过。")
    elif soft_pass:
        recs.append("基础设施与素材完整，但因口播稀少/抓取未全量，标记为软通过。")
    return list(dict.fromkeys(recs))
