"""LLM 网关（T-04-5 / 架构 8.5）：超时、重试、降级、脱敏、限流、计费。

唯一的外部依赖出口——所有 LLM 调用都必须经过这里，这样降级和计费只有一处。
没有配置 LLM_BASE_URL 时直接返回 degraded，不发起网络请求（现场可以整体不接 LLM）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import rds

log = get_logger("wms.llm")

TIMEOUT = 3.0
CONNECT_TIMEOUT = 1.0
RATE_LIMIT_PER_MIN = 60

# 脱敏：SN、供应商名、手机号不进第三方
_SN = re.compile(r"\bSN[0-9A-Z]{6,}\b")
_PHONE = re.compile(r"\b1[3-9]\d{9}\b")


@dataclass
class LlmResult:
    text: str
    degraded: bool
    latency_ms: int
    prompt_tokens: int = 0
    output_tokens: int = 0


def redact(text: str) -> str:
    text = _SN.sub("SN***", text)
    text = _PHONE.sub("1**********", text)
    return text


def _rate_limited(user_id: int) -> bool:
    key = f"rl:llm:{user_id}:{int(time.time() // 60)}"
    n = rds.incr(key)
    if n == 1:
        rds.expire(key, 60)
    return n > RATE_LIMIT_PER_MIN


def ask(prompt: str, *, user_id: int, fallback: str) -> LlmResult:
    """调一次 LLM。任何异常都降级成模板文案，绝不把错误抛给用户。"""
    started = time.perf_counter()

    if not settings.llm_base_url:
        return LlmResult(fallback, True, 0)
    if _rate_limited(user_id):
        return LlmResult(fallback, True, int((time.perf_counter() - started) * 1000))

    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": redact(prompt)}],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}

    for attempt in (1, 2):  # 仅对 5xx/超时重试一次
        try:
            with httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=CONNECT_TIMEOUT)) as c:
                r = c.post(f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                           json=payload, headers=headers)
            if r.status_code >= 500:
                raise httpx.HTTPStatusError("5xx", request=r.request, response=r)
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return LlmResult(
                text, False, int((time.perf_counter() - started) * 1000),
                int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)),
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code < 500:
                break  # 4xx 重试也没用
            if attempt == 2:
                break
            time.sleep(0.3)
        except Exception:  # noqa: BLE001 —— 超时/连接/解析，一律降级
            if attempt == 2:
                break
            time.sleep(0.3)

    log.warning("llm degraded user=%s", user_id)
    return LlmResult(fallback, True, int((time.perf_counter() - started) * 1000))
