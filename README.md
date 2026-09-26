# Paschen 气体击穿核算 HTTP 后端

均匀电场下气体击穿电压（Paschen 定律）的长期运行 HTTP 计算服务。
仅提供 JSON API，无前端、无账户/权限；范围限定在气体击穿这一件事。

- Python 3.12 + FastAPI（异步）
- PostgreSQL 16（asyncpg / SQLAlchemy 2）
- Docker Compose 一键编排（服务 + 数据库）
- 计算内核 / 曲线扫描 / 参数校验 / 持久化分层拆模块
- 自动化测试锁定全部跨输入物理不变量与并发留痕

## 物理模型

Townsend 自持放电判据给出的 Paschen 公式：

```
              B · p · d
Vs = ─────────────────────────────
        ⎛ A · p · d          ⎞
     ln⎜──────────────────── ⎟
        ⎝ ln(1 + 1/γ)        ⎠
```

记 `L = ln(1 + 1/γ)`、`x = p·d`：

- 五个输入 p、d、A、B、γ 必须全部为**有限的严格正数**，否则 422 拒绝；
- 对数量真数 `A·x/L` 必须**严格大于 1**：等于 1 时 Vs 发散为 +∞，
  小于 1 时不存在自持放电——两种情况都返回带中文原因的错误 JSON，
  绝不凑一个数出来；
- 曲线最低点（由 dVs/dx = 0 得到）：

```
pd_min = e · ln(1 + 1/γ) / A          Vs_min = B · pd_min
```

`pd < pd_min` 为左支（pd 增大 Vs 下降），`pd > pd_min` 为右支（pd 增大
Vs 上升）。`ln(1+1/γ)` 是公式分母与最小点位置的关键项，漏放或挪错会让
整条曲线的最小点漂移——该关系被测试精确锁定。

### 空气示例（可复核）

`GET /api/v1/example/air` 预置：p = 760 Torr（标准大气压）、d = 0.1 cm
（1 mm 间隙）、A = 11.25 (Torr·cm)⁻¹、B = 273.75 V/(Torr·cm)、γ = 0.01。

实时核算结果 **Vs ≈ 3984 V（约 3.98 kV），右支，pd = 76 Torr·cm**；
该气体系数下 pd_min ≈ 1.115 Torr·cm、Vs_min ≈ 305 V。

来源（详见 `app/presets.py` 模块说明）：

- F. Paschen, *Annalen der Physik* 300 (1897), 69–96（Paschen 原始定律）；
- J. D. Cobine, *Gaseous Conductors*, Dover, 1958（空气 A/B 经典拟合）；
- M. A. Uman, *Lightning: Its Physics and Effects*, 1987。

不同教材因拟合的 E/p 区间不同会给出另一组常见值（A≈15、B≈365），
不可与本组混用；单位必须自洽（本服务不做隐式单位换算）。

## 快速开始

```bash
docker compose up --build
```

服务在 http://localhost:8000 ，OpenAPI 交互文档 http://localhost:8000/docs ，
PostgreSQL 16 数据落在命名卷 `pgdata`。等数据库健康检查通过后 API 才启动，
启动时自动建表。

### 本地直接运行（可选，用 SQLite 或外部 PostgreSQL）

```bash
pip install -r requirements.txt
export PASCHEN_DATABASE_URL="postgresql+asyncpg://paschen:paschen@localhost:5432/paschen"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

环境变量（均以 `PASCHEN_` 为前缀）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PASCHEN_DATABASE_URL` | 本地 PG 的 asyncpg DSN | SQLAlchemy 异步 DSN；测试用 `sqlite+aiosqlite://` |
| `PASCHEN_PERSIST_ENABLED` | `true` | 设 `0/false` 关闭留痕，不影响核算 |

## API

### 1. 单点核算 `POST /api/v1/breakdown`

```json
{"p": 760, "d": 0.1, "A": 11.25, "B": 273.75, "gamma": 0.01,
 "note": "可选备注"}
```

返回 `pd`、`breakdown_voltage`（伏）及 `_kv`、`branch`（left/right/minimum
含中文说明）、该气体系数的 `pd_min`、`vs_min`、供复核的 `secondary_log`
= ln(1+1/γ)，以及留痕 `record_id`。加 `?persist=false` 可只算不留痕。

### 2. 曲线扫描 `POST /api/v1/scan`

```json
{"A": 11.25, "B": 273.75, "gamma": 0.01,
 "pd_start": 0.1, "pd_end": 4.0, "num_points": 301}
```

在 pd 区间上**均匀实时逐点调用同一核算内核**（与单点接口同源，不烘焙任何
曲线）。每个点带 `breakable` 标记：落在对数非法区（p·d ≤ L/A）的点
`breakdown_voltage` 为 `null` 并附原因，不会被静默跳过，因此 U 形和左支
边界发散都被如实保留。响应同时给出理论 `pd_min`/`vs_min` 和本次采样实际
观测到的 `observed_minimum_pd`/`observed_minimum_vs`。

### 3. 空气示例 `GET /api/v1/example/air`

参数、单位、文献来源与当场算出的结果一起返回。

### 4. 留痕

- `GET /api/v1/records?limit=50&kind=single|scan` 最近记录（倒序）；
- `GET /api/v1/records/{id}` 单条记录，含完整输入快照与逐点输出。

每次核算都是一条独立 INSERT（数据库分配自增主键），并发提交只追加、
不覆盖、不串号。

### 错误 JSON 形状

所有 422（物理非法 / 请求校验失败）均为：

```json
{"error": "no_self_sustained_discharge",
 "reason": "不存在自持放电：……可击穿要求 p*d > 0.410233 ……"}
```

错误码：`non_positive_input`、`non_finite_input`、`non_numeric_input`、
`no_self_sustained_discharge`、`invalid_pd_range`、`invalid_num_points`、
`invalid_request`。

## curl 示例

```bash
curl -s localhost:8000/api/v1/breakdown -H 'Content-Type: application/json' \
  -d '{"p":760,"d":0.1,"A":11.25,"B":273.75,"gamma":0.01}'

curl -s localhost:8000/api/v1/scan -H 'Content-Type: application/json' \
  -d '{"A":11.25,"B":273.75,"gamma":0.01,"pd_start":0.1,"pd_end":4,"num_points":301}'
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest                 # 测试夹具自动用内存 SQLite，不需要 Docker/PG
```

覆盖：

- 空气示例千伏量级、正且有限；
- p/d 互换乘积不变 ⇒ Vs 完全不变；间隙加倍沿曲线平移而非翻倍；
- γ 增大 ⇒ Vs 整体下降；
- `pd_min = e·ln(1+1/γ)/A`、`Vs_min = B·pd_min` 精确值；逼近 pd_min 时
  采样取区间最小、两侧严格回升（左降右升单调性逐网格点检验）；
- 同一电压的左右两支反解一致；
- 非正 / 非有限 / 无自持放电 / 区间反向 / 采样点过少均被正确拒绝；
- HTTP 层契约、错误 JSON、留痕列表/明细；
- 40 组不同参数并发提交：id 唯一、列字段与 JSON 快照逐行不串号。

## 模块划分

```
app/
  physics.py      纯函数内核：公式、最小点、支别判定、反解
  validation.py   正数/有限输入校验
  scanning.py     pd 区间实时逐点扫描（复用 physics，不烘焙曲线）
  presets.py      空气示例参数与文献来源
  schemas.py      Pydantic 请求/响应
  config.py       环境变量配置
  db.py           异步引擎、会话、建表
  models.py       ORM 留痕表
  repository.py   只追加的留痕仓储
  service.py      核算编排：内核 → 序列化 → 留痕
  routers/        HTTP 路由
  main.py         入口、统一错误 JSON
tests/            内核不变量 + HTTP 契约 + 并发留痕
```
