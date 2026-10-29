from .ast import Node


class DslError(Exception):
    """An error in the .map script, with the position it occurred at."""

    def __init__(self, message: str, *, node: Node) -> None:
        super().__init__(f"{node.line}:{node.column}: {message}")
        self.message: str = message
        self.location: Node = node


class DslSyntaxError(DslError):
    """The text does not match the grammar (lexer/parser stage)."""
