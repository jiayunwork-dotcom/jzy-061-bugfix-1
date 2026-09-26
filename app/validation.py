"""参数校验：把 HTTP 层传入的原始值挡在物理核算之前。

物理内核本身也会做防御性校验（纯函数不能信任任何调用方）；这里的校验供扫描等
内部模块复用，并集中维护"五个物理量必须严格为正且有限"这条规则。
"""

from __future__ import annotations

import math
from typing import Any

from .physics import PaschenDomainError

_POSITIVE_FIELDS = ("p", "d", "A", "B", "gamma", "pd_start", "pd_end")


def require_positive_finite(**values: Any) -> dict[str, float]:
    """校验所有给定物理量为有限的严格正数，返回 float 化后的字典。"""
    cleaned: dict[str, float] = {}
    for name, value in values.items():
        if name not in _POSITIVE_FIELDS:
            # 编程错误而非用户输入，直接抛出
            raise ValueError(f"未知的物理量字段: {name}")
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
        cleaned[name] = value
    return cleaned
