from dataclasses import dataclass

from .input_decl import InputDeclaration
from .node import Node
from .output_decl import OutputDeclaration
from .unions import RunStatement


@dataclass(frozen=True, slots=True, kw_only=True)
class RunDefinition(Node):
    inputs: list[InputDeclaration]
    output: OutputDeclaration
    statements: list[RunStatement]
