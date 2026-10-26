"""Deterministic finite tools; no model, database, filesystem, or expression engine."""

import re
from decimal import Decimal, localcontext
from typing import Any

QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string", "minLength": 1, "maxLength": 2000}},
    "required": ["question"],
    "additionalProperties": False,
}
TOOLS = [
    {
        "name": "formula_hint",
        "description": "欧姆定律、牛顿第二定律的适用条件与检查提示。",
        "inputSchema": QUESTION_SCHEMA,
    },
    {
        "name": "unit_convert",
        "description": "固定模板单位换算：将 100 cm 转换为 m。",
        "inputSchema": QUESTION_SCHEMA,
    },
]
UNITS = {
    "mm": ("length", Decimal("0.001")),
    "cm": ("length", Decimal("0.01")),
    "m": ("length", Decimal(1)),
    "km": ("length", Decimal(1000)),
    "mg": ("mass", Decimal("0.001")),
    "g": ("mass", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "s": ("time", Decimal(1)),
    "min": ("time", Decimal(60)),
    "h": ("time", Decimal(3600)),
}
CONVERSION = re.compile(
    r"(?:将\s*|convert\s+)([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"(mm|cm|m|km|mg|g|kg|s|min|h)\s*(?:转换为|换算为|to)\s*"
    r"(mm|cm|m|km|mg|g|kg|s|min|h)\s*[。.]?",
    re.ASCII,
)


def text_result(text: str, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text[:4000]}], "isError": error}


def formula_hint(question: str) -> dict[str, Any]:
    if any(key in question.casefold() for key in ("欧姆", "ohm")):
        return text_result(
            "欧姆定律 U=IR：先检查导体温度等条件是否稳定；统一 V、A、Ω 单位，区分电压、电流与电阻。"
        )
    if any(key in question.casefold() for key in ("牛顿第二", "newton's second", "f=ma")):
        return text_result(
            "牛顿第二定律 ΣF=ma：在惯性参考系中先画受力图，求合外力而非某一个力；"
            "统一 N、kg、m/s² 单位。"
        )
    return text_result("不支持该主题；仅支持欧姆定律、牛顿第二定律提示。", error=True)


def unit_convert(question: str) -> dict[str, Any]:
    match = CONVERSION.fullmatch(question.strip())
    if match is None:
        return text_result("不支持该问题；请使用固定模板，例如：将 100 cm 转换为 m。", error=True)
    number, source, target = match.groups()
    if UNITS[source][0] != UNITS[target][0]:
        return text_result("不能转换不同维度的单位。", error=True)
    with localcontext() as context:
        context.prec = max(32, len(number) + 16)
        value = Decimal(number) * UNITS[source][1] / UNITS[target][1]
        if not value.is_finite():
            return text_result("数值必须有限。", error=True)
        output = format(value, "f")
        if "." in output:
            output = output.rstrip("0").rstrip(".")
    return text_result(f"{number} {source} = {output} {target}；按同维度单位比例换算。")


HANDLERS = {"formula_hint": formula_hint, "unit_convert": unit_convert}
