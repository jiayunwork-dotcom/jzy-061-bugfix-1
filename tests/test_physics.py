"""物理内核的硬不变量测试（不依赖 HTTP 与数据库）。

锁住的关系：
- 空气示例击穿电压在千伏量级、为正有限；
- p、d 互换而乘积不变时 Vs 完全不变；
- 间隙加倍只让工况沿曲线平移，Vs 不是简单翻倍；
- gamma 增大，Vs 整体下降；
- pd_min 处取最小，向两侧偏离都回升；扫描逼近 pd_min 时得区间最小；
- 非法输入（非正/非有限/无自持放电）一律带原因拒绝；
- ln(1+1/gamma) 一旦漏放或挪错，pd_min 位置必漂移——用精确值锁死。
"""

from __future__ import annotations

import math

import pytest

from app.physics import (
    Branch,
    PaschenDomainError,
    breakdown_voltage,
    inverse_pd_for_voltage,
    paschen_minimum,
    secondary_emission_log,
)
from app.presets import AIR_EXAMPLE
from app.scanning import scan_curve

AIR = dict(a=AIR_EXAMPLE.a, b=AIR_EXAMPLE.b, gamma=AIR_EXAMPLE.gamma)


def test_air_example_kilovolt_magnitude_positive_finite():
    r = breakdown_voltage(AIR_EXAMPLE.p, AIR_EXAMPLE.d,
                          AIR_EXAMPLE.a, AIR_EXAMPLE.b, AIR_EXAMPLE.gamma)
    lo, hi = AIR_EXAMPLE.expected_voltage_order_volts
    assert math.isfinite(r.breakdown_voltage)
    assert r.breakdown_voltage > 0
    assert lo <= r.breakdown_voltage <= hi
    # 76 Torr·cm 远大于 pd_min，落在右支。
    assert r.branch is Branch.RIGHT


def test_pd_swap_invariance():
    """p 与 d 互换、乘积不变 => Vs 完全一致（且支别一致）。"""
    p, d = 380.0, 0.2
    r1 = breakdown_voltage(p, d, **AIR)
    r2 = breakdown_voltage(d, p, **AIR)
    r3 = breakdown_voltage(76.0, 1.0, **AIR)
    assert r1.pd == r2.pd == r3.pd == pytest.approx(76.0)
    assert r1.breakdown_voltage == pytest.approx(r2.breakdown_voltage, rel=1e-14)
    assert r2.breakdown_voltage == pytest.approx(r3.breakdown_voltage, rel=1e-14)
    assert r1.branch == r2.branch == r3.branch


def test_doubling_gap_moves_along_curve_not_doubling_voltage():
    """d 加倍 => pd 加倍，Vs 随曲线走，绝不等于简单翻倍。"""
    base = breakdown_voltage(760.0, 0.1, **AIR)   # pd = 76，右支
    doubled = breakdown_voltage(760.0, 0.2, **AIR)  # pd = 152
    assert doubled.pd == pytest.approx(base.pd * 2)
    assert doubled.breakdown_voltage != pytest.approx(
        base.breakdown_voltage * 2, rel=1e-6
    )
    # 右支上 pd 增大 Vs 增大，但增幅远小于翻倍（被对数项抑制）。
    assert doubled.breakdown_voltage > base.breakdown_voltage
    assert doubled.breakdown_voltage < base.breakdown_voltage * 2

    # 左支上加倍反而使 Vs 下降（趋向最小点），证明不是单调实现。
    # pd_min≈1.115、左支可击穿边界 L/A≈0.41：取 pd=0.5 与 1.0 都在左支。
    left1 = breakdown_voltage(0.5, 1.0, **AIR)
    left2 = breakdown_voltage(1.0, 1.0, **AIR)
    pd_min = paschen_minimum(**AIR).pd_min
    assert left1.pd < left2.pd < pd_min
    assert left1.branch is Branch.LEFT and left2.branch is Branch.LEFT
    assert left2.breakdown_voltage < left1.breakdown_voltage


def test_increasing_gamma_lowers_voltage():
    """gamma 增大（更易发射二次电子）=> 同一 pd 下 Vs 整体下降。"""
    gammas = [1e-4, 1e-3, 1e-2, 1e-1, 0.5]
    voltages = [
        breakdown_voltage(760.0, 0.1, AIR_EXAMPLE.a, AIR_EXAMPLE.b, g).breakdown_voltage
        for g in gammas
    ]
    assert all(v1 > v2 for v1, v2 in zip(voltages, voltages[1:]))


def test_gamma_effect_holds_across_whole_curve():
    """gamma 增大使 Vs 在左右两支的整个 pd 网格上都严格下降。"""
    g_low, g_high = 1e-3, 5e-2
    # 网格起点需大于 gamma=1e-3 的左支边界 L/A ≈ 0.614，覆盖左右两支
    grid = [0.7, 1.0, 1.5, 3.0, 10.0, 76.0, 300.0]
    for x in grid:
        v_low = breakdown_voltage(x, 1.0, AIR_EXAMPLE.a, AIR_EXAMPLE.b, g_low)
        v_high = breakdown_voltage(x, 1.0, AIR_EXAMPLE.a, AIR_EXAMPLE.b, g_high)
        assert v_high.breakdown_voltage < v_low.breakdown_voltage, x
        # gamma 增大同时把最小点向左移（L 减小）
    assert paschen_minimum(AIR_EXAMPLE.a, AIR_EXAMPLE.b, g_high).pd_min < \
           paschen_minimum(AIR_EXAMPLE.a, AIR_EXAMPLE.b, g_low).pd_min


def test_scan_all_unbreakable_window_has_none_observed_minimum():
    """整段窗口都在非法域：观测最小为 None、每点带原因，端点不丢。"""
    pd_tip = secondary_emission_log(AIR_EXAMPLE.gamma) / AIR_EXAMPLE.a
    scan = scan_curve(AIR_EXAMPLE.a, AIR_EXAMPLE.b, AIR_EXAMPLE.gamma,
                      pd_tip * 0.05, pd_tip * 0.5, 20)
    assert scan.observed_minimum_pd is None
    assert scan.observed_minimum_vs is None
    assert scan.num_points == 20
    assert all(not p.breakable and p.reason for p in scan.points)
    assert len({p.pd for p in scan.points}) == 20  # pd 各不相同


def test_minimum_location_formula_exact():
    """pd_min = e*ln(1+1/gamma)/A、Vs_min = B*pd_min，数值精确锁定。

    若实现把 ln(1+1/gamma) 从分母里漏掉或挪错位置，该用例必失败。
    """
    for a, b, g in [(11.25, 273.75, 0.01), (15.0, 365.0, 0.001),
                    (8.44, 205.3, 0.1)]:
        m = paschen_minimum(a, b, g)
        expected_pd_min = math.e * math.log1p(1.0 / g) / a
        assert m.pd_min == pytest.approx(expected_pd_min, rel=1e-15)
        assert m.breakdown_voltage_min == pytest.approx(b * expected_pd_min, rel=1e-15)

        # 最小点处直接核算也取到同一电压，且标为 minimum。
        at_min = breakdown_voltage(m.pd_min, 1.0, a, b, g)
        assert at_min.branch is Branch.MINIMUM
        assert at_min.breakdown_voltage == pytest.approx(
            m.breakdown_voltage_min, rel=1e-12
        )


def test_curve_is_u_shaped_around_minimum():
    """在 pd_min 左右等距（乘法意义上）偏离，Vs 都严格回升。"""
    m = paschen_minimum(**AIR)
    v_at_min = breakdown_voltage(m.pd_min, 1.0, **AIR).breakdown_voltage
    for factor in (0.5, 0.8, 1.25, 2.0, 5.0):
        r = breakdown_voltage(m.pd_min * factor, 1.0, **AIR)
        assert r.breakdown_voltage > v_at_min
        assert r.branch is (Branch.LEFT if factor < 1 else Branch.RIGHT)


def test_scan_realtime_and_minimum_within_window():
    """扫描点实时算出；窗口包含 pd_min 时，观测最小点逼近理论最小点，
    且两侧点电压都更高。"""
    m = paschen_minimum(**AIR)
    scan = scan_curve(AIR_EXAMPLE.a, AIR_EXAMPLE.b, AIR_EXAMPLE.gamma,
                      m.pd_min * 0.5, m.pd_min * 2.0, 401)
    breakable = [p for p in scan.points if p.breakable]
    assert len(breakable) == 401
    assert scan.pd_min == pytest.approx(m.pd_min, rel=1e-15)
    assert scan.vs_min == pytest.approx(m.breakdown_voltage_min, rel=1e-15)

    # 采样观测到的最小电压不小于理论最小，且十分接近。
    assert scan.observed_minimum_vs >= m.breakdown_voltage_min
    assert scan.observed_minimum_vs == pytest.approx(
        m.breakdown_voltage_min, rel=2e-3
    )
    obs_idx = next(p.index for p in scan.points
                   if p.pd == scan.observed_minimum_pd)
    voltages = [p.breakdown_voltage for p in scan.points]
    assert voltages[obs_idx] < voltages[0]
    assert voltages[obs_idx] < voltages[-1]
    # 左半段单调下降、右半段单调上升（网格点上验证 U 形不是写死的形状）。
    left_v = [p.breakdown_voltage for p in scan.points if p.branch == "left"]
    right_v = [p.breakdown_voltage for p in scan.points if p.branch == "right"]
    assert all(x > y for x, y in zip(left_v, left_v[1:]))
    assert all(x < y for x, y in zip(right_v, right_v[1:]))


def test_scan_marks_unbreakable_points_instead_of_skipping():
    """扫描区间覆盖非法域时，非法点标记 breakable=False 并带原因，不跳过。"""
    pd_tip = secondary_emission_log(AIR_EXAMPLE.gamma) / AIR_EXAMPLE.a
    scan = scan_curve(AIR_EXAMPLE.a, AIR_EXAMPLE.b, AIR_EXAMPLE.gamma,
                      pd_tip * 0.2, pd_tip * 3.0, 121)
    assert len(scan.points) == 121
    bad = [p for p in scan.points if not p.breakable]
    good = [p for p in scan.points if p.breakable]
    assert bad and good
    for p in bad:
        assert p.breakdown_voltage is None
        assert p.reason and "自持放电" in p.reason
        assert p.branch == "left"  # 非法域只可能在左支边界以内
    for p in good:
        assert p.breakdown_voltage is not None and p.breakdown_voltage > 0


def test_two_inverse_branches_share_voltage():
    """同一高于 Vs_min 的电压对应左右两个 pd 解，且两支解回算电压一致。"""
    m = paschen_minimum(**AIR)
    target = m.breakdown_voltage_min * 2.0
    pair = inverse_pd_for_voltage(target, AIR_EXAMPLE.a, AIR_EXAMPLE.b,
                                  AIR_EXAMPLE.gamma)
    assert pair is not None
    x_left, x_right = pair
    assert x_left < m.pd_min < x_right
    for x in (x_left, x_right):
        r = breakdown_voltage(x, 1.0, **AIR)
        assert r.breakdown_voltage == pytest.approx(target, rel=1e-9)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (dict(p=0, d=1, a=1, b=1, g=0.01), "严格为正"),
        (dict(p=-1, d=1, a=1, b=1, g=0.01), "严格为正"),
        (dict(p=1, d=0, a=1, b=1, g=0.01), "严格为正"),
        (dict(p=1, d=1, a=0, b=1, g=0.01), "严格为正"),
        (dict(p=1, d=1, a=1, b=-2, g=0.01), "严格为正"),
        (dict(p=1, d=1, a=1, b=1, g=0), "严格为正"),
        (dict(p=float("nan"), d=1, a=1, b=1, g=0.01), "有限"),
        (dict(p=1, d=1, a=1, b=1, g=float("inf")), "有限"),
    ],
)
def test_non_positive_or_non_finite_inputs_rejected(kwargs, match):
    with pytest.raises(PaschenDomainError) as exc_info:
        breakdown_voltage(kwargs["p"], kwargs["d"], kwargs["a"],
                          kwargs["b"], kwargs["g"])
    assert match in exc_info.value.reason
    assert exc_info.value.code in (
        "non_positive_input", "non_finite_input", "non_numeric_input")


def test_below_self_sustained_threshold_rejected_with_reason():
    """A*pd/L <= 1（不存在自持放电）必须拒绝并给出临界 pd，而不是凑数。"""
    pd_tip = secondary_emission_log(AIR_EXAMPLE.gamma) / AIR_EXAMPLE.a
    # pd = 0.5*tip 时真数 = 0.5
    with pytest.raises(PaschenDomainError) as exc_info:
        breakdown_voltage(pd_tip * 0.5, 1.0, **AIR)
    assert exc_info.value.code == "no_self_sustained_discharge"
    assert "0.5" in exc_info.value.reason
    assert "自持放电" in exc_info.value.reason
    # 恰好在边界（真数 = 1，Vs 发散）同样拒绝。
    with pytest.raises(PaschenDomainError):
        breakdown_voltage(pd_tip, 1.0, **AIR)
    # 刚越过边界即合法。
    r = breakdown_voltage(pd_tip * 1.0001, 1.0, **AIR)
    assert math.isfinite(r.breakdown_voltage) and r.breakdown_voltage > 0


def test_scan_validates_range_and_points():
    with pytest.raises(PaschenDomainError):
        scan_curve(11.25, 273.75, 0.01, 10.0, 5.0, 100)
    with pytest.raises(PaschenDomainError):
        scan_curve(11.25, 273.75, 0.01, -1.0, 5.0, 100)
    with pytest.raises(PaschenDomainError):
        scan_curve(11.25, 273.75, 0.01, 1.0, 5.0, 1)
