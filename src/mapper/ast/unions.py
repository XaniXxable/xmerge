from .comparison_expr import ComparisonExpr
from .condition_clause import ConditionClause
from .data_path_ref import DataPathRef
from .literal_expr import LiteralExpr
from .logical_and_expr import LogicalAndExpr
from .logical_or_expr import LogicalOrExpr
from .mapping_rule import MappingRule

type RunStatement = ConditionClause | MappingRule
type ConditionExpr = LiteralExpr | DataPathRef | ComparisonExpr | LogicalAndExpr | LogicalOrExpr
