from dataclasses import dataclass

from .expression_node import ExpressionNode
from .node import Node


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionClause(Node):
    expression: ExpressionNode
