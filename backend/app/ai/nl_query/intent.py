"""意图与槽位抽取（架构 5.5 第一步）。

**不起用 LLM**——用确定性的关键词 + 正则。理由：
  1. 同一个问题必须得到同一个结果（AC-AI-09），LLM 分类有随机性；
  2. LLM 默认关闭（LLM_BASE_URL 为空），规则版保证这条链在无外部依赖时完整可用。

要升级成 LLM 分类时，只替换 `parse()` 里的 metric 与 sku 抽取，模板与 guard 不动。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.ai.nl_query import semantics

# 形如 A3288 / BAT-LIPO-4500-003 的编码；中文正文里夹的英文串
_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b")
_SKU_LIKE = re.compile(r"[A-Z]{1,4}[0-9]{3,}|[A-Z]{2,}-[A-Z0-9-]{2,}")
# 近 N 天
_NEAR = re.compile(r"近\s*(\d+)\s*(天|日|周)")
# 明确日期 2026-01-27
_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_time(q: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now()
    today = _day_start(now)

    m = _NEAR.search(q)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * 7 if unit == "周" else n
        return today - timedelta(days=days - 1), now

    if "今天" in q or "今日" in q:
        return today, now
    if "昨天" in q or "昨日" in q:
        return today - timedelta(days=1), today
    if "本周" in q or "这周" in q:
        return today - timedelta(days=today.weekday()), now
    if "上周" in q:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=7)
    if "本月" in q:
        return today.replace(day=1), now
    if "上月" in q:
        first = today.replace(day=1)
        prev = first - timedelta(days=1)
        return prev.replace(day=1), first

    m2 = _DATE.search(q)
    if m2:
        d = datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        return d, d + timedelta(days=1)

    return semantics.default_window()


def parse_sku(q: str) -> str | None:
    """只认「像编码」的英文串，避免把「WMS」这类词当 SKU。"""
    for tok in _CODE.findall(q):
        if _SKU_LIKE.fullmatch(tok):
            return tok
    return None


def parse(q: str, now: datetime | None = None) -> dict:
    """返回 {metric, params}；未命中指标时 metric 为 None。"""
    metric = semantics.pick_metric(q)
    start, end = parse_time(q, now)
    sku = parse_sku(q)
    return {
        "metric": metric.key if metric else None,
        "params": {"start": start, "end": end, "sku_code": sku},
    }
