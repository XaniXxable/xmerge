from dataclasses import dataclass

from .node import Node


@dataclass(frozen=True, slots=True)
class DottedPath(Node):
    keys: tuple[str, ...]
