"""留痕仓储：把核算输入/结果序列化为独立行。只追加，不更新历史行。

并发安全说明
~~~~~~~~~~~~
每次核算都是一条独立 INSERT，主键由数据库序列分配，多个并发请求因此只会
各自拿到各自的自增 id，不共享可变状态，天然不会相互覆盖或串号。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CalculationRecord


async def save_single(
    session: AsyncSession,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    p: float | None,
    d: float | None,
    a: float,
    b: float,
    gamma: float,
    pd_value: float | None,
    breakdown_voltage: float | None,
    branch: str | None,
    note: str | None,
    success: bool = True,
    error_code: str | None = None,
    error_reason: str | None = None,
) -> int:
    record = CalculationRecord(
        kind="single",
        p=p,
        d=d,
        a_coeff=a,
        b_coeff=b,
        gamma=gamma,
        pd_value=pd_value,
        breakdown_voltage=breakdown_voltage,
        branch=branch,
        success=success,
        note=note,
        inputs=inputs,
        outputs=outputs,
        error_code=error_code,
        error_reason=error_reason,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record.id


async def save_scan(
    session: AsyncSession,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    a: float,
    b: float,
    gamma: float,
    note: str | None,
    success: bool = True,
    error_code: str | None = None,
    error_reason: str | None = None,
) -> int:
    record = CalculationRecord(
        kind="scan",
        a_coeff=a,
        b_coeff=b,
        gamma=gamma,
        success=success,
        note=note,
        inputs=inputs,
        outputs=outputs,
        error_code=error_code,
        error_reason=error_reason,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record.id


async def list_recent(
    session: AsyncSession, limit: int = 50, kind: str | None = None
) -> list[CalculationRecord]:
    stmt = select(CalculationRecord).order_by(
        CalculationRecord.id.desc()
    ).limit(limit)
    if kind is not None:
        stmt = stmt.where(CalculationRecord.kind == kind)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_record(
    session: AsyncSession, record_id: int
) -> CalculationRecord | None:
    result = await session.execute(
        select(CalculationRecord).where(CalculationRecord.id == record_id)
    )
    return result.scalar_one_or_none()
