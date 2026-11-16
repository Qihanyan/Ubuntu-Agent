import re
import time
from collections import defaultdict, deque

import bcrypt
import jwt
from fastapi import Header, HTTPException, status

import settings

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}[a-z0-9]$")
BCRYPT_MAX_BYTES = 72

# 用户不存在时也做一次 bcrypt 校验，避免通过响应时间判断用户名是否存在
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


def validate_config() -> None:
    """启动时检查配置，有问题直接拒绝启动。"""
    if len(settings.JWT_SECRET) < 32:
        raise RuntimeError("环境变量 MUSIC_AGENT_JWT_SECRET 未设置或太短（至少 32 字符）")
    if not settings.USERS:
        raise RuntimeError("settings.USERS 为空，至少配置一个用户")
    for name, hashed in settings.USERS.items():
        if not USERNAME_RE.match(name):
            raise RuntimeError(f"用户名 {name!r} 不合法：只能用小写字母、数字、_、-，3~32 位")
        if not hashed.startswith("$2"):
            raise RuntimeError(f"用户 {name!r} 的密码不是 bcrypt 哈希，请用 manage_users.py 生成")


def verify_password(username: str, password: str) -> bool:
    """同步函数（bcrypt 较慢），调用方用 asyncio.to_thread 包一层。"""
    pw = password.encode()
    if len(pw) > BCRYPT_MAX_BYTES:
        bcrypt.checkpw(b"x", _DUMMY_HASH.encode())
        return False
    hashed = settings.USERS.get(username)
    ok = bcrypt.checkpw(pw, (hashed or _DUMMY_HASH).encode())
    return ok and hashed is not None


def create_token(username: str) -> str:
    now = int(time.time())
    payload = {"sub": username, "iat": now, "exp": now + settings.JWT_EXPIRE_HOURS * 3600}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> str | None:
    """返回用户名；无效、过期、或用户已从配置中删除时返回 None。"""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    user = payload.get("sub")
    return user if user in settings.USERS else None


def require_user(authorization: str = Header(default="")) -> str:
    """HTTP 接口的鉴权依赖：Authorization: Bearer <token>"""
    scheme, _, token = authorization.partition(" ")
    user = decode_token(token.strip()) if scheme.lower() == "bearer" else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    return user


class LoginRateLimiter:
    """按 IP 统计登录失败次数的滑动窗口限流（单进程内存版）。"""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
            return True
        return len(q) < self.max_attempts

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
