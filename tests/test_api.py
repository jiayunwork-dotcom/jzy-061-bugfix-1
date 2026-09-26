"""端到端 HTTP 测试：响应结构、物理不变量、非法输入错误 JSON、
留痕与并发提交不串号。"""

from __future__ import annotations

import asyncio
import math

import pytest

from app.presets import AIR_EXAMPLE

AIR_BODY = {
    "p": 760.0, "d": 0.1,
    "A": AIR_EXAMPLE.a, "B": AIR_EXAMPLE.b, "gamma": AIR_EXAMPLE.gamma,
}


async def test_health_and_root(client):
    ac, _ = client
    r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r = await ac.get("/")
    assert r.status_code == 200


async def test_breakdown_single_full_contract(client):
    ac, _ = client
    r = await ac.post("/api/v1/breakdown", json=AIR_BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pd"] == pytest.approx(76.0)
    assert body["branch"] == "right"
    assert 1e3 < body["breakdown_voltage"] < 1e4
    assert body["breakdown_voltage"] / 1000.0 == pytest.approx(
        body["breakdown_voltage_kv"])
    assert math.isfinite(body["breakdown_voltage"])
    assert body["pd_min"] > 0 and body["vs_min"] > 0
    assert body["secondary_log"] == pytest.approx(
        math.log1p(1 / AIR_EXAMPLE.gamma))
    assert isinstance(body["record_id"], int)


async def test_air_example_matches_live_computation(client):
    ac, _ = client
    r = await ac.get("/api/v1/example/air")
    assert r.status_code == 200, r.text
    body = r.json()
    lo, hi = body["expected_voltage_order_volts"]
    vs = body["computed"]["breakdown_voltage"]
    assert lo <= vs <= hi
    assert "Paschen" in body["source"] or "Cobine" in body["source"]
    # 与单点接口同源：拿示例参数再算一次必须完全一致
    r2 = await ac.post("/api/v1/breakdown", json={
        "p": body["p"], "d": body["d"], "A": body["A"], "B": body["B"],
        "gamma": body["gamma"]})
    assert r2.json()["breakdown_voltage"] == pytest.approx(vs, rel=1e-15)


async def test_pd_swap_invariant_over_http(client):
    ac, _ = client
    r1 = await ac.post("/api/v1/breakdown", json={**AIR_BODY, "p": 380, "d": 0.2})
    r2 = await ac.post("/api/v1/breakdown", json={**AIR_BODY, "p": 0.2, "d": 380})
    r3 = await ac.post("/api/v1/breakdown", json={**AIR_BODY, "p": 76, "d": 1})
    vs = [b["breakdown_voltage"] for b in (r1.json(), r2.json(), r3.json())]
    assert vs[0] == vs[1] == vs[2]


async def test_gamma_increase_decreases_voltage_over_http(client):
    ac, _ = client
    voltages = []
    for g in (1e-3, 1e-2, 1e-1):
        r = await ac.post("/api/v1/breakdown", json={**AIR_BODY, "gamma": g})
        voltages.append(r.json()["breakdown_voltage"])
    assert voltages[0] > voltages[1] > voltages[2]


async def test_invalid_inputs_return_error_json(client):
    ac, _ = client
    cases = [
        ({**AIR_BODY, "p": 0}, 422, "non_positive_input"),
        ({**AIR_BODY, "d": -0.1}, 422, "non_positive_input"),
        ({**AIR_BODY, "A": 0}, 422, "non_positive_input"),
        ({**AIR_BODY, "B": -3}, 422, "non_positive_input"),
        ({**AIR_BODY, "gamma": 0}, 422, "non_positive_input"),
        ({**AIR_BODY, "p": "abc"}, 422, None),
        ({**AIR_BODY, "extra": 1}, 422, None),
    ]
    for body, status, code in cases:
        r = await ac.post("/api/v1/breakdown", json=body)
        assert r.status_code == status, (body, r.text)
        err = r.json()
        # 物理域错误直接是顶层 {error, reason}；请求层错误也统一成同形
        assert "error" in err and "reason" in err
        if code:
            assert err["error"] == code


async def test_no_self_sustained_discharge_rejected(client):
    ac, _ = client
    # pd 小到 A*pd/ln(1+1/gamma) <= 1
    r = await ac.post("/api/v1/breakdown", json={
        **AIR_BODY, "p": 0.001, "d": 0.001})
    assert r.status_code == 422
    err = r.json()
    assert err["error"] == "no_self_sustained_discharge"
    assert "自持放电" in err["reason"]


async def test_scan_u_shape_minimum_and_unbreakable_marks(client):
    ac, _ = client
    A, B, g = AIR_EXAMPLE.a, AIR_EXAMPLE.b, AIR_EXAMPLE.gamma
    pd_min = math.e * math.log1p(1 / g) / A
    vs_min = B * pd_min
    body = {
        "A": A, "B": B, "gamma": g,
        "pd_start": pd_min * 0.3, "pd_end": pd_min * 3.0,
        "num_points": 301,
    }
    r = await ac.post("/api/v1/scan", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["pd_min"] == pytest.approx(pd_min)
    assert data["vs_min"] == pytest.approx(vs_min)
    assert data["num_unbreakable"] > 0
    assert data["num_breakable"] + data["num_unbreakable"] == 301
    points = data["points"]
    # 非法点未被跳过
    bad = [p for p in points if not p["breakable"]]
    assert bad and all(p["breakdown_voltage"] is None and p["reason"]
                       for p in bad)
    # 观测最小点逼近理论最小，且两侧回升
    assert data["observed_minimum_vs"] == pytest.approx(vs_min, rel=2e-3)
    good = [p for p in points if p["breakable"]]
    imin = min(range(len(good)), key=lambda i: good[i]["breakdown_voltage"])
    assert good[imin]["breakdown_voltage"] < good[0]["breakdown_voltage"]
    assert good[imin]["breakdown_voltage"] < good[-1]["breakdown_voltage"]
    assert good[imin]["pd"] == pytest.approx(pd_min, rel=2e-2)
    assert isinstance(data["record_id"], int)


async def test_scan_left_only_window_reports_observed_minimum(client):
    """回归：扫描窗口整段压在 pd_min 左侧（但高于自持放电临界）时，
    observed_minimum_* 曾错误返回 null。有可击穿点就必须如实报出区间最小，
    且等于逐点数据的真实最小、位置在窗口最右端。"""
    ac, _ = client
    A, B, g = AIR_EXAMPLE.a, AIR_EXAMPLE.b, AIR_EXAMPLE.gamma
    pd_min = math.e * math.log1p(1 / g) / A
    pd_tip = math.log1p(1 / g) / A
    r = await ac.post("/api/v1/scan", json={
        "A": A, "B": B, "gamma": g,
        "pd_start": pd_tip * 1.05, "pd_end": pd_min * 0.9,
        "num_points": 51})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["num_unbreakable"] == 0
    assert data["num_breakable"] == 51
    good = data["points"]
    true_min = min(p["breakdown_voltage"] for p in good)
    assert data["observed_minimum_vs"] is not None
    assert data["observed_minimum_pd"] is not None
    assert data["observed_minimum_vs"] == pytest.approx(true_min)
    # 左支一路下降：最小出现在最靠右的采样点（pd_end 处）。
    assert data["observed_minimum_pd"] == pytest.approx(good[-1]["pd"])
    assert data["observed_minimum_pd"] == pytest.approx(pd_min * 0.9)


async def test_scan_rejects_bad_range(client):
    ac, _ = client
    r = await ac.post("/api/v1/scan", json={
        "A": AIR_EXAMPLE.a, "B": AIR_EXAMPLE.b, "gamma": AIR_EXAMPLE.gamma,
        "pd_start": 10, "pd_end": 1, "num_points": 50})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_pd_range"


async def test_scan_persist_false_has_no_record(client):
    ac, maker = client
    body = {
        "A": AIR_EXAMPLE.a, "B": AIR_EXAMPLE.b, "gamma": AIR_EXAMPLE.gamma,
        "pd_start": 1.0, "pd_end": 10.0, "num_points": 20, "persist": False}
    r = await ac.post("/api/v1/scan", json=body)
    assert r.status_code == 200
    assert r.json()["record_id"] is None


async def test_records_list_and_detail(client):
    ac, _ = client
    await ac.post("/api/v1/breakdown", json=AIR_BODY)
    r = await ac.get("/api/v1/records", params={"kind": "single"})
    assert r.status_code == 200
    records = r.json()["records"]
    assert records and r.json()["count"] >= 1
    rid = records[0]["id"]
    r = await ac.get(f"/api/v1/records/{rid}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["inputs"]["A"] == AIR_EXAMPLE.a
    assert detail["outputs"]["breakdown_voltage"] > 0
    r = await ac.get("/api/v1/records/999999")
    assert r.status_code == 404

async def test_concurrent_submissions_do_not_overwrite(client):
    """并发提交多组不同核算：每条记录独立、互不串号，全部可追溯。"""
    ac, maker = client
    n = 40
    pressures = [100.0 + 5 * i for i in range(n)]

    async def submit(p):
        return await ac.post("/api/v1/breakdown",
                             json={**AIR_BODY, "p": p, "d": 0.1})

    responses = await asyncio.gather(*(submit(p) for p in pressures))
    ids = []
    seen_pressures = set()
    for p, r in zip(pressures, responses):
        assert r.status_code == 200, r.text
        body = r.json()
        ids.append(body["record_id"])
        seen_pressures.add(p)
        assert body["pd"] == pytest.approx(p * 0.1)
    assert len(set(ids)) == n  # id 唯一 => 没有覆盖/串号

    r = await ac.get("/api/v1/records", params={"limit": 500})
    records = r.json()["records"]
    assert len(records) >= n
    stored = {row["id"]: row for row in records}
    for p, rid in zip(pressures, ids):
        row = stored[rid]
        assert row["p"] == p                 # 每行记住自己的气压
        assert row["pd"] == pytest.approx(p * 0.1)
        # 明细里的 JSON 输入快照同样不串号
        detail = (await ac.get(f"/api/v1/records/{rid}")).json()
        assert detail["inputs"]["p"] == p
        assert detail["outputs"]["p"] == p
        assert detail["outputs"]["pd"] == pytest.approx(p * 0.1)
