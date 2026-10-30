"""密码哈希、JWT、图形验证码。不引 passlib——bcrypt 直接调两行就够。"""
from __future__ import annotations

import base64
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import BizError, Codes
from app.core.redis import rds

_CAPTCHA_CHARS = string.digits + string.ascii_uppercase
_CAPTCHA_KEY = "captcha:{}"


# ---------- 密码 ----------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------
def _encode(payload: dict, ttl: int) -> str:
    now = datetime.now(timezone.utc)
    body = {**payload, "iat": now, "exp": now + timedelta(seconds=ttl), "jti": uuid.uuid4().hex}
    return jwt.encode(body, settings.jwt_secret, algorithm=settings.jwt_alg)


def make_access_token(user_id: int, role: str) -> str:
    return _encode({"sub": str(user_id), "role": role, "typ": "access"}, settings.access_ttl)


def make_refresh_token(user_id: int) -> str:
    return _encode({"sub": str(user_id), "typ": "refresh"}, settings.refresh_ttl)


def decode_token(token: str, *, typ: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except jwt.ExpiredSignatureError:
        raise BizError(Codes.UNAUTHORIZED, "登录已过期，请重新登录") from None
    except jwt.InvalidTokenError:
        raise BizError(Codes.UNAUTHORIZED, "无效的登录凭证") from None
    if payload.get("typ") != typ:
        raise BizError(Codes.UNAUTHORIZED, "凭证类型不符")
    return payload


def blacklist(jti: str, exp: int) -> None:
    """登出/改密后把 jti 拉黑，TTL = token 剩余有效期。"""
    ttl = max(1, exp - int(datetime.now(timezone.utc).timestamp()))
    rds.set(f"bl:{jti}", "1", ex=ttl)


def is_blacklisted(jti: str) -> bool:
    return bool(rds.exists(f"bl:{jti}"))


# ---------- 验证码 ----------
def make_captcha() -> dict:
    """返回 captcha_id + SVG data URI。不引 PIL：几个 <text> + 干扰线就够挡住脚本。"""
    code = "".join(random.choice(_CAPTCHA_CHARS) for _ in range(4))
    cid = uuid.uuid4().hex
    rds.set(_CAPTCHA_KEY.format(cid), code.upper(), ex=settings.captcha_ttl)
    svg = _captcha_svg(code)
    return {
        "captcha_id": cid,
        "image": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(),
        "ttl": settings.captcha_ttl,
    }


def verify_captcha(cid: str, code: str) -> None:
    if not cid or not code:
        raise BizError(Codes.BAD_REQUEST, "请填写验证码")
    key = _CAPTCHA_KEY.format(cid)
    real = rds.get(key)
    if not real:
        raise BizError(Codes.BAD_REQUEST, "验证码已过期，请刷新")
    rds.delete(key)  # 一次性，防重放
    if real.upper() != code.strip().upper():
        raise BizError(Codes.BAD_REQUEST, "验证码错误")


def _captcha_svg(code: str) -> str:
    rnd = random.Random(code)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" viewBox="0 0 120 40">',
        '<rect width="120" height="40" fill="#f4f7fb"/>',
    ]
    for _ in range(4):
        x1, y1, x2, y2 = (rnd.randint(0, 120) for _ in range(4))
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#c9d6e5"/>')
    for i, ch in enumerate(code):
        parts.append(
            f'<text x="{14 + i * 26}" y="{rnd.randint(24, 32)}" font-size="26" '
            f'font-family="Arial" font-weight="bold" fill="#2b6cb0" '
            f'transform="rotate({rnd.randint(-14, 14)} {14 + i * 26} 28)">{ch}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
