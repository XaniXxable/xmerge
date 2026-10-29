from dataclasses import dataclass

from .node import Node
from .primitives import LiteralValue


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstantValue(Node):
    value: LiteralValue
