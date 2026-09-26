"""HTTP 路由：单点核算、曲线扫描、示例参数、留痕查询。只提供 JSON API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import repository, service
from ..db import get_session
from ..physics import PaschenDomainError
from ..presets import AIR_EXAMPLE
from ..schemas import (
    BreakdownRequest,
    BreakdownResponse,
    ExampleResponse,
    ScanRequest,
    ScanResponse,
)

router = APIRouter()


@router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "paschen-breakdown"}


@router.post("/api/v1/breakdown", response_model=BreakdownResponse,
             tags=["breakdown"])
async def breakdown(
    req: BreakdownRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BreakdownResponse:
    try:
        payload = await service.compute_single(
            session if _persist_on(request) else None,
            p=req.p, d=req.d, a=req.A, b=req.B, gamma=req.gamma,
            note=req.note,
        )
    except PaschenDomainError as exc:
        return _domain_http(exc)
    return BreakdownResponse(**payload)


@router.post("/api/v1/scan", response_model=ScanResponse, tags=["scan"])
async def scan(req: ScanRequest,
               session: AsyncSession = Depends(get_session)) -> ScanResponse:
    try:
        payload = await service.compute_scan(
            session if req.persist else None,
            a=req.A, b=req.B, gamma=req.gamma,
            pd_start=req.pd_start, pd_end=req.pd_end,
            num_points=req.num_points, note=req.note,
            persist=req.persist,
        )
    except PaschenDomainError as exc:
        return _domain_http(exc)
    return ScanResponse(**payload)


@router.get("/api/v1/example/air", response_model=ExampleResponse,
            tags=["example"])
async def air_example(
    session: AsyncSession = Depends(get_session),
) -> ExampleResponse:
    """预置空气示例：当场调用核算内核计算，绝不写死数值。"""
    payload = await service.compute_single(
        session,
        p=AIR_EXAMPLE.p, d=AIR_EXAMPLE.d, a=AIR_EXAMPLE.a, b=AIR_EXAMPLE.b,
        gamma=AIR_EXAMPLE.gamma,
        note="preset air example (760 Torr, 1 mm)",
    )
    return ExampleResponse(
        p=AIR_EXAMPLE.p,
        d=AIR_EXAMPLE.d,
        A=AIR_EXAMPLE.a,
        B=AIR_EXAMPLE.b,
        gamma=AIR_EXAMPLE.gamma,
        units={"p": AIR_EXAMPLE.p_unit, "d": AIR_EXAMPLE.d_unit,
               "A": f"1/({AIR_EXAMPLE.p_unit}*{AIR_EXAMPLE.d_unit})",
               "B": f"V/({AIR_EXAMPLE.p_unit}*{AIR_EXAMPLE.d_unit})",
               "breakdown_voltage": "V"},
        description=AIR_EXAMPLE.description,
        source=AIR_EXAMPLE.source,
        expected_voltage_order_volts=list(
            AIR_EXAMPLE.expected_voltage_order_volts
        ),
        computed=BreakdownResponse(**payload),
    )


@router.get("/api/v1/records", tags=["records"])
async def get_records(
    limit: int = 50,
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """列出最近的留痕记录（倒序），便于事后追溯。"""
    limit = max(1, min(limit, 500))
    if kind not in (None, "single", "scan"):
        raise HTTPException(status_code=400, detail={
            "error": "invalid_kind",
            "reason": "kind 只能是 single 或 scan",
        })
    rows = await repository.list_recent(session, limit=limit, kind=kind)
    return {
        "count": len(rows),
        "records": [_record_brief(r) for r in rows],
    }


@router.get("/api/v1/records/{record_id}", tags=["records"])
async def get_record(record_id: int,
                     session: AsyncSession = Depends(get_session)) -> dict:
    row = await repository.get_record(session, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "error": "record_not_found",
            "reason": f"记录 {record_id} 不存在",
        })
    brief = _record_brief(row)
    brief["inputs"] = row.inputs
    brief["outputs"] = row.outputs
    return brief


def _persist_on(request: Request) -> bool:
    # 单点接口可用 ?persist=false 临时不落库；默认落库。
    flag = request.query_params.get("persist", "true").lower()
    return flag not in ("0", "false", "no", "off")


def _domain_http(exc: PaschenDomainError) -> JSONResponse:
    """物理域错误：统一返回顶层 {error, reason} 的 422 JSON。"""
    return JSONResponse(
        status_code=422,
        content={"error": exc.code, "reason": exc.reason},
    )


def _record_brief(row) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "success": row.success,
        "p": row.p,
        "d": row.d,
        "A": row.a_coeff,
        "B": row.b_coeff,
        "gamma": row.gamma,
        "pd": row.pd_value,
        "breakdown_voltage": row.breakdown_voltage,
        "branch": row.branch,
        "note": row.note,
        "error_code": row.error_code,
        "error_reason": row.error_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
