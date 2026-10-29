from dataclasses import dataclass

from .expression_node import ExpressionNode
from .primitives import LiteralValue


@dataclass(frozen=True, slots=True, kw_only=True)
class LiteralExpr(ExpressionNode):
    value: LiteralValue
