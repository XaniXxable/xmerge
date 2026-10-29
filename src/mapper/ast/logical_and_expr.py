from dataclasses import dataclass

from .expression_node import ExpressionNode


@dataclass(frozen=True, slots=True, kw_only=True)
class LogicalAndExpr(ExpressionNode):
    left: ExpressionNode
    right: ExpressionNode
