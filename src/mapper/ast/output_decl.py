from dataclasses import dataclass
from pathlib import PurePath

from .node import Node


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputDeclaration(Node):
    file_path: PurePath
