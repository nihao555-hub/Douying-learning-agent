"""
抖音 Cookie 永久存储。

- 写入 data/secrets/douyin_cookie.txt（权限 0600）
- 同步到 .env 的 DOUYIN_COOKIE（兼容旧逻辑）
- 启动时加载；只有验证成功的登录 Cookie 才会覆盖
- 禁止用空值/匿名 Cookie 覆盖已有有效登录态
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logger import logger

SECRETS_DIR = Path(__file__).resolve().parents[2] / "data" / "secrets"
COOKIE_FILE = SECRETS_DIR / "douyin_cookie.txt"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
LOGIN_KEYS = ("sessionid", "sessionid_ss", "sid_tt", "uid_tt", "sid_guard")


def _looks_like_login_cookie(header: str) -> bool:
    lower = (header or "").lower()
    return any(k in lower for k in LOGIN_KEYS)


def load_persisted_cookie() -> str:
    """优先读 secrets 文件，其次 .env / settings。"""
    try:
        if COOKIE_FILE.exists():
            value = COOKIE_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
    except Exception as e:
        logger.warning(f"读取永久 Cookie 文件失败: {e}")

    env_value = (getattr(settings, "DOUYIN_COOKIE", "") or "").strip()
    if env_value:
        return env_value

    if ENV_PATH.exists():
        try:
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if line.startswith("DOUYIN_COOKIE="):
                    raw = line.split("=", 1)[1].strip()
                    if (raw.startswith("'") and raw.endswith("'")) or (
                        raw.startswith('"') and raw.endswith('"')
                    ):
                        raw = raw[1:-1]
                    return raw.replace("\\'", "'").replace("\\\\", "\\").strip()
        except Exception as e:
            logger.warning(f"从 .env 读取 Cookie 失败: {e}")
    return ""


def apply_cookie_to_runtime(header: str) -> None:
    """让当前进程立即使用该 Cookie。"""
    header = (header or "").strip()
    settings.DOUYIN_COOKIE = header
    try:
        from app.services.douyin_client import get_douyin_client

        client = get_douyin_client()
        client.cookie = header
        client._enhanced_cookie_header = None
        client._base_cookies = None
    except Exception as e:
        logger.debug(f"运行时刷新 DouyinClient Cookie 失败: {e}")


def persist_douyin_cookie(header: str, *, require_login_keys: bool = True) -> bool:
    """
    永久保存 Cookie。
    - 空值不会覆盖已有有效 Cookie
    - require_login_keys=True 时，缺少登录关键字段则拒绝保存
    """
    header = (header or "").strip()
    if not header:
        logger.warning("拒绝保存空 Cookie（不会清空已有登录态）")
        return False
    if require_login_keys and not _looks_like_login_cookie(header):
        logger.warning("拒绝保存疑似匿名 Cookie（缺少 sessionid 等登录字段）")
        return False

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    temp = COOKIE_FILE.with_suffix(".tmp")
    temp.write_text(header + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(COOKIE_FILE)
    COOKIE_FILE.chmod(0o600)

    # 同步 .env（不存在则创建）
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
        escaped = header.replace("\\", "\\\\").replace("'", "\\'")
        replacement = f"DOUYIN_COOKIE='{escaped}'"
        output = []
        replaced = False
        for line in lines:
            if line.startswith("DOUYIN_COOKIE="):
                output.append(replacement)
                replaced = True
            else:
                output.append(line)
        if not replaced:
            output.append(replacement)
        env_tmp = ENV_PATH.with_suffix(".env.tmp")
        env_tmp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        env_tmp.chmod(0o600)
        env_tmp.replace(ENV_PATH)
    except Exception as e:
        logger.warning(f"同步 Cookie 到 .env 失败（secrets 文件已保存）: {e}")

    apply_cookie_to_runtime(header)
    logger.info(
        f"抖音 Cookie 已永久保存（长度={len(header)}, "
        f"path={COOKIE_FILE}, 登录字段={'有' if _looks_like_login_cookie(header) else '无'}）"
    )
    return True


def bootstrap_cookie_on_startup() -> Optional[str]:
    """服务启动时加载永久 Cookie 到运行时。"""
    header = load_persisted_cookie()
    if header:
        apply_cookie_to_runtime(header)
        # 若只有 .env 有值，补写 secrets 文件
        if not COOKIE_FILE.exists():
            try:
                persist_douyin_cookie(header, require_login_keys=False)
            except Exception:
                pass
        logger.info(f"已从永久存储加载 DOUYIN_COOKIE（长度={len(header)}）")
        return header
    logger.warning("永久存储中无 DOUYIN_COOKIE，需登录后自动保存")
    return None


def clear_douyin_cookie(*, force: bool = False) -> bool:
    """显式清除（默认不调用）。仅管理接口可 force。"""
    if not force:
        logger.warning("拒绝非强制清空 Cookie")
        return False
    try:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
    except Exception:
        pass
    apply_cookie_to_runtime("")
    return True
