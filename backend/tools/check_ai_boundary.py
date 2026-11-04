"""AI 层边界检查（架构 8.1 第二道锁）。

`app/ai/**` 不允许：
  1. import 写会话（get_session / SessionLocal / engine）
  2. 出现 commit() —— AI 只能算，不能写

不靠人记：CI / pre-commit 跑这个脚本即可。用法：
    python tools/check_ai_boundary.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
AI_DIR = ROOT / "app" / "ai"

FORBIDDEN = [
    (re.compile(r"\bfrom\s+app\.core\.db\s+import\b.*\b(get_session|SessionLocal|engine)\b"),
     "import 了写会话"),
    (re.compile(r"\bimport\s+app\.core\.db\s+as\b"),
     "import 了 app.core.db（可能拿到写引擎）"),
    (re.compile(r"\.commit\s*\("), "调用了 commit()"),
]

# 允许的例外：AI 写入「建议/反馈/埋点」时由调用方传入写 session。
# 这类写入发生在 app/ai/service.py 的 save_suggestion / record_feedback 等函数里，
# 但为了不把规则做成摆设，这里仍然要求 service.py 里 commit 只出现在显式白名单函数中。
COMMIT_ALLOWED_FUNCS = {"save_suggestion", "record_feedback", "record_metric"}


def _current_func(lines: list[str], idx: int) -> str:
    for i in range(idx, -1, -1):
        m = re.match(r"def\s+(\w+)\(", lines[i])
        if m:
            return m.group(1)
    return ""


def main() -> int:
    problems: list[str] = []
    for path in sorted(AI_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue
            for pattern, why in FORBIDDEN:
                if not pattern.search(line):
                    continue
                if why == "调用了 commit()":
                    fn = _current_func(lines, i - 1)
                    if fn in COMMIT_ALLOWED_FUNCS:
                        continue
                problems.append(f"{path.relative_to(ROOT)}:{i}  {why}：{line.strip()}")

    if problems:
        print("AI 层边界检查未通过：")
        for p in problems:
            print("  " + p)
        return 1
    print(f"ai boundary ok（{len(list(AI_DIR.rglob('*.py')))} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
