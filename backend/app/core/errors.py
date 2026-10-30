"""统一错误码与异常。码表来源：docs/WMS接口文档.md 1.2，禁止在此处新增未登记错误码。"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class Codes:
    """业务错误码。HTTP 状态码与业务码分离：传输/认证层用 HTTP，业务结果用 code。"""

    OK = "0"
    BAD_REQUEST = "WMS-4001"      # 400 参数校验失败
    UNAUTHORIZED = "WMS-4010"     # 401 未登录 / token 过期
    SIGN_INVALID = "WMS-4011"     # 401 集成端签名错误 / 时间戳超时
    FORBIDDEN = "WMS-4030"        # 403 无权限（含跨仓越权）
    REPLAY = "WMS-4091"           # 200 幂等重放（视为成功）
    ORDER_CLOSED = "WMS-4092"     # 200 单据已关闭 / 已作废
    DUPLICATE = "WMS-4093"        # 200 箱码 / SN / 条码重复
    VERSION_CONFLICT = "WMS-4094"  # 200 乐观锁版本冲突
    BIZ_RULE = "WMS-4221"         # 200 业务规则不满足
    STOCK_SHORT = "WMS-4222"      # 200 可用库存不足
    RATE_LIMIT = "WMS-4290"       # 429 限流
    SERVER_ERROR = "WMS-5000"     # 500 服务端异常


# code -> HTTP 状态码。业务类错误 HTTP 仍为 200（见接口文档 1.2 说明）。
_HTTP = {
    Codes.BAD_REQUEST: 400,
    Codes.UNAUTHORIZED: 401,
    Codes.SIGN_INVALID: 401,
    Codes.FORBIDDEN: 403,
    Codes.RATE_LIMIT: 429,
    Codes.SERVER_ERROR: 500,
}


class BizError(Exception):
    """业务异常。raise 处只写「用户看得懂的一句话」，细节进 data。"""

    def __init__(
        self,
        code: str = Codes.BIZ_RULE,
        message: str = "业务规则不满足",
        *,
        data: Any = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status or _HTTP.get(code, 200)

    def payload(self, trace_id: str) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "trace_id": trace_id,
        }


def ok(data: Any = None, message: str = "ok", trace_id: str = "") -> dict:
    return {"code": Codes.OK, "message": message, "data": data, "trace_id": trace_id}


def page(items: list, total: int, page: int, page_size: int, trace_id: str = "") -> dict:
    return ok(
        {"total": total, "page": page, "page_size": page_size, "items": items}, trace_id=trace_id
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz(request: Request, exc: BizError) -> JSONResponse:
        return JSONResponse(
            exc.payload(getattr(request.state, "trace_id", "")), status_code=exc.http_status
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {}
        for e in exc.errors():
            key = ".".join(str(x) for x in e["loc"][1:]) or "body"
            fields[key] = e["msg"]
        return JSONResponse(
            BizError(
                Codes.BAD_REQUEST, "参数校验失败", data={"fields": fields}
            ).payload(getattr(request.state, "trace_id", "")),
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = Codes.UNAUTHORIZED if exc.status_code == 401 else Codes.FORBIDDEN if exc.status_code == 403 else Codes.SERVER_ERROR
        return JSONResponse(
            BizError(code, str(exc.detail)).payload(getattr(request.state, "trace_id", "")),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        import logging

        logging.getLogger("wms").exception("unhandled error: %s", exc)
        return JSONResponse(
            BizError(Codes.SERVER_ERROR, "服务端异常，请稍后重试").payload(
                getattr(request.state, "trace_id", "")
            ),
            status_code=500,
        )
