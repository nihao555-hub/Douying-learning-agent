"""
抖音嵌入式登录会话。

在独立的 X/VNC 显示器中启动 Chrome，通过 noVNC 供前端嵌入。
前端轮询状态时，后端经 Chrome DevTools Protocol 读取登录 Cookie；
Cookie 只写入服务端 .env 和内存，不通过 API 返回明文。
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx
import websockets

from app.core.config import settings
from app.core.logger import logger


class DouyinLoginSession:
    """单实例、短时有效的隔离登录浏览器。"""

    DISPLAY = ":9"
    VNC_PORT = 5909
    NOVNC_PORT = 26059
    CDP_PORT = 9229
    SESSION_TTL = 10 * 60
    NOVNC_ROOT = Path("/usr/local/novnc/noVNC-1.2.0")
    WORK_DIR = Path("/tmp/douyin-embedded-login")
    PID_FILE = WORK_DIR / "pids.json"

    def __init__(self):
        self.token: Optional[str] = None
        self.vnc_password: Optional[str] = None
        self.created_at: float = 0
        self.processes: List[subprocess.Popen] = []
        self._lock = asyncio.Lock()
        self._captured = False
        self._cookie_count = 0
        self._cookie_names: List[str] = []

    @property
    def active(self) -> bool:
        return bool(
            self.token
            and time.time() - self.created_at < self.SESSION_TTL
            and any(p.poll() is None for p in self.processes)
        )

    def _check_dependencies(self):
        required = ["Xtigervnc", "vncpasswd", "google-chrome", "websockify"]
        missing = [name for name in required if not shutil.which(name)]
        if missing:
            raise RuntimeError(f"登录窗口依赖缺失: {', '.join(missing)}")
        if not (self.NOVNC_ROOT / "vnc.html").exists():
            raise RuntimeError("noVNC 静态资源缺失")

    @staticmethod
    def _terminate(process: subprocess.Popen):
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

    async def stop(self):
        for process in reversed(self.processes):
            self._terminate(process)
        # API 重启后内存中的 Popen 会丢失，用 PID 文件清理遗留的隔离进程。
        if self.PID_FILE.exists():
            try:
                for pid in json.loads(self.PID_FILE.read_text(encoding="utf-8")):
                    try:
                        os.killpg(int(pid), signal.SIGTERM)
                    except (ProcessLookupError, ValueError):
                        pass
            except Exception:
                pass
            try:
                self.PID_FILE.unlink()
            except FileNotFoundError:
                pass
        self.processes = []
        self.token = None
        self.vnc_password = None
        self.created_at = 0
        self._captured = False
        self._cookie_count = 0
        self._cookie_names = []
        await asyncio.sleep(0.2)

    def _popen(self, args: List[str], **kwargs) -> subprocess.Popen:
        process = subprocess.Popen(
            args,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
        self.processes.append(process)
        self.WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.PID_FILE.write_text(
            json.dumps([p.pid for p in self.processes]),
            encoding="utf-8",
        )
        return process

    async def start(self) -> Dict:
        async with self._lock:
            if self.active:
                return self._public_state()

            await self.stop()
            self._check_dependencies()
            self.WORK_DIR.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(self.WORK_DIR / "chrome-profile", ignore_errors=True)

            self.token = secrets.token_urlsafe(24)
            # VNC 传统认证只使用前 8 个字符。
            self.vnc_password = secrets.token_urlsafe(6)[:8]
            self.created_at = time.time()

            passwd_file = self.WORK_DIR / "vnc.passwd"
            encoded = subprocess.run(
                ["vncpasswd", "-f"],
                input=self.vnc_password.encode(),
                capture_output=True,
                check=True,
            ).stdout
            passwd_file.write_bytes(encoded)
            passwd_file.chmod(0o600)

            # 清理可能由异常退出留下的 display/socket。
            for stale in [Path("/tmp/.X9-lock"), Path("/tmp/.X11-unix/X9")]:
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass

            log_file = open(self.WORK_DIR / "session.log", "ab", buffering=0)
            self._popen(
                [
                    "Xtigervnc",
                    self.DISPLAY,
                    "-localhost=1",
                    "-SecurityTypes", "VncAuth",
                    "-PasswordFile", str(passwd_file),
                    "-geometry", "1280x900",
                    "-depth", "24",
                    "-rfbport", str(self.VNC_PORT),
                    "-AlwaysShared=1",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            await asyncio.sleep(1.0)

            env = dict(os.environ)
            env["DISPLAY"] = self.DISPLAY
            self._popen(
                [
                    "google-chrome",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-features=Translate",
                    "--password-store=basic",
                    "--remote-allow-origins=*",
                    f"--remote-debugging-port={self.CDP_PORT}",
                    f"--user-data-dir={self.WORK_DIR / 'chrome-profile'}",
                    "--window-size=1260,860",
                    "--window-position=0,0",
                    "--app=https://www.douyin.com/",
                ],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            self._popen(
                [
                    "websockify",
                    str(self.NOVNC_PORT),
                    f"localhost:{self.VNC_PORT}",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

            logger.info("抖音隔离登录窗口已启动（Cookie 不会返回前端）")
            return self._public_state()

    def _public_state(self) -> Dict:
        expires_in = max(0, int(self.SESSION_TTL - (time.time() - self.created_at)))
        viewer_url = None
        if self.vnc_password:
            # 与主站同源：FastAPI 提供 noVNC 静态文件并代理 WebSocket，
            # 避免临时 Quick Tunnel 的 DNS 延迟/失效。
            viewer_url = (
                "/novnc/vnc.html"
                f"?autoconnect=true&resize=scale&quality=6"
                f"&path=novnc/websockify"
                f"&password={quote(self.vnc_password)}"
            )
        return {
            "active": self.active,
            "session_token": self.token,
            "viewer_url": viewer_url,
            "expires_in": expires_in,
            "captured": self._captured,
            "cookie_count": self._cookie_count,
            "cookie_names": self._cookie_names,
        }

    async def _read_cookies_from_chrome(self) -> List[Dict]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"http://127.0.0.1:{self.CDP_PORT}/json/version")
            response.raise_for_status()
            ws_url = response.json().get("webSocketDebuggerUrl")
        if not ws_url:
            return []

        async with websockets.connect(ws_url, origin="http://localhost", open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if message.get("id") == 1:
                    return (message.get("result") or {}).get("cookies") or []

    @staticmethod
    def _cookie_header(cookies: List[Dict]) -> str:
        allowed = {}
        for cookie in cookies:
            domain = str(cookie.get("domain") or "").lstrip(".").lower()
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            if (
                name
                and value
                and (domain == "douyin.com" or domain.endswith(".douyin.com")
                     or domain == "iesdouyin.com" or domain.endswith(".iesdouyin.com"))
            ):
                allowed[name] = value
        return "; ".join(f"{k}={v}" for k, v in allowed.items())

    @staticmethod
    async def _validate_logged_in(header: str) -> bool:
        """
        不能只看 sessionid 等键：抖音现在会给匿名访客下发同名会话键。
        以 self profile API 的 status_code=0 且存在用户标识为准。
        """
        if not header:
            return False
        try:
            async with httpx.AsyncClient(
                timeout=12,
                follow_redirects=True,
                verify=False,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.douyin.com/",
                    "Cookie": header,
                },
            ) as client:
                response = await client.get(
                    "https://www.douyin.com/aweme/v1/web/user/profile/self/"
                )
                data = response.json()
            user = data.get("user") or {}
            user_id = (
                user.get("uid")
                or user.get("short_id")
                or user.get("sec_uid")
                or user.get("sec_user_id")
            )
            return data.get("status_code") == 0 and bool(user_id)
        except Exception as exc:
            logger.debug(f"验证抖音登录态失败: {exc}")
            return False

    @staticmethod
    def _persist_cookie(header: str):
        env_path = Path(__file__).resolve().parents[2] / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
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
        temp = env_path.with_suffix(".env.tmp")
        temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        temp.chmod(0o600)
        temp.replace(env_path)

        # 当前进程立即生效，无需重启。
        settings.DOUYIN_COOKIE = header
        from app.services.douyin_client import get_douyin_client
        client = get_douyin_client()
        client.cookie = header
        client._enhanced_cookie_header = None
        client._base_cookies = None

    async def status(self, session_token: str) -> Dict:
        if not self.token or not secrets.compare_digest(session_token or "", self.token):
            raise ValueError("登录会话无效")
        if time.time() - self.created_at >= self.SESSION_TTL:
            await self.stop()
            return {"active": False, "expired": True, "captured": False}

        try:
            cookies = await self._read_cookies_from_chrome()
        except Exception as exc:
            logger.debug(f"读取登录浏览器 Cookie 尚未就绪: {exc}")
            return self._public_state()

        header = self._cookie_header(cookies)
        names = [part.split("=", 1)[0] for part in header.split("; ") if "=" in part]
        has_login = await self._validate_logged_in(header)

        self._cookie_count = len(names)
        # 仅公开名称，不返回值。
        self._cookie_names = sorted(names)
        if has_login and not self._captured:
            self._persist_cookie(header)
            self._captured = True
            logger.info(f"抖音登录 Cookie 捕获成功（{len(names)}项，值已脱敏）")

        state = self._public_state()
        state["login_detected"] = has_login
        state["validation"] = "已验证账号登录态" if has_login else "等待用户登录"
        return state


_login_session: Optional[DouyinLoginSession] = None


def get_douyin_login_session() -> DouyinLoginSession:
    global _login_session
    if _login_session is None:
        _login_session = DouyinLoginSession()
    return _login_session
