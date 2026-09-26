"""Paschen 曲线扫描：在一段 pd 区间上实时逐点调用核算内核。

扫描不烘焙任何曲线——每个采样点都调用与单点接口完全相同的
``physics.breakdown_voltage``（固定 A、B、gamma，逐点构造 p=pd、d=1 的
等价工况），保证两个接口同源。落在对数非法区域（p*d <= L/A）的点标记为
``breakable=False`` 而不是静默跳过，U 形（含发散边界）因此被如实保留。
"""

from __future__ import annotations

from dataclasses import dataclass

from .physics import (
    Branch,
    PaschenDomainError,
    PaschenMinimum,
    breakdown_voltage,
    paschen_minimum,
)
from .validation import require_positive_finite


@dataclass(frozen=True)
class ScanPoint:
    index: int
    pd: float
    branch: str
    breakable: bool
    breakdown_voltage: float | None
    reason: str | None


@dataclass(frozen=True)
class ScanResult:
    a: float
    b: float
    gamma: float
    pd_min: float
    vs_min: float
    pd_start: float
    pd_end: float
    num_points: int
    points: list[ScanPoint]
    observed_minimum_pd: float | None  # 实际可击穿采样点中的最小 Vs 位置
    observed_minimum_vs: float | None


def scan_curve(
    a: float,
    b: float,
    gamma: float,
    pd_start: float,
    pd_end: float,
    num_points: int,
) -> ScanResult:
    """在 [pd_start, pd_end] 上均匀取 num_points 个点逐点核算。

    非法工况（不存在自持放电）的采样点照常返回，仅标记 ``breakable=False``
    并给出原因；因此调用方可以看到左支边界处的发散与整段不可击穿区间。
    """
    if not isinstance(num_points, int) or isinstance(num_points, bool) or num_points < 2:
        raise PaschenDomainError(
            f"num_points 必须是不小于 2 的整数，收到 {num_points!r}",
            code="invalid_num_points",
        )
    cleaned = require_positive_finite(
        A=a, B=b, gamma=gamma, pd_start=pd_start, pd_end=pd_end
    )
    a, b, gamma = cleaned["A"], cleaned["B"], cleaned["gamma"]
    pd_start, pd_end = cleaned["pd_start"], cleaned["pd_end"]
    if pd_end <= pd_start:
        raise PaschenDomainError(
            f"pd_end ({pd_end:g}) 必须严格大于 pd_start ({pd_start:g})",
            code="invalid_pd_range",
        )

    minimum: PaschenMinimum = paschen_minimum(a, b, gamma)

    points: list[ScanPoint] = []
    observed_min_pd: float | None = None
    observed_min_vs: float | None = None

    last = num_points - 1
    for i in range(num_points):
        pd_i = pd_start if last == 0 else (
            pd_start + (pd_end - pd_start) * i / last
        )
        try:
            # p=pd_i、d=1：Paschen 定律只依赖 pd 乘积，
            # 单点接口的全部规则（含非法域判定）原样适用，保证同源。
            result = breakdown_voltage(pd_i, 1.0, a, b, gamma)
            point = ScanPoint(
                index=i,
                pd=pd_i,
                branch=result.branch.value,
                breakable=True,
                breakdown_voltage=result.breakdown_voltage,
                reason=None,
            )
            # 统计的是本次扫描"实际观测到"的最小击穿电压：凡可击穿的采样点
            # 都参与比较，与它位于左支/右支无关。左支上 pd 越接近 pd_min、
            # Vs 越低——整段窗口压在 pd_min 左侧时，最小电压出现在最右端点，
            # 不能因为没覆盖到理论最小点就把整段排除。
            if observed_min_vs is None or result.breakdown_voltage < observed_min_vs:
                observed_min_vs = result.breakdown_voltage
                observed_min_pd = pd_i
        except PaschenDomainError as exc:
            # 左支边界以内（p*d <= L/A）的采样：不跳过、不凑数，如实标记。
            point = ScanPoint(
                index=i,
                pd=pd_i,
                branch=classify_scan_branch(pd_i, minimum.pd_min),
                breakable=False,
                breakdown_voltage=None,
                reason=exc.reason,
            )
        points.append(point)

    return ScanResult(
        a=a,
        b=b,
        gamma=gamma,
        pd_min=minimum.pd_min,
        vs_min=minimum.breakdown_voltage_min,
        pd_start=pd_start,
        pd_end=pd_end,
        num_points=num_points,
        points=points,
        observed_minimum_pd=observed_min_pd,
        observed_minimum_vs=observed_min_vs,
    )


def classify_scan_branch(pd_value: float, pd_min: float) -> str:
    """不可击穿点也需要标注它在最小点的哪一侧。"""
    tol = 1e-9 * max(1.0, abs(pd_min))
    if abs(pd_value - pd_min) <= tol:
        return Branch.MINIMUM.value
    return Branch.LEFT.value if pd_value < pd_min else Branch.RIGHT.value
