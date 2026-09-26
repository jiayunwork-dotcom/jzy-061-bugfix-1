"""服务层：把 HTTP 输入交给物理内核，组装响应，并负责留痕。

留痕失败不影响核算结果返回（只把 record_id 置空并记录告警），保证
"计算"这一核心能力的可用性；默认持久化开启时成功的核算必有 record_id。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import repository
from .config import get_settings
from .physics import PaschenResult, breakdown_voltage
from .scanning import ScanResult, scan_curve

logger = logging.getLogger("paschen.service")

_BRANCH_DESCRIPTIONS = {
    "left": "左支：pd < pd_min，pd 增大时击穿电压下降",
    "minimum": "最小点：pd ≈ pd_min，击穿电压取全局最小值",
    "right": "右支：pd > pd_min，pd 增大时击穿电压上升",
}


def branch_description(branch: str) -> str:
    return _BRANCH_DESCRIPTIONS[branch]


def serialize_single(result: PaschenResult, p: float, d: float,
                     a: float, b: float, gamma: float) -> dict[str, Any]:
    return {
        "p": p,
        "d": d,
        "A": a,
        "B": b,
        "gamma": gamma,
        "pd": result.pd,
        "breakdown_voltage": result.breakdown_voltage,
        "breakdown_voltage_kv": result.breakdown_voltage / 1000.0,
        "branch": result.branch.value,
        "branch_description": branch_description(result.branch.value),
        "pd_min": result.pd_min,
        "vs_min": result.vs_min,
        "secondary_log": result.secondary_log,
    }


def serialize_scan(scan: ScanResult) -> dict[str, Any]:
    points = [
        {
            "index": pt.index,
            "pd": pt.pd,
            "breakdown_voltage": pt.breakdown_voltage,
            "breakdown_voltage_kv": (
                pt.breakdown_voltage / 1000.0
                if pt.breakdown_voltage is not None
                else None
            ),
            "branch": pt.branch,
            "breakable": pt.breakable,
            "reason": pt.reason,
        }
        for pt in scan.points
    ]
    num_breakable = sum(1 for pt in scan.points if pt.breakable)
    return {
        "A": scan.a,
        "B": scan.b,
        "gamma": scan.gamma,
        "pd_start": scan.pd_start,
        "pd_end": scan.pd_end,
        "num_points": scan.num_points,
        "pd_min": scan.pd_min,
        "vs_min": scan.vs_min,
        "observed_minimum_pd": scan.observed_minimum_pd,
        "observed_minimum_vs": scan.observed_minimum_vs,
        "num_breakable": num_breakable,
        "num_unbreakable": scan.num_points - num_breakable,
        "points": points,
    }


async def compute_single(
    session: AsyncSession | None,
    *,
    p: float,
    d: float,
    a: float,
    b: float,
    gamma: float,
    note: str | None,
) -> dict[str, Any]:
    """单点核算。物理异常直接向上抛（由路由转成错误 JSON）。"""
    result = breakdown_voltage(p, d, a, b, gamma)
    payload = serialize_single(result, float(p), float(d), float(a), float(b),
                               float(gamma))
    payload["record_id"] = await _persist(
        session,
        kind="single",
        save=lambda: repository.save_single(
            session,
            inputs={"p": p, "d": d, "A": a, "B": b, "gamma": gamma, "note": note},
            outputs=payload,
            p=float(p), d=float(d), a=float(a), b=float(b), gamma=float(gamma),
            pd_value=result.pd,
            breakdown_voltage=result.breakdown_voltage,
            branch=result.branch.value,
            note=note,
        ),
    )
    return payload


async def compute_scan(
    session: AsyncSession | None,
    *,
    a: float,
    b: float,
    gamma: float,
    pd_start: float,
    pd_end: float,
    num_points: int,
    note: str | None,
    persist: bool = True,
) -> dict[str, Any]:
    scan: ScanResult = scan_curve(
        a, b, gamma, pd_start, pd_end, num_points
    )
    payload = serialize_scan(scan)
    if not persist:
        payload["record_id"] = None
        return payload
    payload["record_id"] = await _persist(
        session,
        kind="scan",
        save=lambda: repository.save_scan(
            session,
            inputs={"A": a, "B": b, "gamma": gamma,
                    "pd_start": pd_start, "pd_end": pd_end,
                    "num_points": num_points, "note": note},
            outputs=payload,
            a=float(a), b=float(b), gamma=float(gamma),
            note=note,
        ),
    )
    return payload


async def _persist(
    session: AsyncSession | None,
    *,
    kind: str,
    save: Any,
) -> int | None:
    settings = get_settings()
    if not settings.persist_enabled or session is None:
        return None
    try:
        return await save()
    except Exception:  # noqa: BLE001 - 留痕失败不应拖垮核算
        logger.exception("persisting %s calculation failed", kind)
        await session.rollback()
        return None
