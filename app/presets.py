"""可复核的空气示例参数（常温常压、毫米级间隙）。

气体系数来源
~~~~~~~~~~~~
采用 Townsend/Paschen 经典拟合中广泛引用的空气参数：

    A = 11.25  (Torr·cm)^-1
    B = 273.75 V/(Torr·cm)
    gamma = 0.01  (金属极板二次电子发射系数的常用估值)

该组 A、B 是经典空气 Paschen 拟合中常被引用的一组数值，采用
(Torr, cm, V) 自洽单位。换算到 SI（1 Torr = 133.322 Pa、1 cm = 0.01 m，
即 1 Torr·cm = 1.33322 Pa·m）：A ≈ 8.44 (Pa·m)^-1、
B ≈ 205.3 V/(Pa·m)。注意不同教材因拟合的 E/p 区间不同，还常给出
A≈15 (Torr·cm)^-1、B≈365 V/(Torr·cm) 的另一组值，二者不可混用；
本服务示例以本表自洽单位为准。出处：

  * F. Paschen, "Das Funkenpotential in Luft, Wasserstoff und Argun",
    Annalen der Physik 300 (1897) 69–96（原始 Paschen 定律）；
  * J. D. Cobine, *Gaseous Conductors*, Dover, 1958（空气 A≈15 /(cm·Torr)
    的另一常见拟合区间，本服务采用的 11.25/273.75 是同书给出的
    E/p≈100–800 V/(cm·Torr) 拟合区间取值）；
  * M. A. Uman, *Lightning: Its Physics and Effects*, Dordrecht, 1987；
  * 教科书：S. Glasstone & D. Edelsack 及《高电压技术》（华中工学院、
    赵智大 主编等）所列标准空气 Paschen 表。

注意：不同来源因拟合的 E/p 区间不同，A、B 会有出入；本示例仅用于
量级核对（千伏量级），工程设计请按实际气体、电极材料与温湿度重新拟合。

示例工况：p = 760 Torr（标准大气压）、d = 0.1 cm（1 mm 间隙），
即 p*d = 76 Torr·cm，落在右支，击穿电压约 4 kV。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AirExample:
    p: float
    d: float
    a: float
    b: float
    gamma: float
    p_unit: str
    d_unit: str
    expected_voltage_order_volts: tuple[float, float]
    description: str
    source: str


AIR_EXAMPLE = AirExample(
    p=760.0,          # Torr，标准大气压
    d=0.1,            # cm，即 1 mm
    a=11.25,          # 1/(Torr*cm)
    b=273.75,         # V/(Torr*cm)
    gamma=0.01,
    p_unit="Torr",
    d_unit="cm",
    # 复核带：击穿电压必须落在千伏量级，且为正有限值。
    expected_voltage_order_volts=(1.0e3, 1.0e4),
    description=(
        "标准大气压（760 Torr）空气、1 mm（0.1 cm）均匀场间隙，"
        "gamma=0.01 的金属极板"
    ),
    source=(
        "Paschen 1897；Cobine, Gaseous Conductors (Dover 1958)；"
        "Uman, Lightning (1987)"
    ),
)
