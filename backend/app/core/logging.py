"""结构化日志：JSON 单行，字段与架构 9.5 对齐（ts, level, trace_id, user_id, path, latency_ms, code）。"""
import logging
import sys
from datetime import datetime, timezone

_TRACE_FIELDS = ("trace_id", "user_id", "path", "latency_ms", "code")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for f in _TRACE_FIELDS:
            v = getattr(record, f, None)
            if v is not None:
                payload[f] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("wms")
    root.handlers = [handler]
    root.setLevel(level)
    root.propagate = False
    # uvicorn 的 access log 也会打到 stdout，保持同一格式太吵，压到 WARNING
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str = "wms") -> logging.Logger:
    return logging.getLogger(name)
