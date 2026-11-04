"""SQL 白名单校验（架构 8.6 / AC-AI-08）。

问数的 SQL 全部来自预置模板，LLM 不参与生成。这一层是**纵深防御**：
即使模板被改坏、或将来接入别的来源，也只有「单条 SELECT」能出去。

规则：
  1. 必须以 SELECT 开头
  2. 不允许分号（防多语句）
  3. 不允许注释符（防用注释截断后面的强制条件）
  4. 不允许写/DDL/提权关键字
  5. 必须带 LIMIT，且不得超过 5000
"""
from __future__ import annotations

import re

MAX_ROWS = 5000

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|replace|"
    r"into\s+outfile|load_file|information_schema|mysql\.|sleep|benchmark)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"(--|#|/\*)")
_SELECT = re.compile(r"^\s*select\b", re.IGNORECASE)
_LIMIT = re.compile(r"\blimit\s+(\d+)\s*$", re.IGNORECASE)


def validate(sql: str) -> tuple[bool, str | None]:
    """返回 (是否放行, 拒绝原因)。原因会写进 nl_query_log.rejected。"""
    if not sql or not sql.strip():
        return False, "空 SQL"
    if not _SELECT.match(sql):
        return False, "只允许 SELECT"
    if ";" in sql:
        return False, "禁止多语句（分号）"
    if _COMMENT.search(sql):
        return False, "禁止注释符"
    if _FORBIDDEN.search(sql):
        return False, "含写操作或敏感对象"
    m = _LIMIT.search(sql.rstrip())
    if not m:
        return False, "缺少 LIMIT"
    if int(m.group(1)) > MAX_ROWS:
        return False, f"LIMIT 超过 {MAX_ROWS}"
    return True, None


def enforce_limit(sql: str, limit: int = MAX_ROWS) -> str:
    """模板没写 LIMIT 时补上；写了不超过上限就保留。"""
    if _LIMIT.search(sql.rstrip()):
        return sql
    return f"{sql.rstrip()} LIMIT {min(limit, MAX_ROWS)}"


# ---------------------------------------------------------------- 自测
def _self_check() -> None:  # pragma: no cover
    assert validate("SELECT 1 LIMIT 10")[0]
    assert not validate("UPDATE inventory SET qty=0 LIMIT 1")[0]
    assert not validate("SELECT 1; DROP TABLE t LIMIT 1")[0]
    assert not validate("SELECT 1 -- comment\n LIMIT 5")[0]
    assert not validate("SELECT * FROM t")[0]           # 缺 LIMIT
    assert not validate("SELECT * FROM t LIMIT 99999")[0]
    assert not validate("SELECT * FROM information_schema.tables LIMIT 5")[0]
    assert enforce_limit("SELECT 1") == "SELECT 1 LIMIT 5000"
    assert enforce_limit("SELECT 1 LIMIT 10") == "SELECT 1 LIMIT 10"
    print("guard self-check ok")


if __name__ == "__main__":  # pragma: no cover
    _self_check()
