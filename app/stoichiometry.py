"""投料化学计量计算：反应进度、限量试剂、消耗/剩余与理论产量。

入参投料量为 :class:`decimal.Decimal`（非负十进制摩尔数）。内部把
Decimal 精确转换为 :class:`fractions.Fraction` 做有理数运算——
反应进度 ``ξ = min(投料量 ÷ 系数)``、消耗量、剩余量与理论产量都是
精确值，因此并列限量（如 1:1 与 2:2 投料）能被完整识别，限量试剂
的剩余量恒为精确的 0。输出时再按 28 位有效数字（ROUND_HALF_EVEN）
正确舍入为 Decimal，并以普通十进制字符串（非科学计数法）返回，
全程不经过二进制浮点，避免浮点误差。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction

# 输出精度：28 位有效数字（decimal 默认上下文精度），半偶舍入
_OUTPUT_CONTEXT = Context(prec=28)


@dataclass(frozen=True)
class ReactantAmount:
    """一种反应物的投料与消耗结果（摩尔，Decimal）。"""

    coefficient: int
    fed: Decimal
    consumed: Decimal
    remaining: Decimal
    limiting: bool


@dataclass(frozen=True)
class StoichiometryResult:
    """一次投料计量计算的全部结果，顺序与配平后的物种顺序一致。"""

    extent: Decimal                       # 反应进度 ξ
    reactants: tuple[ReactantAmount, ...]
    product_yields: tuple[Decimal, ...]   # 每种生成物的理论产量


def compute_stoichiometry(
    reactant_coefficients: list[int],
    product_coefficients: list[int],
    feeds: list[Decimal],
) -> StoichiometryResult:
    """按配平系数与投料量计算反应进度及物料衡算。

    ``feeds`` 与 ``reactant_coefficients`` 一一对应（同一反应物顺序）。
    反应进度 ``ξ = min(投料量 / 系数)``；达到最小值的全部反应物为并列
    限量试剂，其消耗量等于投料量、剩余量为 0；其余反应物消耗
    ``ξ × 系数``。生成物理论产量为 ``ξ × 系数``。
    """
    exact_feeds = [Fraction(fed) for fed in feeds]
    ratios = [fed / coef for fed, coef in zip(exact_feeds, reactant_coefficients)]
    extent = min(ratios)

    amounts: list[ReactantAmount] = []
    for fed_dec, fed, coef, ratio in zip(
        feeds, exact_feeds, reactant_coefficients, ratios
    ):
        if ratio == extent:
            # 限量试剂：完全消耗，剩余精确的 0（保留投料的原始 Decimal 表示）
            consumed, remaining, limiting = fed_dec, Decimal(0), True
        else:
            consumed = _to_decimal(extent * coef)
            remaining = _to_decimal(fed - extent * coef)
            limiting = False
        amounts.append(
            ReactantAmount(
                coefficient=coef,
                fed=fed_dec,
                consumed=consumed,
                remaining=remaining,
                limiting=limiting,
            )
        )

    return StoichiometryResult(
        extent=_to_decimal(extent),
        reactants=tuple(amounts),
        product_yields=tuple(_to_decimal(extent * coef) for coef in product_coefficients),
    )


def _to_decimal(value: Fraction) -> Decimal:
    """把精确有理数按输出精度（28 位有效数字）正确舍入为 Decimal。"""
    with localcontext(_OUTPUT_CONTEXT):
        return Decimal(value.numerator) / Decimal(value.denominator)


def decimal_text(value: Decimal) -> str:
    """格式化为普通十进制字符串（不用科学计数法），供 JSON 输出。"""
    return format(value, "f")
