"""FastAPI 入口：仅经 HTTP 提供 Paschen 气体击穿核算 JSON API，无前端页面。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import init_db
from .routers.calculations import router as calc_router

logger = logging.getLogger("paschen")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即建表；数据库未就绪时让容器编排负责重启（见 docker-compose）。
    try:
        await init_db()
    except Exception:  # noqa: BLE001
        logger.exception("启动时建表失败，将继续启动以便 /health 可用")
    yield


app = FastAPI(
    title="Paschen 气体击穿核算后端",
    description=(
        "均匀电场下气体击穿电压（Paschen 定律）的 HTTP 计算服务：\n"
        "- POST /api/v1/breakdown 单点核算（Vs、pd、左/右支判定）\n"
        "- POST /api/v1/scan 固定气体系数扫描整条 U 形曲线\n"
        "- GET  /api/v1/example/air 可复核的空气示例\n"
        "- GET  /api/v1/records 历次核算留痕\n"
        "全部输入 p、d、A、B、gamma 必须为正且有限；不满足自持放电条件的工"
        "况返回带原因的 422 错误 JSON，绝不凑数。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(calc_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """把请求层校验错误统一为 {error, reason, detail} 的错误 JSON。"""
    locs = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        locs.append(f"{loc}: {err.get('msg', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "invalid_request",
            "reason": "请求参数校验未通过：" + "；".join(locs),
            "detail": {"errors": exc.errors()},
        },
    )


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    # 无前端页面：根路径只做服务自指，接口清单见 /docs（OpenAPI）。
    return {"service": "paschen-breakdown", "docs": "/docs", "health": "/health"}
