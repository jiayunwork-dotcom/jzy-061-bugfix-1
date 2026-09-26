"""Paschen 击穿核算物理内核（纯函数，无 I/O，单源真相）。

物理模型
--------
均匀电场下气体自持放电（Townsend 判据）给出 Paschen 击穿电压::

    Vs = B * p * d / ln( A * p * d / ln(1 + 1/gamma) )

记 ``L = ln(1 + 1/gamma)``、``x = p*d``，要求对数量的真数 ``A*x/L`` 严格大于 1，
否则不存在自持放电。令真数恰为 1 的临界 pd 为 ``x_tip = L/A``，在该处
``ln(...) -> 0`` 且 Vs -> +inf；在 ``x -> +inf`` 一侧 Vs 近似线性抬升。
处在两者之间时 Vs 取到唯一的全局最小值::

    pd_min = e * L / A
    Vs_min = B * pd_min

曲线在 ``pd_min`` 两侧均抬高（左支随 pd 增大而下降，右支随 pd 增大而上升），
同一个高于 Vs_min 的电压通常对应左右两个 pd 解。

单位说明
--------
p、d、A、B 只需自洽：A 的量纲为 1/(p*d)，B 的量纲为 Vs/(p*d)。
空气示例采用经典 Paschen 文献的 (Torr, cm, V) 单位组合（见 ``presets.py``）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Branch(str, Enum):
    """采样点相对最小击穿电压点 (pd_min) 所在的支。"""

    LEFT = "left"      # pd < pd_min，pd 增大时 Vs 下降
    RIGHT = "right"    # pd > pd_min，pd 增大时 Vs 上升
    MINIMUM = "minimum"  # pd ≈ pd_min


@dataclass(frozen=True)
class PaschenResult:
    """单点核算结果（电压等均为有限正数，调用方已保证可击穿）。"""

    pd: float          # p*d
    breakdown_voltage: float  # Vs
    branch: Branch
    pd_min: float      # 同一组 A、gamma 下的理论最小点
    vs_min: float      # 同一组 A、B、gamma 下的最小击穿电压
    secondary_log: float  # L = ln(1 + 1/gamma)，便于复核分母项


@dataclass(frozen=True)
class PaschenMinimum:
    """Paschen 曲线的最小点。"""

    pd_min: float
    breakdown_voltage_min: float


class PaschenDomainError(ValueError):
    """输入在物理上不成立（非正/非有限/不存在自持放电）。

    ``reason`` 是面向调用方的中文原因说明，随错误 JSON 原样返回。
    """

    def __init__(self, reason: str, code: str = "invalid_operating_condition"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


# 数学上的临界点：ln(1+1/gamma) 是整个公式分母里绝不能漏掉或挪错位置的一项。
def secondary_emission_log(gamma: float) -> float:
    """L = ln(1 + 1/gamma)。要求 gamma > 0。"""
    return math.log1p(1.0 / gamma)


def paschen_minimum(a: float, b: float, gamma: float) -> PaschenMinimum:
    """理论最小点：pd_min = e*ln(1+1/gamma)/A，Vs_min = B*pd_min。"""
    log_l = secondary_emission_log(gamma)
    pd_min = math.e * log_l / a
    return PaschenMinimum(pd_min=pd_min, breakdown_voltage_min=b * pd_min)


def classify_branch(pd: float, pd_min: float, rel_tol: float = 1e-9) -> Branch:
    """按 pd 与 pd_min 的关系判定左支/右支/最小点。"""
    tol = rel_tol * max(1.0, abs(pd_min))
    if abs(pd - pd_min) <= tol:
        return Branch.MINIMUM
    return Branch.LEFT if pd < pd_min else Branch.RIGHT


def breakdown_voltage(
    p: float,
    d: float,
    a: float,
    b: float,
    gamma: float,
) -> PaschenResult:
    """计算单工况击穿电压并判定所在支。

    输入（按顺序）校验：
      1. 五个量都必须是有限实数；
      2. p、d、A、B、gamma 都必须严格为正；
      3. 对数量真数 A*p*d / ln(1+1/gamma) 必须严格大于 1，
         否则不存在自持放电（真数 == 1 时 Vs 发散为 +inf，同样拒绝）。

    任何不满足都抛 :class:`PaschenDomainError`，绝不返回凑出来的值。
    """
    kwargs = {"p": p, "d": d, "A": a, "B": b, "gamma": gamma}
    for name, value in kwargs.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PaschenDomainError(
                f"参数 {name} 必须是数值，收到 {value!r}",
                code="non_numeric_input",
            )
        value = float(value)
        if not math.isfinite(value):
            raise PaschenDomainError(
                f"参数 {name} 必须是有限数值，收到 {value!r}",
                code="non_finite_input",
            )
        if value <= 0.0:
            raise PaschenDomainError(
                f"参数 {name} 必须严格为正，收到 {value!r}",
                code="non_positive_input",
            )

    p, d, a, b, gamma = float(p), float(d), float(a), float(b), float(gamma)

    log_l = secondary_emission_log(gamma)  # L = ln(1 + 1/gamma)
    pd_product = p * d
    argument = a * pd_product / log_l      # 外层 ln 的真数

    # 真数必须 > 1：等于 1 时分母为 0（Vs→∞），小于 1 时无自持放电。
    if argument <= 1.0:
        pd_tip = log_l / a
        raise PaschenDomainError(
            "不存在自持放电：Paschen 对数真数 "
            f"A*p*d/ln(1+1/gamma) = {argument:.6g} 不大于 1。"
            f"当前 p*d = {pd_product:.6g}，可击穿要求 p*d > {pd_tip:.6g}"
            f"（= ln(1+1/gamma)/A，左支边界，等于时击穿电压发散）。",
            code="no_self_sustained_discharge",
        )

    denominator = math.log(argument)
    vs = b * pd_product / denominator

    if not math.isfinite(vs) or vs <= 0.0:
        # 理论上不会到达这里，作为防数值意外的最后一道闸。
        raise PaschenDomainError(
            f"击穿电压计算结果非有限或非正（Vs = {vs!r}），拒绝返回。",
            code="non_finite_result",
        )

    minimum = paschen_minimum(a, b, gamma)
    return PaschenResult(
        pd=pd_product,
        breakdown_voltage=vs,
        branch=classify_branch(pd_product, minimum.pd_min),
        pd_min=minimum.pd_min,
        vs_min=minimum.breakdown_voltage_min,
        secondary_log=log_l,
    )


def inverse_pd_for_voltage(
    vs: float,
    a: float,
    b: float,
    gamma: float,
) -> tuple[float, float] | None:
    """给定目标击穿电压，求曲线上对应的左右两个 pd 解。

    用于展示"同一电压对应两支"，不对外强制使用：
      令 y = A*x/L，则 Vs/(B*L/A) = y/ln(y) =: k。
    k > e 时有两个解 y1∈(1,e)、y2∈(e,∞)，分别对应左、右支；
    k == e 时只有最小点一个解；k < e 无解（电压低于 Vs_min）。
    """
    if not (math.isfinite(vs) and vs > 0.0 and math.isfinite(a) and a > 0.0
            and math.isfinite(b) and b > 0.0 and math.isfinite(gamma) and gamma > 0.0):
        return None
    log_l = secondary_emission_log(gamma)
    k = vs * a / (b * log_l)
    if k < math.e:
        return None

    def y_from_x(x: float) -> float:
        return a * x / log_l

    def f(y: float) -> float:
        return y / math.log(y)

    # 左解 y∈(1,e)，f 从 +inf 递减到 e：f(mid)>=k 说明根在 mid 右侧。
    lo, hi = 1.0 + 1e-12, math.e
    if k == math.e:
        y_left = y_right = math.e
    else:
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if f(mid) >= k:
                lo = mid
            else:
                hi = mid
        y_left = (lo + hi) / 2.0
        # 右解 y∈(e, 大值)
        lo, hi = math.e, math.e
        while f(hi) <= k:
            hi *= 2.0
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if f(mid) >= k:
                hi = mid
            else:
                lo = mid
        y_right = (lo + hi) / 2.0

    return log_l * y_left / a, log_l * y_right / a
