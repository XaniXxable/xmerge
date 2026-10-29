from dataclasses import dataclass

from .node import Node


@dataclass(frozen=True, slots=True, kw_only=True)
class XmlChildFilterText(Node):
    """`[Name="x"]`: select the element whose child <Name> has text "x"."""

    child_tag: str
    expected_text: str
