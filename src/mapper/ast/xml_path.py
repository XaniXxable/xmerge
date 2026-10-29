from dataclasses import dataclass

from .node import Node
from .xml_path_segment import XmlPathSegment


@dataclass(frozen=True, slots=True, kw_only=True)
class XmlPath(Node):
    segments: list[XmlPathSegment]
