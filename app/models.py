"""ORM 模型：每次核算一条独立记录，并发插入只追加、不覆盖、不串号。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CalculationRecord(Base):
    """单次单点核算或一次曲线扫描的留痕记录。

    每次请求插入一行（自增主键由数据库分配），因此并发提交只会各自追加，
    不存在相互覆盖；inputs/outputs 以 JSON 原样保存，可完整复盘当次参数
    与逐点结果。
    """

    __tablename__ = "calculation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # single | scan
    p: Mapped[float | None] = mapped_column(Float, nullable=True)
    d: Mapped[float | None] = mapped_column(Float, nullable=True)
    a_coeff: Mapped[float] = mapped_column(Float)
    b_coeff: Mapped[float] = mapped_column(Float)
    gamma: Mapped[float] = mapped_column(Float)
    pd_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakdown_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(8), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<CalculationRecord id={self.id} kind={self.kind} success={self.success}>"
