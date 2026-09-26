"""Pydantic 请求/响应模型。

校验策略：HTTP 层的字段校验只负责"必须提供、类型为数值"，物理有效性
（正数、有限、自持放电条件）交由物理内核裁决，这样错误信息能带上具体
物理原因，而不是泛泛的 422 表单错误。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BreakdownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    p: float = Field(..., description="气压（单位需与 A、B 自洽，示例为 Torr）")
    d: float = Field(..., description="极板间隙（示例为 cm）")
    A: float = Field(..., description="Paschen 第一系数")
    B: float = Field(..., description="Paschen 第二系数，单位电压/(p*d)")
    gamma: float = Field(..., description="二次电子发射系数，0 < gamma < 1 典型")
    note: str | None = Field(
        default=None, max_length=500,
        description="可选备注，随核算记录一起留痕",
    )


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    A: float
    B: float
    gamma: float
    pd_start: float = Field(..., description="扫描区间起点（p*d），必须为正")
    pd_end: float = Field(..., description="扫描区间终点（p*d），必须大于起点")
    num_points: int = Field(200, ge=2, le=5000, description="均匀采样点数（含端点）")
    persist: bool = Field(
        True, description="是否把本次扫描的汇总（含每个点）落库留痕"
    )
    note: str | None = Field(default=None, max_length=500)


class ErrorResponse(BaseModel):
    error: str = Field(..., description="错误码，如 non_positive_input")
    reason: str = Field(..., description="中文原因说明")
    detail: dict | None = None


class BreakdownResponse(BaseModel):
    p: float
    d: float
    A: float
    B: float
    gamma: float
    pd: float = Field(..., description="气压与间隙的乘积 p*d")
    breakdown_voltage: float = Field(..., description="击穿电压 Vs（伏，随单位自洽）")
    breakdown_voltage_kv: float
    branch: Literal["left", "right", "minimum"]
    branch_description: str
    pd_min: float = Field(..., description="该气体系数下曲线最低点的 pd")
    vs_min: float = Field(..., description="最小击穿电压")
    secondary_log: float = Field(
        ..., description="ln(1+1/gamma)，自持条件分母项，供复核"
    )
    record_id: int | None = Field(None, description="留痕记录 ID（未启用持久化时为空）")


class ScanPointModel(BaseModel):
    index: int
    pd: float
    breakdown_voltage: float | None
    breakdown_voltage_kv: float | None
    branch: Literal["left", "right", "minimum"]
    breakable: bool
    reason: str | None = None


class ScanResponse(BaseModel):
    A: float
    B: float
    gamma: float
    pd_start: float
    pd_end: float
    num_points: int
    pd_min: float
    vs_min: float
    observed_minimum_pd: float | None = Field(
        ..., description="本次实际采样中可击穿点的最小 Vs 所在 pd"
    )
    observed_minimum_vs: float | None
    num_breakable: int
    num_unbreakable: int
    points: list[ScanPointModel]
    record_id: int | None = None


class ExampleResponse(BaseModel):
    p: float
    d: float
    A: float
    B: float
    gamma: float
    units: dict[str, str]
    description: str
    source: str
    expected_voltage_order_volts: list[float]
    computed: BreakdownResponse
