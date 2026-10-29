from dataclasses import dataclass

from .node import Node


@dataclass(frozen=True, slots=True, kw_only=True)
class ExcelPath(Node):
    sheet: str
    cell: str
    cell_end: str | None
