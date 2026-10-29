from dataclasses import dataclass
from pathlib import PurePath

from .node import Node
from .primitives import InputAlias


@dataclass(frozen=True, slots=True, kw_only=True)
class InputDeclaration(Node):
    file_path: PurePath
    alias: InputAlias
