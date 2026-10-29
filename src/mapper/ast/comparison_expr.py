from dataclasses import dataclass

from .comparison_operator import ComparisonOperator
from .expression_node import ExpressionNode


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonExpr(ExpressionNode):
    left: ExpressionNode
    operator: ComparisonOperator
    right: ExpressionNode
