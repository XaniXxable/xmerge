from dataclasses import dataclass

from .constat_value import ConstantValue
from .data_path_ref import DataPathRef
from .node import Node
from .xml_path import XmlPath

type MappingSource = ConstantValue | DataPathRef


@dataclass(frozen=True, slots=True, kw_only=True)
class MappingRule(Node):
    source: MappingSource
    target: XmlPath
