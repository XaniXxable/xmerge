from dataclasses import dataclass

from .dotted_path import DottedPath
from .excel_path import ExcelPath
from .expression_node import ExpressionNode
from .name_ref import NameRef
from .xml_path import XmlPath


@dataclass(frozen=True, slots=True)
class DataPathRef(ExpressionNode):
    name: NameRef
    data_path: DottedPath | XmlPath | ExcelPath
