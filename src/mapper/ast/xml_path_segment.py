# xml_path_segment.py
from dataclasses import dataclass

from .node import Node
from .xml_child_text_filter import XmlChildFilterText


@dataclass(frozen=True, slots=True)
class XmlPathSegment(Node):
    element_tag: str
    filter: XmlChildFilterText | None
