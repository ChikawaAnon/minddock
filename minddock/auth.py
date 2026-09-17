"""应用内登录鉴权：挑战-响应 + 内存会话 token（纯标准库）。

威胁模型与取舍：
- 公网走明文 HTTP（无域名无法上正规 TLS），密码绝不能明文过网：
  登录用挑战-响应，网上只出现 sha256(存储hash + 一次性nonce)，可逆/重放都不可行。
- token 存内存：服务重启即失效需重新登录，个人单用户场景可接受。
- challenge 按来源 IP 限速，防在线爆破；未配置 password_sha256 时整套鉴权关闭
  （本机/测试场景行为不变）。

约定：
- 存储侧：password_sha256 = sha256(salt + password) 的 hex，salt 为配置中的随机串
- 登录侧：客户端算 x = sha256(salt + password)，回传 resp = sha256(x + nonce)
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time

CHALLENGE_TTL = 60          # nonce 有效期（秒）
SESSION_TTL = 24 * 3600     # 会话有效期（秒），访问自动续期
CHALLENGE_RATE = 10         # 每 IP 每分钟最多获取 challenge 次数


def hash_password(salt: str, password: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


class AuthManager:
    def __init__(self, salt: str | None, password_sha256: str | None):
        self.salt = salt or ""
        self.password_sha256 = password_sha256 or None
        self.enabled = bool(password_sha256)
        self._challenges: dict[str, float] = {}      # nonce -> expire_at
        self._sessions: dict[str, float] = {}        # token -> expire_at
        self._rate: dict[str, list[float]] = {}      # ip -> [timestamps]
        self._lock = threading.Lock()

    # ---- 登录流程 ----

    def new_challenge(self, ip: str) -> str | None:
        """签发一次性 nonce；未启用鉴权返回 None，限速超限抛 PermissionError。"""
        if not self.enabled:
            return None
        now = time.time()
        with self._lock:
            hits = [t for t in self._rate.get(ip, []) if now - t < 60]
            if len(hits) >= CHALLENGE_RATE:
                raise PermissionError("尝试过于频繁，请稍后再试")
            hits.append(now)
            self._rate[ip] = hits
            nonce = secrets.token_hex(16)
            self._challenges[nonce] = now + CHALLENGE_TTL
            # 顺手清理过期 nonce
            self._challenges = {k: v for k, v in self._challenges.items() if v > now}
        return nonce

    def login(self, nonce: str, resp: str) -> str | None:
        """校验挑战响应，成功返回新会话 token，失败返回 None。"""
        now = time.time()
        with self._lock:
            expire = self._challenges.pop(nonce, 0)  # 一次性：无论成败都作废
            if not nonce or expire < now:
                return None
            expect = hashlib.sha256(
                (self.password_sha256 + nonce).encode("utf-8")).hexdigest()
            if not secrets.compare_digest(resp, expect):
                return None
            token = secrets.token_urlsafe(32)
            self._sessions[token] = now + SESSION_TTL
        return token

    def check(self, token: str) -> bool:
        """会话有效则滑动续期并返回 True。"""
        if not self.enabled:
            return True
        if not token:
            return False
        now = time.time()
        with self._lock:
            expire = self._sessions.get(token, 0)
            if expire < now:
                return False
            self._sessions[token] = now + SESSION_TTL
            return True

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)
