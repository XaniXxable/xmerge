from dataclasses import dataclass

from .node import Node
from .primitives import InputAlias


@dataclass(frozen=True, slots=True)
class NameRef(Node):
    alias: InputAlias
